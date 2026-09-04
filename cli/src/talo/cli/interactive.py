"""대화형 터미널 UI.

prompt_toolkit 입력 + Rich 렌더링. 한글 조합 입력·여러 줄 붙여넣기·좁은 화면을
해치지 않는 단순 구조를 유지한다. 실행 중 Ctrl+C는 중단 요청으로 처리한다.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from talo.schemas import ExitCode

COMMANDS_HELP = {
    "/help": ("도움말", "사용 가능한 명령과 사용법을 봅니다"),
    "/model": ("모델 선택", "현재 실행에 사용할 AI 모델을 바꿉니다"),
    "/connect": ("AI 연결", "AI 서비스 연결과 인증을 관리합니다"),
    "/plan": ("계획 모드", "파일을 바꾸지 않고 분석과 계획만 수행합니다"),
    "/dev": ("개발 모드", "허용된 범위에서 코드를 수정하고 검증합니다"),
    "/status": ("작업 상태", "최근 실행과 검증 결과를 확인합니다"),
    "/diff": ("변경 내용", "현재 Git 변경 요약을 확인합니다"),
    "/memory": ("기억 관리", "프로젝트 기억을 조회·추가·확정·삭제합니다"),
    "/sessions": ("세션 목록", "저장된 작업 세션을 확인합니다"),
    "/permissions": ("권한 설정", "현재 작업 방식과 권한을 확인합니다"),
    "/skills": ("스킬 목록", "사용 가능한 스킬과 설명을 확인합니다"),
    "/mcp": ("MCP 연결", "등록된 MCP 도구 연결 상태를 확인합니다"),
    "/export": ("내보내기", "세션 인계 자료를 Markdown 또는 JSON으로 저장합니다"),
    "/quit": ("종료", "Talo 대화형 세션을 종료합니다"),
}

SLASH_MENU_HEIGHT = len(COMMANDS_HELP) + 1
SLASH_MENU_STYLE = {
    "prompt": "bold #ffaf87",
    "completion-menu.completion": "bg:#1f1f1f #bcbcbc",
    "completion-menu.completion.current": "bg:#ffaf87 #1c1c1c bold",
    "completion-menu.meta.completion": "bg:#1f1f1f #777777",
    "completion-menu.meta.completion.current": "bg:#ffaf87 #1c1c1c",
    "scrollbar.background": "bg:#303030",
    "scrollbar.button": "bg:#ffaf87",
}


async def run_interactive(ctx: Any, session_id: str) -> int:
    from talo.application.service import run_request, start_session
    from talo.cli import render

    mode = ctx.config.default_mode
    permission = ctx.config.default_permission
    conn = ctx.resolver.active()
    model = None
    if conn and conn.connection:
        model = ctx.config.selected_model_id(conn.connection) or conn.connection.model_id
    info = ctx.repo_info.summary()
    render.header(info, model, mode, permission)

    if not sys.stdin.isatty():
        # 파이프 입력: 한 줄씩 처리하는 단순 모드 (테스트·스크립트용)
        for line in sys.stdin:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("/"):
                _handle_slash_print(ctx, session_id, line)
                continue
            outcome = await run_request(ctx, line, session_id=session_id, mode=mode, permission=permission,
                                        on_human=render.print_event)
            _print_outcome(outcome)
        return int(ExitCode.COMPLETED)

    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style

    bindings = KeyBindings()

    @bindings.add("escape")
    def _(event: Any) -> None:
        """입력 중 Esc: 현재 입력 취소/중단 안내."""
        event.app.current_buffer.reset()

    class SlashCompleter(Completer):
        def get_completions(self, document: Any, complete_event: Any):
            text = document.text_before_cursor
            if text.startswith("/"):
                for cmd, (name, description) in COMMANDS_HELP.items():
                    if cmd.startswith(text):
                        yield Completion(
                            cmd,
                            start_position=-len(text),
                            display=f"{cmd:<13} {name}",
                            display_meta=description,
                        )
            elif text.startswith("@"):
                from prompt_toolkit.completion import PathCompleter
                pc = PathCompleter(only_directories=False, expanduser=True)
                for c in pc.get_completions(document, complete_event):
                    yield c

    session_prompt: Any = PromptSession(
        "› ",
        completer=SlashCompleter(),
        key_bindings=bindings,
        style=Style.from_dict(SLASH_MENU_STYLE),
        reserve_space_for_menu=SLASH_MENU_HEIGHT,
        multiline=False,
    )

    ctrl_c_armed = False
    while True:
        try:
            text = await session_prompt.prompt_async()
        except KeyboardInterrupt:
            if ctrl_c_armed:
                render.console.print("\n[dim]Talo를 종료합니다.[/dim]")
                return int(ExitCode.COMPLETED)
            ctrl_c_armed = True
            render.console.print("\n[dim]종료하려면 Ctrl+C를 한 번 더 누르세요.[/dim]")
            continue
        except EOFError:
            render.console.print("\n[dim]종료합니다.[/dim]")
            return int(ExitCode.COMPLETED)
        ctrl_c_armed = False
        text = text.strip()
        if not text:
            continue
        if text.startswith("/"):
            changed = _handle_slash_interactive(ctx, session_id, text)
            if changed == "quit":
                return int(ExitCode.COMPLETED)
            if changed and isinstance(changed, dict):
                if "mode" in changed:
                    mode = changed["mode"]
                if "permission" in changed:
                    permission = changed["permission"]
                conn = ctx.resolver.active()
                model = None
                if conn and conn.connection:
                    model = ctx.config.selected_model_id(conn.connection) or conn.connection.model_id
                render.header(ctx.repo_info.summary(), model, mode, permission)
            continue

        # 자연어 요청 → 같은 기능 접근 가능
        lowered = text.lower()
        if "모델 바꿔" in text or lowered == "model":
            _handle_slash_interactive(ctx, session_id, "/model")
            continue
        if "변경 내용" in text or lowered == "diff":
            _handle_slash_interactive(ctx, session_id, "/diff")
            continue

        runtime_ref: dict[str, Any] = {}
        try:
            outcome = await run_request(ctx, text, session_id=session_id, mode=mode, permission=permission,
                                        on_human=render.print_event,
                                        on_approval=lambda tool, scope: _approval_prompt(session_prompt, tool, scope))
            _print_outcome(outcome)
        except KeyboardInterrupt:
            render.console.print("\n[yellow]중단 요청됨. 진행 중인 프로세스 종료 여부를 확인합니다.[/yellow]")
        except asyncio.CancelledError:
            render.console.print("\n[yellow]중단됨.[/yellow]")
            raise
    return int(ExitCode.COMPLETED)


async def _approval_prompt(session_prompt: Any, tool: str, scope: dict[str, Any]) -> bool:
    from talo.cli import render

    render.console.print(f"[yellow]승인 요청: {tool}[/yellow]")
    render.console.print(f"  실행 내용: {json.dumps(scope, ensure_ascii=False)[:200]}")
    render.menu_table("승인 선택", [
        ("1", "이번만 허용", "이 도구 호출 한 번만 실행합니다"),
        ("2", "거절", "도구를 실행하지 않고 대화를 계속합니다"),
    ])
    try:
        answer = await session_prompt.prompt_async("선택 (1/2): ")
    except (EOFError, KeyboardInterrupt):
        return False
    answer = answer.strip()
    return answer in {"1", "y", "yes", "허용"}


def _print_outcome(outcome: Any) -> None:
    from talo.cli import render

    if outcome.exit_code == ExitCode.COMPLETED:
        # 본문은 message.delta 이벤트로 이미 스트리밍됐으므로 중복 출력하지 않는다.
        render.console.print("[green]완료[/green]")
    elif outcome.exit_code == ExitCode.APPROVAL_NEEDED:
        render.console.print("[yellow]승인 필요 상태로 종료했습니다.[/yellow]")
    else:
        render.console.print(f"[red]{outcome.summary[:200]}[/red]")


def _handle_slash_print(ctx: Any, session_id: str, text: str) -> None:
    from talo.cli import render
    result = _handle_slash_interactive(ctx, session_id, text)
    if result == "quit":
        return
    if isinstance(result, dict) and "output" in result:
        render.console.print(result["output"])


def _handle_slash_interactive(ctx: Any, session_id: str, text: str) -> Any:
    from talo.application.service import export_session, list_sessions, memory_store, start_session
    from talo.cli import render

    parts = text.split(maxsplit=1)
    cmd = parts[0]
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        render.menu_table(
            "Talo 명령 메뉴",
            [(command, name, description) for command, (name, description) in COMMANDS_HELP.items()],
        )
        render.console.print("[dim]명령을 입력하거나 자연어로 바로 요청하세요.[/dim]")
        return None
    if cmd == "/quit" or cmd == "/exit":
        return "quit"
    if cmd == "/plan":
        render.console.print("[green]계획 모드로 전환했습니다. 변경·실행은 수행하지 않습니다.[/green]")
        return {"mode": "plan"}
    if cmd == "/dev":
        render.console.print("[green]개발 모드로 전환했습니다.[/green]")
        return {"mode": "dev"}
    if cmd == "/permissions":
        render.console.print(f"작업 방식: {ctx.config.default_mode} · 권한: {ctx.config.default_permission}")
        render.console.print("권한 변경은 /plan, /dev 또는 `talo run --permission`을 사용하세요.")
        return None
    if cmd == "/model":
        conns = list(ctx.config.connections.values())
        if not conns:
            render.console.print("[yellow]연결된 AI가 없습니다. `talo setup`으로 먼저 연결하세요.[/yellow]")
            return None
        if not arg:
            from talo.cli.connection_wizard import run_model_picker
            picked = run_model_picker(ctx.config)
            if picked:
                return {"model": picked}
            return None
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(conns):
                target = f"{conns[idx].connection_id}:{conns[idx].model_id}"
                ctx.config.set_default_model(target)
                render.console.print(f"[green]모델 전환: {target}[/green]")
                return {"model": target}
        elif ":" in arg or any(c.connection_id == arg for c in conns):
            ctx.config.set_default_model(arg)
            render.console.print(f"[green]모델 전환: {arg}[/green]")
            return {"model": arg}
        render.console.print(f"[yellow]알 수 없는 모델 번호/ID: {arg}[/yellow]")
        return None
    if cmd == "/status":
        runs = ctx.repository.list_runs(session_id)
        if not runs:
            render.console.print("이 세션의 실행 기록이 없습니다.")
            return None
        last = runs[-1]
        render.console.print(f"마지막 Run: {last['id']} · 상태: {last['state']} · 방식: {last['mode']}")
        verifs = ctx.repository.conn.execute(
            "SELECT * FROM verifications WHERE run_id=? ORDER BY created_at", (last["id"],)
        ).fetchall()
        for v in verifs:
            render.console.print(f"  검증: [{v['result']}] {v['evidence_ref'] or ''}")
        return None
    if cmd == "/diff":
        render.console.print(ctx.workspace.diff_stat() or "(변경 없음)")
        return None
    if cmd == "/memory":
        store = memory_store(ctx)
        if arg.startswith("add "):
            mid = store.propose("fact", arg[4:]).id
            render.console.print(f"[green]기억 제안 저장: {mid}[/green]")
        elif arg.startswith("confirm "):
            store.confirm(arg[8:])
            render.console.print("[green]확정 처리됨[/green]")
        elif arg.startswith("del "):
            store.delete(arg[4:])
            render.console.print("[green]삭제됨 (파생 캐시에서도 제외)[/green]")
        else:
            for m in store.list():
                render.console.print(f"  [{m.status}] {m.kind}: {m.content[:80]} ({m.id[:8]})")
        return None
    if cmd == "/sessions":
        render.sessions_table(list_sessions(ctx))
        return None
    if cmd == "/skills":
        skills = ctx.skill_loader.list_skills()
        for s in skills:
            render.console.print(f"  {s['name']} [{s['origin']}]: {s['description'][:80]}")
        render.console.print("명시적 실행은 /skills run <이름> 또는 자연어로 요청하세요.")
        return None
    if cmd == "/mcp":
        render.console.print("등록된 MCP 연결이 없습니다. (초기 범위: 명시적으로 등록한 MCP 도구 연결)")
        return None
    if cmd == "/export":
        fmt = arg.strip() or "markdown"
        if fmt not in {"markdown", "json"}:
            render.console.print("[red]형식은 markdown 또는 json이어야 합니다.[/red]")
            return None
        doc = export_session(ctx, session_id, fmt)
        path = ctx.cwd / f"talo-export-{session_id[:8]}.{'json' if fmt == 'json' else 'md'}"
        path.write_text(doc, encoding="utf-8")
        render.console.print(f"[green]내보냄: {path}[/green]")
        return None
    if cmd == "/connect":
        from talo.cli.connection_wizard import run_connect_interactive
        run_connect_interactive(ctx.config, ctx.resolver.credentials_store)
        return None
    render.console.print(f"[yellow]알 수 없는 명령: {cmd}[/yellow] (/help)")
    return None
