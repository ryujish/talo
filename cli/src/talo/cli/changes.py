"""CLI/TUI가 공유하는 변경 검토와 복구 화면."""
from __future__ import annotations

import json
import sys

from talo.changes.manager import ChangeError, for_context


def print_diff(text: str):
    from talo.cli.render import console
    from rich.text import Text
    # 원본의 ANSI 제어문자가 터미널에서 실행되지 않도록 Rich Text로 렌더링한다.
    text = "".join(c if c in "\n\t" or ord(c) >= 32 and ord(c) != 127 else "�" for c in text)
    for line in text.splitlines():
        style = "green" if line.startswith("+") else "red" if line.startswith("-") else "cyan" if line.startswith("@@") else ""
        console.print(Text(line, style=style))


def show_changes(ctx, action="list", cid=None, *, patch_hash=None, json_out=False):
    from talo.cli.render import console
    manager = for_context(ctx)
    try:
        if action == "list":
            result = [{"id": c["id"], "state": c["state"], "patch_hash": c["patch_hash"],
                       "files": [f["path"] for f in c["manifest"]["files"]]} for c in manager.list()]
            if not json_out:
                for c in result:
                    console.print(f"{c['id']}  {c['state']}  {', '.join(c['files'])}", markup=False)
                if not result:
                    console.print("저장된 Talo 변경이 없습니다.")
        elif action in {"diff", "review"}:
            if cid is None:
                pending = manager.list("proposed") or manager.list()
                if not pending:
                    print_diff(ctx.workspace.git_diff() or "(변경 없음)")
                    return 0
                cid = pending[0]["id"]
            c = manager.get(cid)
            result = {"id": cid, "state": c["state"], "patch_hash": c["patch_hash"], "diff": manager.diff(cid)}
            if not json_out:
                console.print(f"{cid} · {c['state']} · {c['manifest']['match_method']}", markup=False)
                print_diff(result["diff"])
                console.print("승인 해시: " + c["patch_hash"], markup=False)
                if action == "review" and c["state"] == "proposed" and sys.stdin.isatty():
                    answer = input("적용 [a] / 취소 [x] / 검토 유지 [Enter]: ").strip().lower()
                    if answer == "a":
                        result = manager.apply(cid, c["patch_hash"])
                        console.print("적용했습니다. /undo 또는 talo undo로 되돌릴 수 있습니다.")
                    elif answer == "x":
                        result = manager.cancel(cid)
                        console.print("변경을 취소했습니다.")
        elif action == "apply":
            if not cid or not patch_hash:
                raise ChangeError("APPROVAL_REQUIRED", "변경 ID와 검토한 --hash가 필요합니다")
            result = manager.apply(cid, patch_hash)
        elif action == "cancel":
            if not cid:
                raise ChangeError("INVALID_ACTION", "변경 ID가 필요합니다: talo changes cancel <change-id>")
            result = manager.cancel(cid)
        elif action == "recover":
            if not cid:
                raise ChangeError("INVALID_ACTION", "변경 ID가 필요합니다: talo changes recover <change-id>")
            result = manager.recover(cid)
        elif action == "undo":
            result = manager.undo(cid)
        else:
            raise ChangeError("INVALID_ACTION", "알 수 없는 변경 동작")
        if json_out:
            print(json.dumps(result, ensure_ascii=False))
        elif action not in {"list", "diff", "review"}:
            console.print(f"{result['id']} · {result['state']}", markup=False)
        return 0
    except (ChangeError, OSError, RuntimeError) as exc:
        result = {"ok": False, "code": getattr(exc, "code", "CHANGE_ERROR"), "error": str(exc)}
        if json_out:
            print(json.dumps(result, ensure_ascii=False))
        else:
            console.print(result["code"] + ": " + str(exc), markup=False, style="yellow")
        return 1


def show_resume(ctx, session_id):
    from talo.cli.render import console
    from talo.continuity import state_hash, tasks, text_content
    from talo.sanitize import redact_text

    def clean(value, max_len=180):
        return redact_text(str(value), max_len) if value is not None else ""

    row = ctx.repository.latest_handoff(session_id)
    if row:
        try:
            doc = json.loads(row["document_json"] or "{}")
        except (TypeError, ValueError):
            doc = {}
        goal = doc.get("goal") or "확인되지 않음"
        console.print("마지막 목표: " + clean(goal), markup=False)

        completed = doc.get("completed_tasks") or []
        if completed:
            console.print("완료:")
            for t in completed:
                if isinstance(t, dict):
                    ev = f" [근거: {clean(t.get('evidence'))}]" if t.get("evidence") else ""
                    console.print(f"  - [x] {clean(t.get('title'))} ({clean(t.get('id'))}){ev}", markup=False)
                else:
                    console.print(f"  - [x] {clean(t)}", markup=False)
        else:
            console.print("완료: 없음", markup=False)

        open_tasks = doc.get("open_tasks")
        if open_tasks is None:
            open_tasks = [t for t in tasks(ctx.repository, ctx.workspace_id) if t.get("status") != "done"]
        if open_tasks:
            console.print("남은 일:")
            for t in open_tasks:
                if isinstance(t, dict):
                    status = clean(t.get("status") or "open", 40)
                    console.print(f"  - [{status}] {clean(t.get('title'))} ({clean(t.get('id'))})", markup=False)
                else:
                    console.print(f"  - [open] {clean(t)}", markup=False)
        else:
            console.print("남은 일: 없음", markup=False)

        verifications = doc.get("verification") or []
        if verifications:
            console.print("검증:")
            for v in verifications:
                if isinstance(v, dict):
                    desc = v.get("operation_id") or v.get("command") or v.get("id") or "검증"
                    res = v.get("result") or v.get("status") or ("성공" if v.get("exit_code") == 0 else "실패")
                else:
                    desc, res = v, ""
                console.print(f"  - {clean(desc)}{': ' + clean(res) if res else ''}", markup=False)
        else:
            console.print("검증: 없음", markup=False)

        actions = doc.get("next_actions") or []
        if actions:
            console.print("다음 행동:")
            for a in actions:
                console.print(f"  - {clean(a)}", markup=False)
        else:
            console.print("다음 행동: 없음", markup=False)

        if (doc.get("workspace_hash") and hasattr(ctx, "workspace") and ctx.workspace is not None
                and doc["workspace_hash"] != state_hash(ctx.workspace.snapshot())):
            console.print("작업 파일 상태가 달라졌습니다. 이전 검증은 최신 상태의 성공 근거가 아닙니다.", style="yellow")
    else:
        console.print("이전 handoff 기록이 없습니다.", markup=False)
        remaining = [t for t in tasks(ctx.repository, ctx.workspace_id) if t.get("status") != "done"]
        if remaining:
            console.print("남은 일:")
            for t in remaining:
                console.print(f"  - [{clean(t.get('status') or 'open', 40)}] {clean(t.get('title'))} ({clean(t.get('id'))})", markup=False)

    pending = for_context(ctx).list("proposed")
    for change in pending:
        console.print("검토 대기: talo changes review " + change["id"], markup=False)

    last = ctx.repository.conn.execute(
        "SELECT m.content_json FROM messages m JOIN runs r ON r.id=m.run_id "
        "WHERE r.session_id=? AND m.role='assistant' ORDER BY m.created_at DESC,m.rowid DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    console.print("마지막 문구: " + clean(text_content(last["content_json"]) if last else "없음", 400), markup=False)
