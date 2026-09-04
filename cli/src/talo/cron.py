"""cron: 예약 작업의 저장·검증·무인 실행 (Slice 1).

OS 스케줄러(launchd/systemd timer)가 매분 `talo cron run-due`를 호출하면,
Talo는 due job을 SQLite 원자 선점으로 처리하고 read_only 모델 실행만 수행한다.
임의 cron 표현식은 지원하지 않으며 매일/평일 HH:MM만 다룬다.
"""
from __future__ import annotations

import asyncio
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from talo import paths
from talo.application.service import AppContext, create_app_context, run_request, start_session
from talo.cli import render
from talo.schemas import ExitCode, RunConfig

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# 무인 실행 기본값: 낮은 반복·시간 예산 (과도한 모델 호출 방지)
DEFAULT_RUN_CONFIG = RunConfig(max_iterations=8, timeout_seconds=120.0)


def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    parts = hhmm.split(":")
    if len(parts) != 2:
        raise ValueError(f"잘못된 HH:MM 형식: {hhmm}")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"잘못된 HH:MM 형식: {hhmm}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"시각이 범위를 벗어남: {hhmm} (00:00~23:59)")
    return hour, minute


def _parse_weekdays(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    out: list[int] = []
    for token in raw.split(","):
        token = token.strip().lower()
        if token not in WEEKDAYS:
            raise ValueError(
                f"잘못된 요일: {token} (허용: {','.join(WEEKDAYS.keys())})")
        day = WEEKDAYS[token]
        if day not in out:
            out.append(day)
    return sorted(out)


def build_schedule_json(hhmm: str, weekdays: list[int] | None) -> str:
    return json.dumps({"hhmm": hhmm, "weekdays": weekdays}, ensure_ascii=False)


def _next_run_at(from_epoch: float, schedule: dict[str, Any]) -> float:
    """from_epoch 이후 이 schedule이 처음 발생하는 시각(분 단위)을 epoch로 반환."""
    hhmm = schedule.get("hhmm", schedule.get("time"))
    if not hhmm:
        raise ValueError("schedule에 hhmm이 없음")
    hour, minute = _parse_hhmm(hhmm)
    days = schedule.get("weekdays")
    allowed: set[int] | None = {int(d) for d in days} if days else None

    # from_epoch의 다음 분 경계부터 탐색 (최대 8일 = 1주 + 여유)
    base = datetime.fromtimestamp(from_epoch)
    for day_offset in range(9):
        dt = datetime(base.year, base.month, base.day, hour, minute) + timedelta(days=day_offset)
        if dt.timestamp() <= from_epoch:
            continue
        if allowed is None or dt.weekday() in allowed:
            return float(dt.timestamp())
    raise ValueError("해당 schedule의 발생 시각을 찾지 못함")


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

async def run_due_jobs(ctx: AppContext, *, now: float | None = None,
                       run_config: RunConfig | None = None) -> list[dict[str, Any]]:
    """due job을 원자 선점한 뒤 read_only로 실행하고 scheduled_runs에 기록한다."""
    cfg = run_config or DEFAULT_RUN_CONFIG
    current = now if now is not None else time.time()
    results: list[dict[str, Any]] = []

    for job in ctx.repository.due_jobs(ctx.project_id, now=current):
        try:
            schedule = json.loads(job["schedule_json"])
            nxt = _next_run_at(current, schedule)
        except (ValueError, json.JSONDecodeError) as exc:
            results.append({"job_id": job["id"], "name": job["name"], "state": "failed",
                            "error": f"schedule 오류: {exc}"})
            continue

        claimed = ctx.repository.claim_due_job(
            job["id"], ctx.project_id, float(job["next_run_at"]), nxt)
        if claimed is None:
            # 동시 실행에 선점을 빼앗김 — 같은 슬롯 재실행 금지
            results.append({"job_id": job["id"], "name": job["name"], "state": "skipped",
                            "error": "이미 이 슬롯에서 처리됨"})
            continue

        started = time.time()
        ctx.repository.mark_scheduled_run(claimed, "running", started_at=started)
        try:
            session_id = start_session(ctx, title=f"cron-{job['name']}")
            outcome = await asyncio.wait_for(
                run_request(
                    ctx, job["prompt"], session_id=session_id,
                    mode="plan", permission="read_only", run_config=cfg,
                ),
                timeout=cfg.timeout_seconds,
            )
            state = "succeeded" if outcome.exit_code == ExitCode.COMPLETED else "failed"
            error = None if state == "succeeded" else outcome.summary[:500]
            ctx.repository.mark_scheduled_run(
                claimed, state, session_id=outcome.session_id, run_id=outcome.run_id,
                error=error, started_at=started, finished_at=time.time(),
            )
            results.append({"job_id": job["id"], "name": job["name"], "state": state,
                            "run_id": outcome.run_id, "session_id": outcome.session_id})
        except Exception as exc:  # noqa: BLE001 - 무인 실행은 실패를 기록하고 계속
            ctx.repository.mark_scheduled_run(
                claimed, "failed", error=f"{type(exc).__name__}: {exc}",
                started_at=started, finished_at=time.time(),
            )
            results.append({"job_id": job["id"], "name": job["name"], "state": "failed",
                            "error": str(exc)})

    if results:
        try:
            from talo.daily import build_daily_report
            build_daily_report(ctx)
        except Exception as exc:  # noqa: BLE001 - 예약 실행 기록을 잃지 않고 일지 실패를 노출
            results.append({"job_id": "daily", "name": "daily-report", "state": "failed",
                            "error": f"{type(exc).__name__}: {exc}"})

    return results


# ---------------------------------------------------------------------------
# CLI 핸들러
# ---------------------------------------------------------------------------

def cmd_cron_add(args: Any) -> int:
    ctx = create_app_context()
    try:
        try:
            _parse_hhmm(args.at)
            weekdays = _parse_weekdays(args.weekdays)
        except ValueError as exc:
            render.console.print(f"[red]{exc}[/red]")
            return int(ExitCode.INPUT_ERROR)
        schedule_json = build_schedule_json(args.at, weekdays)
        first_run = _next_run_at(time.time(), json.loads(schedule_json))
        jid = ctx.repository.create_job(
            ctx.project_id, args.name, args.prompt, schedule_json, "local", next_run_at=first_run)
        render.console.print(
            f"[green]예약 작업 추가: {jid} — {args.name} @ {args.at}"
            + (f" ({args.weekdays})" if weekdays else "")
            + "[/green]")
        return int(ExitCode.COMPLETED)
    finally:
        ctx.close()


def cmd_cron_list(args: Any) -> int:
    ctx = create_app_context()
    try:
        jobs = ctx.repository.list_jobs(ctx.project_id)
        if not jobs:
            render.console.print("[yellow]예약 작업이 없습니다.[/yellow]")
            return int(ExitCode.COMPLETED)
        rows = [{
            "id": j["id"],
            "name": j["name"],
            "schedule": j["schedule_json"],
            "enabled": "활성" if j["enabled"] else "비활성",
            "next_run_at": _fmt(j["next_run_at"]),
        } for j in jobs]
        render.jobs_table(rows)
        return int(ExitCode.COMPLETED)
    finally:
        ctx.close()


def cmd_cron_disable(args: Any) -> int:
    ctx = create_app_context()
    try:
        ok = ctx.repository.disable_job(args.job_id, ctx.project_id)
        if ok:
            render.console.print(f"[green]예약 작업 비활성화: {args.job_id}[/green]")
            return int(ExitCode.COMPLETED)
        render.console.print(f"[red]예약 작업을 찾지 못함(프로젝트 범위): {args.job_id}[/red]")
        return int(ExitCode.INPUT_ERROR)
    finally:
        ctx.close()


def cmd_cron_history(args: Any) -> int:
    ctx = create_app_context()
    try:
        if args.job_id:
            job = ctx.repository.get_job(args.job_id)
            if job is None or job["project_id"] != ctx.project_id:
                render.console.print(f"[red]예약 작업을 찾지 못함(프로젝트 범위): {args.job_id}[/red]")
                return int(ExitCode.INPUT_ERROR)
            runs = ctx.repository.scheduled_run_history(args.job_id)
            rows = [{
                "scheduled_for": _fmt(r["scheduled_for"]),
                "state": r["state"],
                "run_id": r["run_id"] or "-",
                "error": (r["error"] or "-")[:60],
            } for r in runs]
            render.jobs_table(rows)
        else:
            jobs = ctx.repository.list_jobs(ctx.project_id)
            if not jobs:
                render.console.print("[yellow]예약 작업이 없습니다.[/yellow]")
                return int(ExitCode.COMPLETED)
            render.console.print("[cyan]최근 실행 이력 (작업별)[/cyan]")
            for job in jobs:
                runs = ctx.repository.scheduled_run_history(job["id"], limit=3)
                render.console.print(f"- {job['name']} ({job['id']})")
                for r in runs:
                    render.console.print(
                        f"    {_fmt(r['scheduled_for'])}  {r['state']}  run={r['run_id'] or '-'}")
        return int(ExitCode.COMPLETED)
    finally:
        ctx.close()


def cmd_cron_run_due(args: Any) -> int:
    ctx = create_app_context()
    try:
        results = asyncio.run(run_due_jobs(ctx))
        if not results:
            render.console.print("[dim]실행할 due 작업이 없습니다.[/dim]")
            return int(ExitCode.COMPLETED)
        for r in results:
            mark = "green" if r["state"] == "succeeded" else ("yellow" if r["state"] == "skipped" else "red")
            render.console.print(
                f"[{mark}]{r['name']}: {r['state']}[/{mark}]"
                + (f"  ({r['error']})" if r.get("error") else ""))
        failed = any(r["state"] == "failed" for r in results)
        return int(ExitCode.FAILED if failed else ExitCode.COMPLETED)
    finally:
        ctx.close()


def _fmt(epoch: float | None) -> str:
    if epoch is None:
        return "-"
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# macOS launchd LaunchAgent 관리
# ---------------------------------------------------------------------------

LAUNCHD_LABEL_PREFIX = "ai.talo.cron"


def get_default_launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def get_launch_agent_path(project_id: str, custom_dir: Path | None = None) -> Path:
    parent = custom_dir or get_default_launch_agents_dir()
    return parent / f"{LAUNCHD_LABEL_PREFIX}.{project_id}.plist"


def _resolve_talo_binary(custom_bin: str | None = None) -> str:
    if custom_bin:
        return str(Path(custom_bin).expanduser().resolve())
    found = shutil.which("talo")
    if found:
        return str(Path(found).resolve())
    venv_talo = Path(sys.prefix) / "bin" / "talo"
    if venv_talo.exists():
        return str(venv_talo.resolve())
    local_talo = Path.home() / ".local" / "bin" / "talo"
    if local_talo.exists():
        return str(local_talo.resolve())
    return "talo"


def generate_launchd_plist(
    project_id: str,
    project_dir: str | Path,
    *,
    talo_bin: str | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> str:
    """macOS launchd LaunchAgent XML plist 문자열을 생성한다.

    보안 및 안정성 경계:
    - StartInterval=60, RunAtLoad=True 보장
    - talo cron run-due 및 프로젝트 작업 디렉터리만 포함
    - 자격증명, API 키, 환경변수는 일절 포함하지 않음
    """
    resolved_bin = _resolve_talo_binary(talo_bin)
    norm_project_dir = str(Path(project_dir).expanduser().resolve())
    log_dir = paths.project_dir(project_id) if hasattr(paths, "project_dir") else paths.talo_home()
    norm_stdout = str(stdout_path or (log_dir / f"cron-{project_id}.log"))
    norm_stderr = str(stderr_path or (log_dir / f"cron-{project_id}.err"))

    plist_data: dict[str, Any] = {
        "Label": f"{LAUNCHD_LABEL_PREFIX}.{project_id}",
        "ProgramArguments": [resolved_bin, "cron", "run-due"],
        "WorkingDirectory": norm_project_dir,
        "StartInterval": 60,
        "RunAtLoad": True,
        "StandardOutPath": norm_stdout,
        "StandardErrorPath": norm_stderr,
    }
    return plistlib.dumps(plist_data, fmt=plistlib.FMT_XML).decode("utf-8")


def install_launchd_agent(
    project_id: str,
    project_dir: str | Path,
    *,
    dest_dir: Path | None = None,
    dry_run: bool = False,
    force: bool = False,
    talo_bin: str | None = None,
) -> tuple[bool, Path | None, str]:
    """launchd plist를 생성하고 파일 권한 0600으로 설치한다."""
    plist_xml = generate_launchd_plist(project_id, project_dir, talo_bin=talo_bin)
    plist_path = get_launch_agent_path(project_id, dest_dir)

    if dry_run:
        return True, plist_path, plist_xml

    if plist_path.exists() and not force:
        return False, plist_path, f"이미 LaunchAgent 파일이 존재합니다: {plist_path} (--force로 덮어쓰기)"

    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(plist_xml.encode("utf-8"))
    plist_path.chmod(0o600)

    return True, plist_path, "LaunchAgent 설치 완료"


def uninstall_launchd_agent(
    project_id: str,
    *,
    dest_dir: Path | None = None,
) -> tuple[bool, str]:
    """launchd plist를 언로드 및 삭제한다."""
    plist_path = get_launch_agent_path(project_id, dest_dir)
    if not plist_path.exists():
        return False, f"등록된 LaunchAgent 파일이 없습니다: {plist_path}"

    if shutil.which("launchctl"):
        try:
            subprocess.run(
                ["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path)],
                capture_output=True, timeout=3, check=False,
            )
        except Exception:
            pass

    try:
        plist_path.unlink()
        return True, f"LaunchAgent 파일 제거 완료: {plist_path}"
    except Exception as exc:
        return False, f"파일 삭제 실패: {exc}"


def status_launchd_agent(
    project_id: str,
    *,
    dest_dir: Path | None = None,
) -> dict[str, Any]:
    """LaunchAgent 파일 상태 및 launchctl 등록 여부를 확인한다."""
    plist_path = get_launch_agent_path(project_id, dest_dir)
    label = f"{LAUNCHD_LABEL_PREFIX}.{project_id}"
    status: dict[str, Any] = {
        "label": label,
        "plist_path": str(plist_path),
        "installed": False,
        "permissions": None,
        "valid_permissions": False,
        "loaded": False,
        "config": {},
        "error": None,
    }

    if not plist_path.exists():
        return status

    status["installed"] = True
    st_mode = plist_path.stat().st_mode & 0o777
    status["permissions"] = oct(st_mode)
    status["valid_permissions"] = (st_mode == 0o600)

    try:
        data = plistlib.loads(plist_path.read_bytes())
        status["config"] = {
            "program_arguments": data.get("ProgramArguments", []),
            "working_directory": data.get("WorkingDirectory", ""),
            "start_interval": data.get("StartInterval"),
            "run_at_load": data.get("RunAtLoad"),
            "stdout": data.get("StandardOutPath", ""),
            "stderr": data.get("StandardErrorPath", ""),
        }
    except Exception as exc:
        status["error"] = f"plist 파싱 오류: {exc}"

    if shutil.which("launchctl"):
        try:
            proc = subprocess.run(
                ["launchctl", "list"],
                capture_output=True, text=True, timeout=3, check=False,
            )
            if proc.returncode == 0 and label in proc.stdout:
                status["loaded"] = True
        except Exception:
            pass

    return status


def cmd_cron_install(args: Any) -> int:
    ctx = create_app_context()
    try:
        dest_dir = Path(args.dest_dir).expanduser() if getattr(args, "dest_dir", None) else None
        dry_run = getattr(args, "dry_run", False)
        force = getattr(args, "force", False)
        talo_bin = getattr(args, "talo_bin", None)

        ok, path, msg = install_launchd_agent(
            ctx.project_id,
            ctx.cwd,
            dest_dir=dest_dir,
            dry_run=dry_run,
            force=force,
            talo_bin=talo_bin,
        )

        if dry_run:
            render.console.print(f"[cyan]=== {path} (Dry Run) ===[/cyan]")
            render.console.print(msg)
            return int(ExitCode.COMPLETED)

        if not ok:
            render.console.print(f"[yellow]{msg}[/yellow]")
            return int(ExitCode.INPUT_ERROR)

        render.console.print("[bold green]✓ macOS launchd LaunchAgent 생성 완료[/bold green]")
        render.console.print(f"  파일 경로: [cyan]{path}[/cyan]")
        render.console.print("  파일 권한: [bold]0600[/bold] (-rw-------)")
        render.console.print("  실행 주기: [bold]매 60초[/bold] (StartInterval=60, RunAtLoad=True)")
        render.console.print(f"  작업 위치: {ctx.cwd}")
        render.console.print("\n[bold]LaunchAgent 등록 명령어:[/bold]")
        render.console.print(f"  launchctl bootstrap gui/$(id -u) {path}")
        render.console.print("(또는 레거시 명령어):")
        render.console.print(f"  launchctl load {path}")
        return int(ExitCode.COMPLETED)
    finally:
        ctx.close()


def cmd_cron_uninstall(args: Any) -> int:
    ctx = create_app_context()
    try:
        dest_dir = Path(args.dest_dir).expanduser() if getattr(args, "dest_dir", None) else None
        ok, msg = uninstall_launchd_agent(ctx.project_id, dest_dir=dest_dir)
        if ok:
            render.console.print(f"[green]✓ {msg}[/green]")
            return int(ExitCode.COMPLETED)
        render.console.print(f"[yellow]{msg}[/yellow]")
        return int(ExitCode.INPUT_ERROR)
    finally:
        ctx.close()


def cmd_cron_status(args: Any) -> int:
    ctx = create_app_context()
    try:
        dest_dir = Path(args.dest_dir).expanduser() if getattr(args, "dest_dir", None) else None
        st = status_launchd_agent(ctx.project_id, dest_dir=dest_dir)
        render.console.print(f"\n[bold cyan]macOS LaunchAgent 상태 — {ctx.project_id}[/bold cyan]")
        render.console.print(f"  서비스 라벨: {st['label']}")
        render.console.print(f"  파일 위치:   {st['plist_path']}")
        render.console.print(f"  설치 여부:   {'[green]설치됨[/green]' if st['installed'] else '[yellow]미설치[/yellow]'}")
        if st["installed"]:
            perm_color = "green" if st["valid_permissions"] else "red"
            render.console.print(f"  파일 권한:   [{perm_color}]{st['permissions']} (0600 권장)[/{perm_color}]")
            cfg = st.get("config", {})
            render.console.print(f"  실행 간격:   {cfg.get('start_interval')}초")
            render.console.print(f"  RunAtLoad:   {cfg.get('run_at_load')}")
            render.console.print(f"  작업 경로:   {cfg.get('working_directory')}")
            render.console.print(f"  launchd 등록: {'[green]활성 (loaded)[/green]' if st['loaded'] else '[yellow]미등록 (bootstrap 필요)[/yellow]'}")
            if not st["loaded"]:
                render.console.print(f"  [dim]등록 명령어: launchctl bootstrap gui/$(id -u) {st['plist_path']}[/dim]")
        return int(ExitCode.COMPLETED)
    finally:
        ctx.close()
