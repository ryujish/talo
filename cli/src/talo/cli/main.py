"""Talo CLI 진입점.

talo            대화형 화면 시작
talo resume [id] 세션 선택·재개
talo run "요청"  단발 실행 (--plan/--json)
talo connect     AI 연결 관리
talo doctor      진단
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path
from typing import Any

from talo import paths
from talo.config import Config, ConnectionConfig
from talo.schemas import ExitCode, RunConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="talo", description="Talo — 여러 AI와 작업을 이어가는 개발자 CLI 에이전트")
    parser.add_argument("--version", action="version", version=f"talo {__import__('talo').__version__}")
    sub = parser.add_subparsers(dest="command")

    p_remote = sub.add_parser("remote", help="선택형 서버 동기화·원격 작업")
    p_remote.add_argument("remote_action", choices=["pair", "start", "status", "disconnect", "install", "uninstall"])
    p_remote.add_argument("--server", default="https://think-along.ai.kr")
    p_remote.add_argument("--name", default=None)
    p_remote.add_argument("--sync-records", action="store_true", help="대화·결정·작업 기록을 서버에 저장")
    p_remote.add_argument("--allow-run", action="store_true", help="이 프로젝트의 원격 실행 허용")
    p_remote.add_argument("--share-diff", action="store_true", help="검토할 diff의 서버 전달·저장 허용")

    p_run = sub.add_parser("run", help="한 작업 수행 후 종료")
    p_run.add_argument("request", help="요청 내용")
    p_run.add_argument("--plan", action="store_true", help="계획 모드로 수행")
    p_run.add_argument("--json", action="store_true", help="구조화된 JSONL 이벤트 출력")
    p_run.add_argument("--model", help="사용할 모델 (connection_id:model_id 또는 model_id)")
    p_run.add_argument("--permission", choices=["read_only", "project_edit", "delegated"], default=None)
    p_run.add_argument("--session", help="이어갈 세션 ID")
    p_run.add_argument("--max-iterations", type=int, default=None)

    p_resume = sub.add_parser("resume", help="세션 선택·재개")
    p_resume.add_argument("session_id", nargs="?", help="재개할 세션 ID")

    p_connect = sub.add_parser("connect", help="AI 연결 관리")
    p_connect.add_argument("action", nargs="?", choices=["add", "remove", "use", "validate", "list"], default=None)
    p_connect.add_argument("target", nargs="?", help="연결 ID 또는 연결 ID:모델")
    p_connect.add_argument("--provider", default="openrouter")
    p_connect.add_argument("--base-url", default=None)
    p_connect.add_argument("--model-id", default=None)
    p_connect.add_argument("--api-key-env", default=None)
    p_connect.add_argument("--keychain", action="store_true", help="API 키를 macOS Keychain에 저장")

    p_changes = sub.add_parser("changes", help="변경 목록·검토·적용·복구")
    p_changes.add_argument("action", choices=["list", "diff", "review", "apply", "cancel", "recover"], nargs="?", default="list")
    p_changes.add_argument("change_id", nargs="?")
    p_changes.add_argument("--hash", dest="patch_hash")
    p_changes.add_argument("--json", action="store_true")
    p_undo = sub.add_parser("undo", help="마지막 Talo 변경만 되돌리기")
    p_undo.add_argument("change_id", nargs="?")
    p_undo.add_argument("--json", action="store_true")
    p_tasks = sub.add_parser("tasks", help="열린 작업·완료 확인")
    p_tasks.add_argument("action", choices=["list", "done"], nargs="?", default="list")
    p_tasks.add_argument("task_id", nargs="?")
    p_tasks.add_argument("--evidence", default="")
    sub.add_parser("serve", help="Headless 코어 JSONL stdio 서비스")
    sub.add_parser("demo", help="AI 연결 없는 변경 검토·undo 체험")
    sub.add_parser("setup", help="AI 연결 및 기본 모델 대화형 설정")

    p_model = sub.add_parser("model", help="기본 모델 선택 및 변경")
    p_model.add_argument("target", nargs="?", help="변경할 연결ID:모델")

    p_cron = sub.add_parser("cron", help="예약 작업 관리 및 실행")
    p_cron_sub = p_cron.add_subparsers(dest="cron_action")

    p_cron_add = p_cron_sub.add_parser("add", help="예약 작업 추가")
    p_cron_add.add_argument("--name", required=True, help="작업 이름")
    p_cron_add.add_argument("--at", required=True, help="실행 시각 HH:MM")
    p_cron_add.add_argument("--weekdays", default=None, help="요일 (콤마 구분: mon,tue,...)")
    p_cron_add.add_argument("--prompt", required=True, help="실행할 프롬프트")

    p_cron_sub.add_parser("list", help="예약 작업 목록")

    p_cron_disable = p_cron_sub.add_parser("disable", help="예약 작업 비활성화")
    p_cron_disable.add_argument("job_id", help="작업 ID")

    p_cron_sub.add_parser("run-due", help="due 예약 작업을 read_only로 실행")

    p_cron_history = p_cron_sub.add_parser("history", help="실행 이력")
    p_cron_history.add_argument("job_id", nargs="?", help="작업 ID (생략 시 전체)")

    p_cron_install = p_cron_sub.add_parser("install", help="macOS launchd LaunchAgent 등록")
    p_cron_install.add_argument("--dry-run", action="store_true", help="파일을 생성하지 않고 내용만 출력")
    p_cron_install.add_argument("--force", action="store_true", help="기존 plist 파일이 있어도 덮어쓰기")
    p_cron_install.add_argument("--dest-dir", default=None, help="plist 생성 대상 디렉터리")
    p_cron_install.add_argument("--bin", dest="talo_bin", default=None, help="talo 실행 파일 경로")

    p_cron_uninstall = p_cron_sub.add_parser("uninstall", help="macOS launchd LaunchAgent 제거")
    p_cron_uninstall.add_argument("--dest-dir", default=None, help="plist 대상 디렉터리")

    p_cron_status = p_cron_sub.add_parser("status", help="macOS launchd LaunchAgent 등록 상태 확인")
    p_cron_status.add_argument("--dest-dir", default=None, help="plist 대상 디렉터리")

    p_inbox = sub.add_parser("inbox", help="승인 요청 Inbox 관리")
    p_inbox_sub = p_inbox.add_subparsers(dest="inbox_action")
    p_inbox_list = p_inbox_sub.add_parser("list", help="승인 요청 목록 (정제 표시)")
    p_inbox_list.add_argument("--status", default=None, help="pending|approved|denied (생략 시 전체)")
    p_inbox_approve = p_inbox_sub.add_parser("approve", help="요청 승인 (자동 재생 없음)")
    p_inbox_approve.add_argument("request_id", help="요청 ID")
    p_inbox_deny = p_inbox_sub.add_parser("deny", help="요청 거절 (자동 재생 없음)")
    p_inbox_deny.add_argument("request_id", help="요청 ID")

    p_daily = sub.add_parser("daily", help="오늘 일일 일지 생성 (전날 미완료 이월)")
    p_daily.add_argument("--date", default=None, help="YYYY-MM-DD (기본: 오늘)")

    p_mcp = sub.add_parser("mcp", help="MCP HTTP/stdio 연결 확인")
    p_mcp.add_argument("action", choices=["think-along", "http", "stdio"])
    p_mcp.add_argument("target", nargs="?", help="HTTP URL 또는 stdio 실행 명령")
    p_mcp.add_argument("args", nargs="*", help="stdio 명령 인자")
    p_mcp.add_argument("--token-env", default=None, help="Bearer 토큰 환경변수 이름")

    p_orca = sub.add_parser("orchestrate", help="Orca 작업을 기존 Talo 터미널에 직접 주입")
    p_orca.add_argument("task_id", help="Orca task ID")
    p_orca.add_argument("terminal", help="대상 Talo terminal handle")
    p_orca.add_argument("--run", default=None, help="Orca run ID")
    p_orca.add_argument("--from-terminal", default=None, help="coordinator terminal handle")

    sub.add_parser("doctor", help="인증·모델 연결·도구·설정 진단")
    return parser


def load_dotenv_files() -> None:
    """프로젝트 및 상위 디렉터리의 .env, .env.local 자동 로드."""
    import os
    from pathlib import Path
    search_dirs = [Path.cwd(), Path.cwd().parent]
    for d in search_dirs:
        for fname in [".env", ".env.local"]:
            p = d / fname
            if p.is_file():
                try:
                    for line in p.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip("\"'"))
                except Exception:
                    pass


def auto_connect_from_env(config: Config) -> bool:
    """환경변수에서 검증된 API 키를 감지해 첫 연결을 자동 등록 (S04)."""
    import os
    from talo.config import ConnectionConfig

    # 이미 연결이 등록되어 있으면 건너뜀
    if config.connections:
        return False

    # 1. OpenAI
    if os.environ.get("OPENAI_API_KEY"):
        conn = ConnectionConfig(
            connection_id="openai_gpt-4.1-mini",
            provider_id="openai",
            base_url="https://api.openai.com/v1",
            credential_ref="env:OPENAI_API_KEY",
            model_id="gpt-4.1-mini",
            validated_at="auto_detected",
        )
        config.set_connection(conn)
        config.set_default_model(f"{conn.connection_id}:{conn.model_id}")
        return True

    # 2. DeepCode / DeepSeek
    if os.environ.get("BASE_URL") and os.environ.get("API_KEY"):
        conn = ConnectionConfig(
            connection_id="deepcode_deepseek-v4-pro",
            provider_id="deepcode",
            base_url=os.environ["BASE_URL"],
            credential_ref="env:API_KEY",
            model_id=os.environ.get("MODEL", "deepseek-v4-pro"),
            validated_at="auto_detected",
        )
        config.set_connection(conn)
        config.set_default_model(f"{conn.connection_id}:{conn.model_id}")
        return True

    if os.environ.get("DEEPSEEK_API_KEY"):
        conn = ConnectionConfig(
            connection_id="deepseek_chat",
            provider_id="deepseek",
            base_url="https://api.deepseek.com",
            credential_ref="env:DEEPSEEK_API_KEY",
            model_id="deepseek-chat",
            validated_at="auto_detected",
        )
        config.set_connection(conn)
        config.set_default_model(f"{conn.connection_id}:{conn.model_id}")
        return True

    # 3. Google Gemini
    if os.environ.get("GEMINI_API_KEY"):
        conn = ConnectionConfig(
            connection_id="gemini_flash",
            provider_id="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            credential_ref="env:GEMINI_API_KEY",
            model_id="gemini-2.5-flash",
            validated_at="auto_detected",
        )
        config.set_connection(conn)
        config.set_default_model(f"{conn.connection_id}:{conn.model_id}")
        return True

    return False


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in {None, "run", "resume", "connect", "setup", "model", "doctor"}:
        load_dotenv_files()
        config = Config.load()
        auto_connect_from_env(config)

    if args.command in {"changes", "undo", "tasks"}:
        from talo.application.service import create_app_context
        from talo.cli.changes import show_changes
        ctx = create_app_context()
        try:
            if args.command == "tasks":
                from talo.continuity import tasks, finish_task
                from talo.cli.render import console
                if args.action == "done":
                    finish_task(ctx.repository, ctx.workspace_id, args.task_id, args.evidence)
                for task in tasks(ctx.repository, ctx.workspace_id):
                    console.print(f"{task['id']} [{task['status']}] {task['title']}", markup=False)
                return 0
            return show_changes(ctx, "undo" if args.command == "undo" else args.action,
                                args.change_id, patch_hash=getattr(args, "patch_hash", None), json_out=args.json)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        finally:
            ctx.close()
    if args.command == "remote":
        load_dotenv_files()
        from talo.remote import command
        try:
            return command(args)
        except (ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            return 130

    if args.command == "serve":
        from talo.service import serve
        return serve()
    if args.command == "demo":
        return _cmd_demo()
    if args.command == "run":
        return asyncio.run(_cmd_run(args))
    if args.command == "resume":
        return asyncio.run(_cmd_resume(args))
    if args.command == "connect":
        return _cmd_connect(args)
    if args.command == "setup":
        return _cmd_setup()
    if args.command == "model":
        return _cmd_model(args)
    if args.command == "cron":
        return _cmd_cron(args)
    if args.command == "inbox":
        return _cmd_inbox(args)
    if args.command == "daily":
        return _cmd_daily(args)
    if args.command == "mcp":
        return asyncio.run(_cmd_mcp(args))
    if args.command == "orchestrate":
        return asyncio.run(_cmd_orchestrate(args))
    if args.command == "doctor":
        return _cmd_doctor()
    return asyncio.run(_cmd_interactive())


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

async def _cmd_run(args: argparse.Namespace) -> int:
    from talo.application.service import create_app_context, list_sessions, run_request, start_session
    from talo.cli.render import console

    ctx = create_app_context()
    try:
        session_id = args.session
        if not session_id:
            session_id = start_session(ctx, title=args.request[:40])
        mode = "plan" if args.plan else ctx.config.default_mode
        permission = args.permission or ctx.config.default_permission
        connection_id, model_id = _split_model(args.model)

        run_config = RunConfig() if args.max_iterations is None else RunConfig(max_iterations=args.max_iterations)

        async def on_human(event_type: str, payload: dict[str, Any]) -> None:
            from talo.cli.render import print_event
            if args.json:
                # 진단은 stderr로 분리
                print(f"[{event_type}] {_brief(payload)}", file=sys.stderr)
            else:
                print_event(event_type, payload)

        outcome = await run_request(
            ctx, args.request, session_id=session_id, mode=mode, permission=permission,
            connection_id=connection_id, model_id=model_id, json_out=args.json,
            on_human=on_human, run_config=run_config,
        )
        if not args.json:
            if outcome.exit_code == ExitCode.COMPLETED:
                # 본문은 message.delta 이벤트로 이미 스트리밍됐으므로 중복 출력하지 않는다.
                console.print("[green]완료[/green]")
            elif outcome.state.value in ("awaiting_approval",):
                console.print(outcome.summary, markup=False, style="yellow")
            else:
                console.print(f"[red]{outcome.summary}[/red]")
        return int(outcome.exit_code)
    finally:
        ctx.close()


def _split_model(spec: str | None) -> tuple[str | None, str | None]:
    if not spec:
        return None, None
    if ":" in spec:
        conn_id, model = spec.split(":", 1)
        return conn_id, model
    return None, spec


def _brief(payload: dict[str, Any]) -> str:
    text = payload.get("text") or payload.get("message") or payload.get("summary") or ""
    return str(text)[:120]


# --------------------------------------------------------------------------
# resume
# --------------------------------------------------------------------------

async def _cmd_resume(args: argparse.Namespace) -> int:
    from talo.application.service import create_app_context, list_sessions
    from talo.cli import render

    ctx = create_app_context()
    try:
        sessions = list_sessions(ctx)
        if not sessions:
            render.console.print("[yellow]저장된 세션이 없습니다. `talo`로 새 작업을 시작하세요.[/yellow]")
            return int(ExitCode.INPUT_ERROR)
        if args.session_id:
            chosen = next((s for s in sessions if s["id"].startswith(args.session_id)), None)
            if chosen is None:
                render.console.print(f"[red]세션을 찾지 못함: {args.session_id}[/red]")
                return int(ExitCode.INPUT_ERROR)
        else:
            render.sessions_table(sessions)
            render.console.print("`talo resume <세션ID>`로 재개하거나 `talo`로 새 세션을 시작하세요.")
            return int(ExitCode.COMPLETED)
        session_id = chosen["id"]
        render.console.print(f"[green]세션 재개: {session_id} — {chosen['title'] or '(제목 없음)'}[/green]")
        _show_incomplete(ctx, session_id)
        from talo.cli.changes import show_resume
        show_resume(ctx, session_id)
        from talo.cli.interactive import run_interactive
        return await run_interactive(ctx, session_id=session_id)
    finally:
        ctx.close()


def _show_incomplete(ctx: Any, session_id: str) -> None:
    """마지막 handoff의 next_actions를 미완료 항목으로 정제해 표시한다."""
    import json as _json

    from talo.cli import render
    from talo.sanitize import redact_text

    ho = ctx.repository.latest_handoff(session_id)
    if ho is None:
        return
    try:
        doc = _json.loads(ho["document_json"] or "{}")
    except ValueError:
        doc = {}
    actions = (doc.get("next_actions") or [])
    if not actions:
        render.console.print("[dim]미완료 작업 없음 (이전 handoff 기준)[/dim]")
        return
    render.console.print("[cyan]미완료 작업:[/cyan]")
    for a in actions[:8]:
        render.console.print(f"  - [ ] {redact_text(str(a), 120)}")


# --------------------------------------------------------------------------
# connect
# --------------------------------------------------------------------------

def _cmd_connect(args: argparse.Namespace) -> int:
    from talo.cli import render
    from talo.cli.connection_wizard import run_connect_interactive
    from talo.providers.resolver import CredentialStore

    config = Config.load()
    store = CredentialStore()

    # 인자 없이 실행 시 대화형 연결 관리 메뉴로 진입 (Talo_CLI_Connection_UI_Plan_v0.1 S13)
    if args.action is None and args.target is None and sys.stdin.isatty():
        return run_connect_interactive(config, store)

    action = args.action or "list"

    if action == "list":
        render.connections_table(list(config.connections.values()), config.default_model.split(":")[0] if config.default_model else None)
        return int(ExitCode.COMPLETED)


    if action == "add":
        return _connect_add(args, config, store)

    if action == "remove":
        if not args.target:
            render.console.print("[red]연결 ID가 필요합니다: talo connect remove <ID>[/red]")
            return int(ExitCode.INPUT_ERROR)
        config.remove_connection(args.target)
        render.console.print(f"[green]연결 제거: {args.target}[/green]")
        return int(ExitCode.COMPLETED)

    if action == "use":
        if not args.target:
            render.console.print("[red]사용할 연결이 필요합니다: talo connect use <ID>[:모델][/red]")
            return int(ExitCode.INPUT_ERROR)
        conn_id = args.target.split(":")[0]
        if conn_id not in config.connections:
            render.console.print(f"[red]연결을 찾지 못함: {conn_id}[/red]")
            return int(ExitCode.INPUT_ERROR)
        config.update(default_model=args.target)
        render.console.print(f"[green]기본 모델 설정: {args.target}[/green]")
        return int(ExitCode.COMPLETED)

    if action == "validate":
        from talo.providers.resolver import ConnectionResolver
        resolver = ConnectionResolver(config, store)
        target = args.target
        if target:
            conn = config.connection(target)
            if conn is None:
                render.console.print(f"[red]연결을 찾지 못함: {target}[/red]")
                return int(ExitCode.INPUT_ERROR)
            ok, message = asyncio.run(_validate_async(conn, resolver))
            render.console.print(f"[{'green' if ok else 'red'}]{message}[/{'green' if ok else 'red'}]")
            return int(ExitCode.COMPLETED if ok else ExitCode.EXTERNAL_PAUSED)
        all_ok = True
        for conn in config.connections.values():
            ok, message = asyncio.run(_validate_async(conn, resolver))
            mark = "ok" if ok else "fail"
            render.console.print(f"[{mark}] {conn.connection_id}: {message}[/{mark}]")
            if not ok:
                all_ok = False
        return int(ExitCode.COMPLETED if all_ok else ExitCode.EXTERNAL_PAUSED)

    return int(ExitCode.INPUT_ERROR)


def _cmd_setup() -> int:
    """talo setup 명령: 대화형 설정 및 AI 연결 마법사 (S01/S03)."""
    from talo.cli.connection_wizard import run_first_time_guide
    from talo.providers.resolver import CredentialStore

    config = Config.load()
    store = CredentialStore()
    ok = run_first_time_guide(config, store)
    return int(ExitCode.COMPLETED if ok else ExitCode.INPUT_ERROR)


def _cmd_model(args: argparse.Namespace) -> int:
    """talo model 명령: 기본 모델 조회 및 전환 (S09/S12)."""
    from talo.cli import render
    from talo.cli.connection_wizard import run_model_picker

    config = Config.load()
    if args.target:
        config.set_default_model(args.target)
        render.console.print(f"[green]기본 모델 설정: {args.target}[/green]")
        return int(ExitCode.COMPLETED)
    picked = run_model_picker(config)
    return int(ExitCode.COMPLETED if picked else ExitCode.INPUT_ERROR)


async def _validate_async(conn: ConnectionConfig, resolver: Any) -> tuple[bool, str]:
    if conn.provider_id == "mock":
        return True, "mock 연결은 항상 유효함"
    return await resolver.validate(conn)


async def _cmd_mcp(args: argparse.Namespace) -> int:
    from talo.cli import render
    from talo.integrations.mcp import McpManager

    manager = McpManager()
    try:
        if args.action == "think-along":
            connection = await manager.connect_http(
                "think_along", "https://mcp.flowpulse.ai.kr/mcp", "THINK_ALONG_OAUTH_KEY",
            )
        elif args.action == "http":
            if not args.target:
                render.console.print("[red]HTTP MCP URL이 필요합니다.[/red]")
                return int(ExitCode.INPUT_ERROR)
            connection = await manager.connect_http("http", args.target, args.token_env)
        else:
            if not args.target:
                render.console.print("[red]stdio MCP 실행 명령이 필요합니다.[/red]")
                return int(ExitCode.INPUT_ERROR)
            connection = await manager.connect_stdio("stdio", args.target, args.args)
        color = "green" if connection.status == "connected" else "red"
        render.console.print(f"[{color}]{connection.connection_id}: {connection.status}[/{color}]")
        if connection.error:
            render.console.print(f"[red]{connection.error}[/red]")
        for tool in connection.tools:
            render.console.print(f"  {tool.get('name', '-')}: {tool.get('description', '')}")
        return int(ExitCode.COMPLETED if connection.status == "connected" else ExitCode.EXTERNAL_PAUSED)
    finally:
        await manager.aclose()


async def _cmd_orchestrate(args: argparse.Namespace) -> int:
    from talo.cli import render
    from talo.integrations.orca import dispatch_to_talo

    try:
        dispatch = await dispatch_to_talo(
            args.task_id, args.terminal, run_id=args.run, coordinator=args.from_terminal,
        )
    except Exception as exc:  # noqa: BLE001
        render.console.print(f"[red]Orca 주입 실패: {exc}[/red]")
        return int(ExitCode.EXTERNAL_PAUSED)
    render.console.print(f"[green]Orca 작업 주입 완료: {dispatch['id']}[/green]")
    return int(ExitCode.COMPLETED)


CLI_BRIDGE_PRESETS: dict[str, dict[str, str]] = {
    "codex_cli": {"command": "codex", "label": "Codex CLI (OAuth)", "default_model": "gpt-5.6-sol"},
    "codex": {"command": "codex", "label": "Codex CLI (OAuth)", "default_model": "gpt-5.6-sol"},
    "opencode": {"command": "opencode", "label": "OpenCode Zen", "default_model": "opencode/big-pickle"},
    "agy": {"command": "agy", "label": "Google AGY", "default_model": "gemini-3.8-flash-high"},
}


def _connect_add(args: argparse.Namespace, config: Config, store: Any) -> int:
    from talo.cli import render

    provider = args.provider
    if provider in CLI_BRIDGE_PRESETS:
        return _connect_add_cli_bridge(args, config, provider)

    base_url = args.base_url or ("https://openrouter.ai/api/v1" if provider == "openrouter" else None)
    if not base_url:
        render.console.print("[red]--base-url이 필요합니다.[/red]")
        return int(ExitCode.INPUT_ERROR)
    model_id = args.model_id
    if not model_id:
        model_id = input("모델 ID: ").strip()
        if not model_id:
            render.console.print("[red]모델 ID가 필요합니다.[/red]")
            return int(ExitCode.INPUT_ERROR)

    if args.keychain:
        account = input("Keychain 계정 이름 [talo]: ").strip() or "talo"
        api_key = getpass.getpass("API 키 (마스킹 입력): ").strip()
        ok, msg = store.store(f"keychain:{account}", api_key)
        if not ok:
            render.console.print(f"[red]{msg}[/red]")
            return int(ExitCode.INPUT_ERROR)
        credential_ref = f"keychain:{account}"
        render.console.print(f"[green]{msg}[/green]")
    else:
        env_name = args.api_key_env or input("API 키 환경변수 이름 [TALO_API_KEY]: ").strip() or "TALO_API_KEY"
        credential_ref = f"env:{env_name}"

    conn = ConnectionConfig(
        connection_id=f"{provider}_{model_id.split('/')[-1][:16]}",
        provider_id=provider,
        base_url=base_url,
        credential_ref=credential_ref,
        model_id=model_id,
    )
    config.set_connection(conn)
    render.console.print(f"[green]연결 추가: {conn.connection_id} (credential_ref={credential_ref})[/green]")
    render.console.print("연결 검증은 `talo connect validate`로 수행하세요.")
    return int(ExitCode.COMPLETED)


def _connect_add_cli_bridge(args: argparse.Namespace, config: Config, provider: str) -> int:
    """CLI 서브프로세스 브릿지 연결 등록 (API 키 불필요, 기존 OAuth 세션 사용)."""
    from talo.cli import render

    preset = CLI_BRIDGE_PRESETS[provider]
    default_model = preset["default_model"]
    model_id = (args.model_id or input(f"모델 ID [{default_model}]: ").strip() or default_model)

    conn = ConnectionConfig(
        connection_id=f"{provider}_{model_id.split('/')[-1][:16]}",
        provider_id=provider,
        protocol="cli_subprocess",
        base_url="",
        credential_ref="",
        model_id=model_id,
        command=preset["command"],
        cwd=str(Path.cwd()),
    )
    config.set_connection(conn)
    config.set_default_model(f"{conn.connection_id}:{model_id}")
    render.console.print(f"[green]연결 추가: {conn.connection_id} — {preset['label']}[/green]")
    render.console.print("이 연결은 API 키 대신 로컬 CLI의 기존 로그인 세션(OAuth)을 사용합니다.")
    render.console.print("검증은 `talo connect validate`로 수행하세요.")
    return int(ExitCode.COMPLETED)


# --------------------------------------------------------------------------
# cron
# --------------------------------------------------------------------------

def _cmd_cron(args: argparse.Namespace) -> int:
    from talo import cron

    action = args.cron_action
    if action == "add":
        return cron.cmd_cron_add(args)
    if action == "list":
        return cron.cmd_cron_list(args)
    if action == "disable":
        return cron.cmd_cron_disable(args)
    if action == "run-due":
        return cron.cmd_cron_run_due(args)
    if action == "history":
        return cron.cmd_cron_history(args)
    if action == "install":
        return cron.cmd_cron_install(args)
    if action == "uninstall":
        return cron.cmd_cron_uninstall(args)
    if action == "status":
        return cron.cmd_cron_status(args)
    from talo.cli import render
    render.console.print("[yellow]cron 하위 명령: add | list | disable | run-due | history | install | uninstall | status[/yellow]")
    return int(ExitCode.INPUT_ERROR)


# --------------------------------------------------------------------------
# inbox
# --------------------------------------------------------------------------

def _cmd_inbox(args: argparse.Namespace) -> int:
    from talo import inbox

    action = args.inbox_action
    if action == "list":
        return inbox.cmd_inbox_list(args)
    if action == "approve":
        return inbox.cmd_inbox_approve(args)
    if action == "deny":
        return inbox.cmd_inbox_deny(args)
    from talo.cli import render
    render.console.print("[yellow]inbox 하위 명령: list | approve | deny[/yellow]")
    return int(ExitCode.INPUT_ERROR)


# --------------------------------------------------------------------------
# daily
# --------------------------------------------------------------------------

def _cmd_daily(args: argparse.Namespace) -> int:
    from talo.daily import cmd_daily
    return cmd_daily(args)


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------

def _cmd_doctor() -> int:
    from talo.cli import render
    from talo.storage.db import Database

    checks: list[dict[str, Any]] = []
    import platform
    import shutil
    import sqlite3

    checks.append({"name": "python", "status": "ok", "detail": f"{platform.python_version()} ({platform.machine()})"})
    checks.append({"name": "git", "status": "ok" if shutil.which("git") else "fail",
                   "detail": shutil.which("git") or "설치 안 됨"})

    try:
        tmp = paths.talo_home() / "_doctor.sqlite"
        db = Database(tmp)
        db.migrate()
        checks.append({"name": "sqlite", "status": "ok",
                       "detail": f"WAL+FTS5={'있음' if db.fts5_available else '없음'}"})
        db.close()
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "sqlite", "status": "fail", "detail": str(exc)})

    config = Config.load()
    conns = list(config.connections.values())
    if not conns:
        checks.append({"name": "연결", "status": "warn", "detail": "연결 없음 — `talo setup`"})
    else:
        checks.append({"name": "연결", "status": "ok",
                       "detail": ", ".join(f"{c.connection_id}({c.model_id or '-'})" for c in conns)})

    from talo.application.service import create_app_context
    try:
        ctx = create_app_context()
        info = ctx.repo_info
        checks.append({"name": "프로젝트", "status": "ok",
                       "detail": f"{info.root} · branch={info.branch or '없음'} · git={'있음' if info.is_git else '없음'}"})
        checks.append({"name": "도구", "status": "ok", "detail": f"{len(ctx.tool_registry.list())}개 등록"})
        checks.append({"name": "스킬", "status": "ok", "detail": f"{len(ctx.skill_loader.list_skills())}개"})
        ctx.close()
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "프로젝트", "status": "fail", "detail": str(exc)})

    ok = all(c["status"] != "fail" for c in checks)
    render.doctor_report(checks)
    if not conns:
        render.console.print("[yellow]첫 실행 안내: `talo setup`으로 AI 연결을 설정하면 요청을 실행할 수 있습니다.[/yellow]")
    return int(ExitCode.COMPLETED if ok else ExitCode.INPUT_ERROR)


# --------------------------------------------------------------------------
# interactive
# --------------------------------------------------------------------------

async def _cmd_interactive() -> int:
    from talo.application.service import create_app_context, start_session
    from talo.cli.connection_wizard import run_first_time_guide
    from talo.cli.interactive import run_interactive

    ctx = create_app_context()
    try:
        active = ctx.resolver.active()
        if (active is None or not ctx.config.connections) and sys.stdin.isatty():
            run_first_time_guide(ctx.config, ctx.resolver.credentials_store)
        sessions = ctx.repository.list_sessions(ctx.workspace_id)
        session_id = sessions[0]["id"] if sessions else start_session(ctx)
        from talo.cli.changes import show_resume
        show_resume(ctx, session_id)
        return await run_interactive(ctx, session_id=session_id)
    finally:
        ctx.close()


def _cmd_demo():
    import tempfile
    from talo.application.service import create_app_context
    from talo.changes.manager import for_context
    from talo.cli.changes import print_diff
    from talo.cli.render import console
    with tempfile.TemporaryDirectory(prefix="talo-demo-") as directory:
        root = Path(directory)
        (root / "hello.txt").write_text("안녕하세요, Talo\n")
        # 임시 설정·상태를 사용하므로 실제 프로젝트와 자격증명을 변경하지 않는다.
        import os
        old = os.environ.get("TALO_HOME")
        os.environ["TALO_HOME"] = str(root / "state")
        ctx = create_app_context(root)
        try:
            manager = for_context(ctx)
            c = manager.propose([{"path": "hello.txt", "content": "다음 날에도 이어서 작업합니다.\n"}])
            print_diff(manager.diff(c["id"]))
            console.print("체험: 임시 프로젝트에 변경을 적용하고 즉시 undo합니다.")
            manager.apply(c["id"], c["patch_hash"])
            manager.undo(c["id"])
            assert (root / "hello.txt").read_text() == "안녕하세요, Talo\n"
            console.print("체험 완료: 제안 → diff → 적용 → undo → 원문 복구 확인")
            return 0
        finally:
            ctx.close()
            if old is None:
                os.environ.pop("TALO_HOME", None)
            else:
                os.environ["TALO_HOME"] = old


if __name__ == "__main__":
    raise SystemExit(main())
