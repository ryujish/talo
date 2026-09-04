"""Slice 1 스케줄 저장 계층 테스트.

scheduled_jobs/scheduled_runs v2 마이그레이션, 프로젝트 격리, 원자 선점.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from talo.storage.db import Database
from talo.storage.repository import Repository

MOCK_CONFIG = """
default_model = "mock_1:mock-model"
connections = { mock_1 = { connection_id = "mock_1", provider_id = "mock", protocol = "mock", base_url = "", credential_ref = "env:NONE", model_id = "mock-model", capabilities = {}, validated_at = "" } }
"""


@pytest.fixture()
def repo(tmp_path):
    db = Database(tmp_path / "state.sqlite")
    db.migrate()
    yield Repository(db)
    db.close()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("TALO_HOME", str(home))
    (home / "config.toml").write_text(MOCK_CONFIG, encoding="utf-8")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "t"], check=True)
    (repo_dir / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-qm", "init"], check=True)
    monkeypatch.chdir(repo_dir)
    return repo_dir


def _make_job(repo: Repository, project_id: str = "proj_a", name: str = "daily",
              next_run_at: float = 1000.0) -> str:
    return repo.create_job(project_id, name, "요약 프롬프트", '{"kind":"daily","hhmm":"08:00"}',
                           "local", next_run_at=next_run_at)


def test_migration_v2_scheduled_tables(repo):
    row = repo.conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC").fetchone()
    assert row["version"] == 3
    tables = {r["name"] for r in repo.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"scheduled_jobs", "scheduled_runs", "approval_requests"} <= tables


def test_create_and_list_jobs_project_scoped(repo):
    a = _make_job(repo, "proj_a")
    _make_job(repo, "proj_b")

    jobs_a = repo.list_jobs("proj_a")
    assert [j["id"] for j in jobs_a] == [a]
    assert repo.get_job(a)["project_id"] == "proj_a"
    assert repo.get_job(a)["enabled"] == 1


def test_disable_job_project_scoped(repo):
    a = _make_job(repo, "proj_a")

    assert repo.disable_job(a, "proj_a") is True
    assert repo.get_job(a)["enabled"] == 0
    # 다른 프로젝트로 disable 시도 → 영향 없음
    assert repo.disable_job(a, "proj_b") is False
    assert repo.get_job(a)["enabled"] == 0


def test_due_jobs_only_enabled_and_due(repo):
    a = _make_job(repo, "proj_a", next_run_at=1000.0)
    b = repo.create_job("proj_a", "later", "p", "{}", "local", next_run_at=9999.0)
    _make_job(repo, "proj_b", next_run_at=10.0)
    repo.disable_job(a, "proj_a")

    assert repo.due_jobs("proj_a", now=5000.0) == []
    due = repo.due_jobs("proj_a", now=20000.0)
    assert [j["id"] for j in due] == [b]  # a는 비활성, proj_b는 격리로 제외


def test_claim_due_job_atomic_unique_slot(repo):
    jid = _make_job(repo, "proj_a", next_run_at=1000.0)

    first = repo.claim_due_job(jid, "proj_a", scheduled_for=1000.0, next_run_at=2000.0)
    assert first is not None
    # 동일 슬롯 두 번째 선점은 UNIQUE 충돌로 None
    second = repo.claim_due_job(jid, "proj_a", scheduled_for=1000.0, next_run_at=2000.0)
    assert second is None
    # 다음 슬롯은 선점 가능
    third = repo.claim_due_job(jid, "proj_a", scheduled_for=2000.0, next_run_at=3000.0)
    assert third is not None
    # 선점 시 next_run_at 전진
    assert repo.get_job(jid)["next_run_at"] == 3000.0


def test_claim_due_job_wrong_project_rejected(repo):
    jid = _make_job(repo, "proj_a", next_run_at=1000.0)

    assert repo.claim_due_job(jid, "proj_b", scheduled_for=1000.0, next_run_at=2000.0) is None
    # 원 프로젝트의 job 상태는 그대로
    assert repo.get_job(jid)["next_run_at"] == 1000.0
    assert repo.scheduled_run_history(jid) == []


def test_mark_scheduled_run_and_history(repo):
    jid = _make_job(repo, "proj_a", next_run_at=1000.0)
    rid = repo.claim_due_job(jid, "proj_a", scheduled_for=1000.0, next_run_at=2000.0)

    repo.mark_scheduled_run(rid, "running", session_id="ses_1", started_at=1001.0)
    repo.mark_scheduled_run(rid, "succeeded", run_id="run_1", finished_at=1005.0)

    history = repo.scheduled_run_history(jid)
    assert len(history) == 1
    assert history[0]["state"] == "succeeded"
    assert history[0]["session_id"] == "ses_1"
    assert history[0]["run_id"] == "run_1"
    assert history[0]["scheduled_for"] == 1000.0


# ---------------------------------------------------------------------------
# run-due 무인 실행 (mock provider + read_only)
# ---------------------------------------------------------------------------

def _ctx(monkeypatch, env):
    from talo.application.service import create_app_context
    ctx = create_app_context(Path(env))
    return ctx


def _add_due(ctx, name="daily"):
    from talo import cron
    jid = ctx.repository.create_job(
        ctx.project_id, name, "ex", json.dumps({"hhmm": "08:00", "weekdays": None}),
        "local", next_run_at=0.0)
    return jid


def _run_due(monkeypatch, env, script):
    from talo import cron
    monkeypatch.setenv("TALO_MOCK_SCRIPT", json.dumps(script, ensure_ascii=False))
    ctx = _ctx(monkeypatch, env)
    try:
        return asyncio.run(cron.run_due_jobs(ctx)), ctx
    except Exception:
        ctx.close()
        raise


def test_run_due_executes_read_only_and_records(env, monkeypatch):
    """mock active 연결로 read_only 실행 성공, scheduled_runs에 기록."""
    from talo import cron
    ctx = _ctx(monkeypatch, env)
    try:
        jid = _add_due(ctx)
        script = [{"tool": {"name": "file_read", "arguments": {"path": "a.txt"}}}, {"text": "확인"}]
        monkeypatch.setenv("TALO_MOCK_SCRIPT", json.dumps(script, ensure_ascii=False))
        results = asyncio.run(cron.run_due_jobs(ctx))
        assert results and results[0]["state"] == "succeeded"
        history = ctx.repository.scheduled_run_history(jid)
        assert len(history) == 1
        assert history[0]["state"] == "succeeded"
        assert history[0]["scheduled_for"] == 0.0
        assert history[0]["session_id"] and history[0]["run_id"]
        # 실행 후 next_run_at이 전진해 다시 due가 아닌지 확인
        assert ctx.repository.due_jobs(ctx.project_id) == []
        from talo import daily
        assert daily.daily_path(ctx.project_id).exists()
    finally:
        ctx.close()


def test_run_due_skips_write_tool_under_read_only(env, monkeypatch):
    """read_only 무인 실행은 WRITE 도구를 승인 없이 실행하지 않는다."""
    from talo import cron
    ctx = _ctx(monkeypatch, env)
    try:
        jid = _add_due(ctx)
        script = [{"tool": {"name": "file_write", "arguments": {"path": "a.txt", "content": "x"}}}]
        monkeypatch.setenv("TALO_MOCK_SCRIPT", json.dumps(script, ensure_ascii=False))
        results = asyncio.run(cron.run_due_jobs(ctx))
        # 승인 불가 → APPROVAL_NEEDED → failed로 기록
        assert results[0]["state"] == "failed"
        # 파일이 실제로 변경되지 않았어야 함
        assert (env / "a.txt").read_text() == "hello\n"
        history = ctx.repository.scheduled_run_history(jid)
        assert history[0]["state"] == "failed"
    finally:
        ctx.close()


def test_run_due_same_slot_idempotent(env, monkeypatch):
    """같은 분 슬롯 재실행 시 선점 실패로 중복 실행하지 않는다."""
    from talo import cron
    ctx = _ctx(monkeypatch, env)
    try:
        jid = _add_due(ctx)
        script = [{"text": "확인"}]
        monkeypatch.setenv("TALO_MOCK_SCRIPT", json.dumps(script, ensure_ascii=False))
        first = asyncio.run(cron.run_due_jobs(ctx))
        assert first[0]["state"] == "succeeded"
        # next_run_at 전진으로 같은 슬롯에서는 다시 due가 아님 → 두 번째는 0건
        second = asyncio.run(cron.run_due_jobs(ctx))
        assert second == []
        history = ctx.repository.scheduled_run_history(jid)
        assert len(history) == 1
    finally:
        ctx.close()


def test_run_due_disabled_job_not_executed(env, monkeypatch):
    from talo import cron
    ctx = _ctx(monkeypatch, env)
    try:
        jid = _add_due(ctx)
        ctx.repository.disable_job(jid, ctx.project_id)
        script = [{"text": "확인"}]
        monkeypatch.setenv("TALO_MOCK_SCRIPT", json.dumps(script, ensure_ascii=False))
        results = asyncio.run(cron.run_due_jobs(ctx))
        assert results == []
        assert ctx.repository.scheduled_run_history(jid) == []
    finally:
        ctx.close()


def test_run_due_timeout_is_recorded(env, monkeypatch):
    from talo import cron
    from talo.schemas import RunConfig

    ctx = _ctx(monkeypatch, env)
    try:
        jid = _add_due(ctx)

        async def slow_run(*args, **kwargs):
            await asyncio.sleep(0.05)

        monkeypatch.setattr(cron, "run_request", slow_run)
        results = asyncio.run(cron.run_due_jobs(
            ctx, run_config=RunConfig(max_iterations=1, timeout_seconds=0.001)))
        assert results[0]["state"] == "failed"
        assert ctx.repository.scheduled_run_history(jid)[0]["error"].startswith("TimeoutError")
    finally:
        ctx.close()


def test_build_schedule_json_and_next_run_at():
    from talo import cron
    from datetime import datetime
    s = json.loads(cron.build_schedule_json("09:30", [0, 1]))
    assert s == {"hhmm": "09:30", "weekdays": [0, 1]}
    t = datetime(2026, 9, 4, 10, 0).timestamp()  # 금
    nxt = cron._next_run_at(t, s)
    assert datetime.fromtimestamp(nxt).weekday() == 0  # 다음 월요일
    assert datetime.fromtimestamp(nxt).hour == 9 and datetime.fromtimestamp(nxt).minute == 30
    for bad in ["08:60", "25:00", "a:b", "8am"]:
        with pytest.raises(ValueError):
            cron._parse_hhmm(bad)
    with pytest.raises(ValueError):
        cron._parse_weekdays("mon,xxx")


# ---------------------------------------------------------------------------
# macOS launchd LaunchAgent 테스트
# 주의: 실제 사용자 ~/Library/LaunchAgents 디렉터리에 쓰지 않고 tmp_path를 사용한다.
# ---------------------------------------------------------------------------

def test_generate_launchd_plist_structure_and_safety(tmp_path):
    import plistlib
    from talo import cron

    proj_dir = tmp_path / "sample_project"
    proj_dir.mkdir()
    xml = cron.generate_launchd_plist(
        "proj_123",
        proj_dir,
        talo_bin="/custom/bin/talo",
        stdout_path=tmp_path / "out.log",
        stderr_path=tmp_path / "err.log",
    )

    data = plistlib.loads(xml.encode("utf-8"))
    assert data["Label"] == "ai.talo.cron.proj_123"
    assert data["ProgramArguments"] == ["/custom/bin/talo", "cron", "run-due"]
    assert data["WorkingDirectory"] == str(proj_dir.resolve())
    assert data["StartInterval"] == 60
    assert data["RunAtLoad"] is True
    assert data["StandardOutPath"] == str((tmp_path / "out.log").resolve())
    assert data["StandardErrorPath"] == str((tmp_path / "err.log").resolve())

    # 보안 경계 검증: 환경변수나 자격증명 필드가 절대 없어야 함
    assert "EnvironmentVariables" not in data
    assert "api_key" not in xml.lower()
    assert "secret" not in xml.lower()


def test_install_launchd_agent_file_permissions_0600(tmp_path):
    from talo import cron

    dest = tmp_path / "agents"
    proj_dir = tmp_path / "sample_project"
    proj_dir.mkdir()

    # 1. dry-run: 파일 쓰지 않음
    ok, path, content = cron.install_launchd_agent(
        "proj_test", proj_dir, dest_dir=dest, dry_run=True, talo_bin="/bin/talo")
    assert ok is True
    assert not (dest / "ai.talo.cron.proj_test.plist").exists()
    assert "ai.talo.cron.proj_test" in content

    # 2. 실제 설치 (임시 디렉터리)
    ok, path, msg = cron.install_launchd_agent(
        "proj_test", proj_dir, dest_dir=dest, dry_run=False, talo_bin="/bin/talo")
    assert ok is True
    assert path.exists()

    # 파일 권한 0600 (-rw-------) 검증
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600

    # 3. 덮어쓰기 방지: force=False이면 실패
    ok_dup, _, err = cron.install_launchd_agent(
        "proj_test", proj_dir, dest_dir=dest, dry_run=False, force=False)
    assert ok_dup is False
    assert "이미 LaunchAgent 파일이 존재합니다" in err

    # 4. force=True이면 성공
    ok_force, _, _ = cron.install_launchd_agent(
        "proj_test", proj_dir, dest_dir=dest, dry_run=False, force=True)
    assert ok_force is True


def test_uninstall_launchd_agent(tmp_path):
    from talo import cron

    dest = tmp_path / "agents"
    proj_dir = tmp_path / "sample_project"
    proj_dir.mkdir()

    # 존재하지 않는 파일 삭제 시도
    ok, msg = cron.uninstall_launchd_agent("proj_none", dest_dir=dest)
    assert ok is False
    assert "등록된 LaunchAgent 파일이 없습니다" in msg

    # 설치 후 삭제
    cron.install_launchd_agent("proj_test", proj_dir, dest_dir=dest)
    plist_path = dest / "ai.talo.cron.proj_test.plist"
    assert plist_path.exists()

    ok, msg = cron.uninstall_launchd_agent("proj_test", dest_dir=dest)
    assert ok is True
    assert not plist_path.exists()


def test_status_launchd_agent(tmp_path):
    from talo import cron

    dest = tmp_path / "agents"
    proj_dir = tmp_path / "sample_project"
    proj_dir.mkdir()

    # 미설치 상태
    st = cron.status_launchd_agent("proj_test", dest_dir=dest)
    assert st["installed"] is False

    # 설치 후 상태 확인
    cron.install_launchd_agent("proj_test", proj_dir, dest_dir=dest)
    st = cron.status_launchd_agent("proj_test", dest_dir=dest)
    assert st["installed"] is True
    assert st["valid_permissions"] is True
    assert st["config"]["start_interval"] == 60
    assert st["config"]["run_at_load"] is True


def test_cmd_cron_launchd_cli_handlers(tmp_path, env, monkeypatch):
    import argparse
    from talo import cron
    from talo.schemas import ExitCode

    dest = tmp_path / "agents"

    # install --dry-run
    args_dry = argparse.Namespace(
        dest_dir=str(dest), dry_run=True, force=False, talo_bin="/bin/talo")
    code = cron.cmd_cron_install(args_dry)
    assert code == int(ExitCode.COMPLETED)
    assert not (dest / "ai.talo.cron.proj_a.plist").exists()

    # install 실제 생성
    args_inst = argparse.Namespace(
        dest_dir=str(dest), dry_run=False, force=False, talo_bin="/bin/talo")
    code = cron.cmd_cron_install(args_inst)
    assert code == int(ExitCode.COMPLETED)

    # status
    args_st = argparse.Namespace(dest_dir=str(dest))
    code = cron.cmd_cron_status(args_st)
    assert code == int(ExitCode.COMPLETED)

    # uninstall
    args_un = argparse.Namespace(dest_dir=str(dest))
    code = cron.cmd_cron_uninstall(args_un)
    assert code == int(ExitCode.COMPLETED)
    assert not (dest / "ai.talo.cron.proj_a.plist").exists()
