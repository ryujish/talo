"""P1 Slice 3 후속: 승인 Inbox\ndaily 일지, 관련 테스트.

approval_requests 감사 CRUD, talo inbox list/approve/deny, talo daily 원자 생성
· 미완료 이월, resume 미완료 표시, 출력 정제(sanitize)를 검증한다.
"""
from __future__ import annotations

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


def _ctx(monkeypatch, env):
    from talo.application.service import create_app_context
    return create_app_context(Path(env))


# ---------------------------------------------------------------------------
# sanitize (정제)
# ---------------------------------------------------------------------------

def test_redact_secrets_and_scopes():
    from talo.sanitize import redact_text, sanitize_scope_json, redact_scope

    out = redact_text("API_KEY=sk-abc123456\npush=2", 200)
    assert "sk-abc123456" not in out
    assert "API_KEY=<redacted>" in out

    scope = {"path": "a.txt", "password": "p@ss", "command": "ls -al | head -99999"}
    redacted = redact_scope(scope, 12)
    assert redacted["password"] == "<redacted>"
    assert redacted["path"] == "a.txt"
    assert len(redacted["command"]) <= 12 + 1  # 잘림 + '…'

    js = sanitize_scope_json(json.dumps(scope), 12)
    assert "p@ss" not in js


# ---------------------------------------------------------------------------
# approval_requests 감사 CRUD
# ---------------------------------------------------------------------------

def test_approval_crud_and_decide_idempotent(repo):
    aid = repo.create_approval_request("ses_1", "run_1", "git_commit", '{"message":"커밋"}')
    row = repo.get_approval_request(aid)
    assert row["status"] == "pending"
    assert row["tool_name"] == "git_commit"
    assert row["session_id"] == "ses_1"

    assert repo.decide_approval_request(aid, "approved", "user") is True
    row = repo.get_approval_request(aid)
    assert row["status"] == "approved"
    assert row["decided_by"] == "user"

    # 한 번 결정된 요청은 재결정 불가
    assert repo.decide_approval_request(aid, "denied", "user") is False
    assert repo.get_approval_request(aid)["status"] == "approved"

    pending = repo.list_approval_requests(status="pending")
    assert all(r["status"] == "pending" for r in pending)
    assert all(r["id"] != aid for r in pending)


def test_approval_scope_is_redacted_before_storage(repo):
    aid = repo.create_approval_request(
        "ses_1", "run_1", "command_run",
        '{"authorization":"Bearer abcdefghijk","api_key":"sk-abc123456","path":"a.txt"}',
    )
    stored = repo.get_approval_request(aid)["scope_json"]
    assert "abcdefghijk" not in stored
    assert "sk-abc123456" not in stored
    assert stored.count("<redacted>") == 2
    assert "a.txt" in stored


# ---------------------------------------------------------------------------
# talo inbox CLI
# ---------------------------------------------------------------------------

def test_inbox_list_approve_deny_no_replay(env, monkeypatch, capsys):
    from talo.cli.main import main as cli_main
    ctx = _ctx(monkeypatch, env)
    try:
        aid = ctx.repository.create_approval_request(
            "ses_1", "run_1", "file_write", '{"path":"x.py","content":"secret sk-abc999"}')
    finally:
        ctx.close()

    assert cli_main(["inbox", "list"]) == 0
    out = capsys.readouterr().out
    assert aid[:8] in out
    assert "file_write" in out
    assert "sk-abc999" not in out  # 원문/비밀 정제

    # 승인 — 자동 재생 없음 (상태만 변경)
    assert cli_main(["inbox", "approve", aid]) == 0
    out = capsys.readouterr().out
    assert aid[:16] in out
    assert "승인" in out and "자동 재생 없음" in out

    ctx = _ctx(monkeypatch, env)
    try:
        row = ctx.repository.get_approval_request(aid)
        assert row["status"] == "approved"
        assert row["decided_by"] == "user"
    finally:
        ctx.close()

    # 이미 결정된 요청 재결정 → 실패
    assert cli_main(["inbox", "approve", aid]) == 2

    # deny 경로
    ctx = _ctx(monkeypatch, env)
    try:
        bid = ctx.repository.create_approval_request("ses_2", "run_2", "command_run", '{"command":"rm -rf /"}')
    finally:
        ctx.close()
    assert cli_main(["inbox", "deny", bid]) == 0
    ctx = _ctx(monkeypatch, env)
    try:
        assert ctx.repository.get_approval_request(bid)["status"] == "denied"
    finally:
        ctx.close()


def test_inbox_unknown_request(env, monkeypatch, capsys):
    from talo.cli.main import main as cli_main
    assert cli_main(["inbox", "approve", "apr_nope"]) == 2


# ---------------------------------------------------------------------------
# talo daily (원자 생성 + 전날 미완료 이월)
# ---------------------------------------------------------------------------

def test_daily_version_migration(repo):
    row = repo.conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC").fetchone()
    from talo.storage.db import MIGRATIONS
    assert row["version"] == len(MIGRATIONS)
    tables = {r["name"] for r in repo.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "approval_requests" in tables


def test_daily_generates_file_and_carries_unchecked(env, monkeypatch):
    from talo.application.service import start_session
    from talo import daily

    # 오늘/전날일지 직접 준비: 전날 미완료 체크박스 + 오늘 날짜
    today = daily.date.today().isoformat()
    from datetime import date, timedelta
    prev_day = (date.fromisoformat(today) - timedelta(days=1)).isoformat()

    ctx = _ctx(monkeypatch, env)
    try:
        sid = start_session(ctx)
        # 오늘 실행된 런을 만들어 세션이 일지 '오늘 작업'에 포함되게 함
        ctx.repository.create_run(sid, "req_1", "plan", "completed")
        ctx.repository.save_handoff(sid, "run_1", 1, {"next_actions": ["관련 해시 정리", "문서화"]})
        # 전날 일지에 미완료 체크박스 기록
        prev = daily.daily_path(ctx.project_id, prev_day)
        prev.parent.mkdir(parents=True, exist_ok=True)
        prev.write_text("- [ ] 이월할 작업 A\n- [x] 완료한 것\n", encoding="utf-8")

        target = daily.build_daily_report(ctx)
        text = target.read_text(encoding="utf-8")
    finally:
        ctx.close()

    assert target.name == f"{today}.md"
    # 확인한 체크박스, 완료 체크박스는 이월되지 않음
    assert "- [ ] 이월할 작업 A" in text
    assert "- [ ] 완료한 것" not in text
    # handoff next_actions 이월
    assert "관련 해시 정리" in text and "문서화" in text


# ---------------------------------------------------------------------------
# resume 미완료 표시
# ---------------------------------------------------------------------------

def test_resume_shows_incomplete(env, monkeypatch, capsys):
    from talo.application.service import start_session
    from talo.cli.main import _show_incomplete

    ctx = _ctx(monkeypatch, env)
    try:
        sid = start_session(ctx)
        ctx.repository.save_handoff(sid, "run_1", 1, {"next_actions": ["남은 검증", "보고서"]})
        _show_incomplete(ctx, sid)
        out = capsys.readouterr().out
        assert "미완료 작업" in out
        assert "남은 검증" in out
        assert "보고서" in out

        # handoff가 없는 세션은 미완료 표시 없이 조용히 지나감
        capsys.readouterr()
        sid2 = start_session(ctx)
        _show_incomplete(ctx, sid2)
        assert capsys.readouterr().out == ""
    finally:
        ctx.close()


def test_resume_list_sessions(env, monkeypatch, capsys):
    from talo.application.service import start_session
    from talo.cli.main import main as cli_main

    ctx = _ctx(monkeypatch, env)
    try:
        start_session(ctx, "테스트 세션")
    finally:
        ctx.close()

    assert cli_main(["resume"]) == 0
    assert "테스트 세션" in capsys.readouterr().out


def test_resume_by_id_shows_five_sections(env, monkeypatch, capsys):
    from talo.application.service import start_session
    from talo.cli.changes import show_resume

    ctx = _ctx(monkeypatch, env)
    try:
        sid = start_session(ctx, "세션 1")
        handoff_doc = {
            "schema": "talo.handoff/0.2",
            "goal": "웹 성능 최적화",
            "completed_tasks": [
                {"id": "task_1", "title": "벤치마크 작성", "status": "done", "evidence": "테스트 통과"}
            ],
            "open_tasks": [
                {"id": "task_2", "title": "캐시 개선", "status": "in_progress"}
            ],
            "verification": [
                {"command": "pytest", "status": "succeeded", "exit_code": 0}
            ],
            "next_actions": [
                "캐시 검토 (task_2)"
            ],
            "workspace_hash": "dummy",
        }
        ctx.repository.save_handoff(sid, "run_1", 1, handoff_doc)
        run_id = ctx.repository.create_run(sid, "request_1", "dev", "completed")
        ctx.repository.append_message(
            run_id, "assistant", json.dumps([{"type": "text", "text": "최종 답변입니다."}])
        )
        show_resume(ctx, sid)
        out = capsys.readouterr().out
        assert "목표" in out and "웹 성능 최적화" in out
        assert "완료" in out and "벤치마크 작성" in out
        assert "남은 일" in out and "캐시 개선" in out
        assert "검증" in out and "pytest" in out
        assert "다음 행동" in out and "캐시 검토" in out
        assert "마지막 문구" in out and "최종 답변입니다." in out
    finally:
        ctx.close()


def test_resume_by_numeric_index(env, monkeypatch, capsys):
    from talo.application.service import start_session
    from talo.cli.main import main as cli_main

    ctx = _ctx(monkeypatch, env)
    try:
        sid = start_session(ctx, "첫번째 세션")
    finally:
        ctx.close()

    assert cli_main(["resume", "1"]) == 0
    out = capsys.readouterr().out
    assert "세션 재개" in out
    assert sid in out


def test_resume_with_request(env, monkeypatch, capsys):
    from talo.application.service import start_session
    from talo.cli.main import main as cli_main

    ctx = _ctx(monkeypatch, env)
    try:
        sid = start_session(ctx, "실행 세션")
    finally:
        ctx.close()

    assert cli_main(["resume", sid, "안녕"]) == 0
    out = capsys.readouterr().out
    assert "세션 재개" in out
    assert sid in out

    ctx2 = _ctx(monkeypatch, env)
    try:
        runs = ctx2.repository.list_runs(sid)
        assert len(runs) >= 1
    finally:
        ctx2.close()


def test_resume_interactive_select(env, monkeypatch, capsys):
    from talo.application.service import start_session
    from talo.cli.main import main as cli_main

    ctx = _ctx(monkeypatch, env)
    try:
        sid = start_session(ctx, "선택 세션")
    finally:
        ctx.close()

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("talo.cli.connection_wizard._choose_menu", lambda *args, **kwargs: "1")
    assert cli_main(["resume"]) == 0
    out = capsys.readouterr().out
    assert "세션 재개" in out
    assert sid in out


def test_resume_escape_returns_to_previous_step(env, monkeypatch, capsys):
    from talo.application.service import start_session
    from talo.cli.main import main as cli_main

    ctx = _ctx(monkeypatch, env)
    try:
        start_session(ctx, "취소 세션")
    finally:
        ctx.close()

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("talo.cli.connection_wizard._choose_menu", lambda *args, **kwargs: "0")
    assert cli_main(["resume"]) == 0
    assert "세션 재개" not in capsys.readouterr().out


def test_resume_slash_switches_session(env, monkeypatch, capsys):
    from talo.application.service import start_session
    from talo.cli.interactive import _handle_slash_interactive

    ctx = _ctx(monkeypatch, env)
    try:
        sid = start_session(ctx, "슬래시 세션")
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("talo.cli.connection_wizard._choose_menu", lambda *args, **kwargs: "1")
        result = _handle_slash_interactive(ctx, sid, "/resume")
        assert result == {"session_id": sid}
        assert sid in capsys.readouterr().out
    finally:
        ctx.close()


def test_resume_with_next_action(env, monkeypatch, capsys):
    from talo.application.service import start_session
    from talo.cli.main import main as cli_main

    ctx = _ctx(monkeypatch, env)
    try:
        sid = start_session(ctx, "넥스트 세션")
        handoff_doc = {
            "schema": "talo.handoff/0.2",
            "goal": "목표",
            "open_tasks": [],
            "completed_tasks": [],
            "verification": [],
            "next_actions": ["자동 다음 작업"],
            "workspace_hash": "dummy",
        }
        ctx.repository.save_handoff(sid, "run_1", 1, handoff_doc)
    finally:
        ctx.close()

    assert cli_main(["resume", sid, "--next"]) == 0
    out = capsys.readouterr().out
    assert "세션 재개" in out

    ctx2 = _ctx(monkeypatch, env)
    try:
        runs = ctx2.repository.list_runs(sid)
        assert len(runs) >= 1
    finally:
        ctx2.close()


def test_resume_slash_with_request_and_next(env, monkeypatch, capsys):
    from talo.application.service import start_session
    from talo.cli.interactive import _handle_slash_interactive

    ctx = _ctx(monkeypatch, env)
    try:
        sid = start_session(ctx, "슬래시 후속요청 세션")
        handoff_doc = {
            "schema": "talo.handoff/0.2",
            "goal": "목표",
            "open_tasks": [],
            "completed_tasks": [],
            "verification": [],
            "next_actions": [{"title": "슬래시 자동 다음 작업"}],
            "workspace_hash": "dummy",
        }
        ctx.repository.save_handoff(sid, "run_1", 1, handoff_doc)

        # 1. 인자와 함께 즉시 실행 요청
        res1 = _handle_slash_interactive(ctx, sid, f"/resume {sid} 추가작업실행")
        assert res1 == {"session_id": sid, "run_request": "추가작업실행"}

        # 2. --next 플래그로 handoff의 다음 작업 가져오기
        res2 = _handle_slash_interactive(ctx, sid, f"/resume {sid} --next")
        assert res2 == {"session_id": sid, "run_request": "슬래시 자동 다음 작업"}
    finally:
        ctx.close()
