"""로컬 headless 코어의 버전 있는 stdio JSONL 계약.

같은 프로세스에서 요청을 직렬 처리한다. HTTP/브라우저 전송은 후속 어댑터다.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import hashlib
from pathlib import Path

from talo.application.service import create_app_context, run_request, start_session
from talo.changes.manager import for_context
from talo.continuity import tasks


def serve():
    for line in sys.stdin:
        request_id = None
        ctx = None
        try:
            if len(line) > 1024 * 1024:
                raise ValueError("요청 크기 상한을 초과했습니다")
            req = json.loads(line)
            request_id = req.get("id")
            if req.get("version") != 1 or not isinstance(request_id, str):
                raise ValueError("version=1과 문자열 id가 필요합니다")
            method = req.get("method")
            if method == "health":
                result = {"protocol_version": 1, "transport": "stdio", "status": "ready"}
            else:
                ctx = create_app_context(Path(req["cwd"]))
                manager = for_context(ctx)
                params = req.get("params", {})
                mutating = method in {"session.start", "run", "changes.apply", "changes.undo", "changes.cancel", "changes.recover", "tasks.done"}
                if mutating:
                    body_hash = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
                    ctx.repository.conn.execute("BEGIN IMMEDIATE")
                    previous = ctx.repository.conn.execute("SELECT * FROM core_requests WHERE workspace_id=? AND request_id=?",
                                                           (ctx.workspace_id, request_id)).fetchone()
                    if previous:
                        ctx.repository.conn.rollback()
                        if previous["body_hash"] != body_hash:
                            raise ValueError("동일 요청 id에 다른 본문을 사용할 수 없습니다")
                        if previous["state"] != "complete":
                            raise ValueError("이전 요청 결과가 미확정입니다. 상태를 조회한 뒤 새 요청을 사용하세요")
                        print(previous["result_json"], flush=True)
                        continue
                    ctx.repository.conn.execute("INSERT INTO core_requests VALUES(?,?,?,?,?,?)",
                                                (ctx.workspace_id, request_id, body_hash, "started", None, time.time()))
                    ctx.repository.conn.commit()
                if method == "session.start":
                    result = {"session_id": start_session(ctx, params.get("title"))}
                elif method == "sessions.list":
                    result = [dict(s) for s in ctx.repository.list_sessions(ctx.workspace_id)]
                elif method == "run":
                    async def events(kind, payload):
                        print(json.dumps({"version": 1, "id": request_id, "type": "event", "event": kind,
                                          "payload": payload}, ensure_ascii=False), flush=True)
                    outcome = asyncio.run(run_request(ctx, params["request"], session_id=params["session_id"],
                                                      mode=params.get("mode", "dev"),
                                                      permission=params.get("permission", "project_edit"),
                                                      on_human=events))
                    result = {"run_id": outcome.run_id, "state": outcome.state.value,
                              "exit_code": int(outcome.exit_code), "summary": outcome.summary}
                elif method == "changes.list":
                    result = manager.list(params.get("state"))
                elif method == "changes.diff":
                    result = {"change": manager.get(params["change_id"]), "diff": manager.diff(params["change_id"])}
                elif method == "changes.apply":
                    result = manager.apply(params["change_id"], params["patch_hash"])
                elif method == "changes.undo":
                    result = manager.undo(params.get("change_id"))
                elif method == "changes.cancel":
                    result = manager.cancel(params["change_id"])
                elif method == "changes.recover":
                    result = manager.recover(params["change_id"])
                elif method == "tasks.list":
                    result = tasks(ctx.repository, ctx.workspace_id)
                elif method == "tasks.done":
                    from talo.continuity import finish_task
                    task_id = params.get("task_id")
                    evidence = params.get("evidence", "확인 완료")
                    if not task_id:
                        raise ValueError("task_id가 필요합니다")
                    finish_task(ctx.repository, ctx.workspace_id, task_id, evidence)
                    result = {"ok": True, "task_id": task_id, "status": "done"}
                else:
                    raise ValueError("지원하지 않는 method")
            response = json.dumps({"version": 1, "id": request_id, "type": "result", "result": result}, ensure_ascii=False)
            if ctx and mutating:
                ctx.repository.conn.execute("UPDATE core_requests SET state='complete',result_json=? WHERE workspace_id=? AND request_id=?",
                                            (response, ctx.workspace_id, request_id))
                ctx.repository.conn.commit()
            print(response, flush=True)
        except Exception as exc:
            print(json.dumps({"version": 1, "id": request_id, "type": "error",
                              "code": getattr(exc, "code", "REQUEST_ERROR"), "message": str(exc)},
                             ensure_ascii=False), flush=True)
        finally:
            if ctx:
                ctx.close()
    return 0
