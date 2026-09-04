"""승인 요청 Inbox CLI.

talo inbox list                 대기·기록된 승인 요청 목록 (scope 정제 표시)
talo inbox approve <id>         요청 승인 (상태만 변경 — 자동 재생 없음)
talo inbox deny <id>            요청 거절 (상태만 변경 — 자동 재생 없음)
"""
from __future__ import annotations

from typing import Any

from talo.schemas import ExitCode


def _ctx() -> Any:
    from talo.application.service import create_app_context
    return create_app_context()


def cmd_inbox_list(args: Any) -> int:
    from talo.cli import render
    ctx = _ctx()
    try:
        status = getattr(args, "status", None)
        requests = ctx.repository.list_approval_requests(status=status, limit=100)
        if not requests:
            render.console.print("[yellow]승인 요청이 없습니다.[/yellow]")
            return int(ExitCode.COMPLETED)
        render.approval_requests_table(requests)
        return int(ExitCode.COMPLETED)
    finally:
        ctx.close()


def _decide(args: Any, status: str) -> int:
    from talo.cli import render
    ctx = _ctx()
    try:
        req = ctx.repository.get_approval_request(args.request_id)
        if req is None:
            render.console.print(f"[red]승인 요청을 찾지 못함: {args.request_id}[/red]")
            return int(ExitCode.INPUT_ERROR)
        if req["status"] != "pending":
            render.console.print(f"[yellow]이미 결정된 요청입니다 (현재: {req['status']}).[/yellow]")
            return int(ExitCode.INPUT_ERROR)
        ok = ctx.repository.decide_approval_request(args.request_id, status, "user")
        if not ok:
            render.console.print(f"[yellow]요청을 결정하지 못했습니다: {args.request_id}[/yellow]")
            return int(ExitCode.INPUT_ERROR)
        label = "승인됨" if status == "approved" else "거절됨"
        render.console.print(f"[green]{req['tool_name']} 요청 {args.request_id[:16]} {label} (자동 재생 없음).[/green]")
        return int(ExitCode.COMPLETED)
    finally:
        ctx.close()


def cmd_inbox_approve(args: Any) -> int:
    return _decide(args, "approved")


def cmd_inbox_deny(args: Any) -> int:
    return _decide(args, "denied")
