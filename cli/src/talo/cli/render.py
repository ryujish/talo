"""Rich 기반 사람용 렌더링."""
from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich import box
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


def header(info: dict[str, Any], model: str | None, mode: str, permission: str) -> None:
    lines = [
        f"[dim]프로젝트[/dim]  {info.get('root', '-')}  [dim]·[/dim]  {info.get('branch') or 'Git 없음'}",
        f"[dim]작업 방식[/dim]  [bold cyan]{mode}[/bold cyan]  [dim]· 권한[/dim]  {permission}",
        f"[dim]AI 모델[/dim]   {model or '연결 안 됨 — /connect로 설정'}",
    ]
    if info.get("limitation"):
        lines.append(f"[yellow]주의[/yellow] {info['limitation']}")
    console.print(Panel(
        "\n".join(lines),
        title="[bold cyan]Talo[/bold cyan]",
        subtitle="[dim]/help 명령 메뉴[/dim]",
        border_style="cyan",
        padding=(0, 1),
    ))


def menu_table(title: str, rows: list[tuple[str, str, str]]) -> None:
    """번호/명령, 메뉴명, 설명을 같은 모양으로 보여준다."""
    table = Table(title=title, box=box.ROUNDED, header_style="bold cyan", pad_edge=False)
    table.add_column("선택", style="bold cyan", no_wrap=True)
    table.add_column("메뉴", style="bold", no_wrap=True)
    table.add_column("설명", style="dim")
    for key, name, description in rows:
        table.add_row(key, name, description)
    console.print(table)


def print_delta(text: str, end: str = "") -> None:
    console.print(text, end=end, markup=False)


def print_event(event_type: str, payload: dict[str, Any]) -> None:
    if event_type == "message.delta":
        console.print(payload.get("text", ""), end="", markup=False)
    elif event_type == "message.completed":
        if payload.get("text"):
            console.print()
    elif event_type == "tool.prepared":
        console.print(f"[dim]▸ {payload.get('tool')} 준비[/dim]")
    elif event_type == "tool.completed":
        status = payload.get("status", "?")
        color = {"success": "green", "error": "red", "denied": "yellow"}.get(status, "dim")
        summary = payload.get("summary", "")
        console.print(f"[{color}]▸ {payload.get('tool')} [{status}][/{color}] {summary[:160]}")
    elif event_type == "approval.required":
        console.print(f"[yellow]승인 필요: {payload.get('tool')} {json.dumps(payload.get('arguments', {}), ensure_ascii=False)[:120]}[/yellow]")
    elif event_type == "workspace.changed":
        console.print(f"[cyan]변경: {payload.get('paths')}[/cyan]")
    elif event_type == "verification.recorded":
        color = "green" if payload.get("result") == "passed" else "red"
        console.print(f"[{color}]검증 [{payload.get('result')}]: {payload.get('command')}[/{color}]")
    elif event_type == "run.failed":
        console.print(f"[red]실패: {payload.get('message', payload.get('error'))}[/red]")
    elif event_type == "run.paused":
        console.print(f"[yellow]일시 중지: {payload.get('reason')} — {payload.get('message', '')}[/yellow]")
    elif event_type == "run.completed":
        changes = payload.get("changes", {})
        verifs = payload.get("verifications", [])
        console.print()
        if changes and (changes.get("added") or changes.get("modified") or changes.get("removed")):
            console.print(f"변경: 추가 {changes.get('added')} 수정 {changes.get('modified')} 삭제 {changes.get('removed')}")
        if verifs:
            for v in verifs:
                console.print(f"검증 [{v.get('result')}]: {v.get('command')}")
    elif event_type == "run.started":
        console.print(f"[dim]작업 시작 (run {payload.get('run_id', '')[:16]}…)[/dim]")


def sessions_table(sessions: list[Any]) -> None:
    table = Table(title="세션")
    table.add_column("ID", style="dim")
    table.add_column("제목")
    table.add_column("상태")
    table.add_column("갱신")
    for s in sessions:
        table.add_row(s["id"][:16], s["title"] or "-", s["status"], str(s["updated_at"])[:19])
    console.print(table)


def connections_table(connections: list[Any], active_id: str | None = None) -> None:
    table = Table(title="AI 연결")
    table.add_column("ID")
    table.add_column("공급자")
    table.add_column("모델")
    table.add_column("상태")
    for c in connections:
        marker = " *" if c.connection_id == active_id else ""
        table.add_row(c.connection_id + marker, c.provider_id, c.model_id or "-",
                      f"validated_at={c.validated_at or '미검증'}")
    if not connections:
        console.print("[yellow]연결 없음. `talo connect add`로 추가하세요.[/yellow]")
    else:
        console.print(table)


def jobs_table(rows: list[dict[str, Any]]) -> None:
    table = Table(title="예약 작업")
    table.add_column("ID", style="dim")
    table.add_column("이름")
    table.add_column("일정")
    table.add_column("상태")
    table.add_column("값")
    for r in rows:
        table.add_row(r.get("id", "")[:16], r.get("name", "-"),
                      r.get("schedule", r.get("scheduled_for", "-")),
                      r.get("state", r.get("enabled", "-")),
                      r.get("error", r.get("next_run_at", r.get("run_id", "-"))))
    console.print(table)


def approval_requests_table(requests: list[Any]) -> None:
    from talo.sanitize import sanitize_scope_json

    table = Table(title="승인 요청 Inbox")
    table.add_column("ID", style="dim")
    table.add_column("도구")
    table.add_column("상태")
    table.add_column("생성")
    table.add_column("결정")
    table.add_column("범위(정제)")
    for r in requests:
        table.add_row(
            r["id"][:16],
            r["tool_name"],
            r["status"],
            str(r["created_at"])[:19],
            str(r["decided_at"])[:19] if r["decided_at"] else "-",
            sanitize_scope_json(r["scope_json"])[:100],
        )
    console.print(table)


def doctor_report(checks: list[dict[str, Any]]) -> None:
    table = Table(title="talo doctor")
    table.add_column("항목")
    table.add_column("상태")
    table.add_column("내용")
    for c in checks:
        style = {"ok": "green", "warn": "yellow", "fail": "red"}.get(c["status"], "dim")
        table.add_row(c["name"], f"[{style}]{c['status']}[/{style}]", c.get("detail", ""))
    console.print(table)


def markdown(text: str) -> None:
    console.print(Markdown(text))
