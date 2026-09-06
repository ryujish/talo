"""프로젝트 재개: 원문 참조, 확정 기억, 구체적 열린 작업을 인계한다."""
from __future__ import annotations

import hashlib
import json
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS work_tasks (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, session_id TEXT NOT NULL,
    run_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
    evidence TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
"""


def text_content(raw: str) -> str:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    if isinstance(value, dict):
        return str(value.get("text", ""))
    if isinstance(value, list):
        return "\n".join(str(x.get("text") or "") for x in value if isinstance(x, dict) and x.get("type") == "text")
    return value if isinstance(value, str) else ""


def recent_messages(repository, session_id: str, limit: int = 40):
    rows = repository.conn.execute(
        "SELECT m.* FROM messages m JOIN runs r ON r.id=m.run_id WHERE r.session_id=? "
        "AND m.role IN ('user','assistant') ORDER BY m.created_at DESC,m.rowid DESC LIMIT ?",
        (session_id, limit)).fetchall()
    # 이전 미완료 도구 호출은 재생하지 않는다. 텍스트 원문만 provider 중립으로 복구한다.
    return [{"role": row["role"], "content": text_content(row["content_json"])}
            for row in reversed(rows) if text_content(row["content_json"])]


def begin_task(repository, workspace_id, session_id, run_id, request):
    tid = "task_" + uuid.uuid4().hex[:12]
    now = time.time()
    repository.conn.execute("INSERT INTO work_tasks VALUES(?,?,?,?,?,?,?,?,?)",
                            (tid, workspace_id, session_id, run_id, request, "in_progress", None, now, now))
    repository.conn.commit()
    return tid


def tasks(repository, workspace_id):
    return [dict(r) for r in repository.conn.execute(
        "SELECT * FROM work_tasks WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,))]


def finish_task(repository, workspace_id, task_id, evidence):
    if not evidence.strip():
        raise ValueError("완료 확인 근거를 입력하세요")
    cur = repository.conn.execute("UPDATE work_tasks SET status='done',evidence=?,updated_at=? "
                                  "WHERE id=? AND workspace_id=?", (evidence, time.time(), task_id, workspace_id))
    repository.conn.commit()
    if not cur.rowcount:
        raise ValueError("현재 작업 공간의 작업을 찾지 못했습니다")


def state_hash(snapshot):
    return hashlib.sha256(json.dumps({k: v for k, v in snapshot.items() if k != "at"},
                                    sort_keys=True).encode()).hexdigest()


def save_handoff(runtime, outcome, workspace_id, project_id, request):
    from talo.changes.manager import ChangeManager
    repository = runtime.repository
    status = "needs_review" if outcome.exit_code == 0 else "blocked"
    repository.conn.execute("UPDATE work_tasks SET status=?,updated_at=? WHERE run_id=?",
                            (status, time.time(), outcome.run_id))
    repository.conn.commit()
    all_tasks = tasks(repository, workspace_id)
    open_tasks = [t for t in all_tasks if t["status"] != "done"]
    snapshot = runtime.workspace.snapshot()
    manager = ChangeManager(runtime.workspace.detect().root, repository.db.path,
                            runtime._artifacts_dir, workspace_id)
    changes = manager.list()
    pending = [c for c in changes if c["state"] in {"proposed", "applying", "undoing", "recovery_required"}]
    actions = [f"변경 검토: talo changes review {c['id']}" if c["state"] == "proposed"
               else f"변경 복구: talo changes recover {c['id']}" for c in pending]
    actions += [f"{t['title'][:200]} — {'완료 확인' if t['status'] == 'needs_review' else '남은 작업 재개'} ({t['id']})"
                for t in open_tasks[:8]]
    memories = repository.list_memories(project_id, status="confirmed")
    verifications = [dict(v) for v in repository.conn.execute(
        "SELECT * FROM verifications WHERE run_id=?", (outcome.run_id,))]
    previous = repository.latest_handoff(outcome.session_id)
    version = (previous["context_version"] if previous else 0) + 1
    row = repository.conn.execute("SELECT MAX(seq) FROM events WHERE session_id=?", (outcome.session_id,)).fetchone()
    doc = {"schema": "talo.handoff/0.2", "context_version": version,
           "identity": {"project_id": project_id, "workspace_id": workspace_id,
                        "session_id": outcome.session_id, "run_id": outcome.run_id},
           "goal": request, "goal_source": "run:" + outcome.run_id,
           "decisions": [dict(m) for m in memories if m["kind"] == "decision"],
           "constraints": [dict(m) for m in memories if m["kind"] == "rule"],
           "open_tasks": open_tasks, "completed_tasks": [t for t in all_tasks if t["status"] == "done"],
           "workspace": snapshot, "workspace_hash": state_hash(snapshot),
           "verification": verifications, "next_actions": actions,
           "changes": [{k: c[k] for k in ("id", "state", "patch_hash")} for c in changes[:20]],
           "unknowns": ["모델의 완료 응답은 사용자 목표 달성의 증거가 아닙니다"],
           "source_event_cursor": row[0] or 0, "previous_handoff_id": previous["id"] if previous else None,
           "generated_at": time.time()}
    repository.save_handoff(outcome.session_id, outcome.run_id, version, doc)
    repository.touch_session(outcome.session_id)
    outcome.handoff = doc
    return doc
