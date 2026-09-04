"""실행 루프 통합 테스트: A1·A3·A4·A11 시나리오."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from talo.schemas import ExitCode

MOCK_CONFIG = """
default_model = "mock_1:mock-model"
connections = { mock_1 = { connection_id = "mock_1", provider_id = "mock", protocol = "mock", base_url = "", credential_ref = "env:NONE", model_id = "mock-model", capabilities = {}, validated_at = "" } }
"""


@pytest.fixture()
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("TALO_HOME", str(home))
    (home / "config.toml").write_text(MOCK_CONFIG, encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    monkeypatch.chdir(repo)
    return repo


def _run(monkeypatch, repo, script: list[dict], request: str, mode: str = "dev", permission: str = "project_edit"):
    from talo.application.service import create_app_context, run_request, start_session

    monkeypatch.setenv("TALO_MOCK_SCRIPT", json.dumps(script, ensure_ascii=False))
    ctx = create_app_context(Path(repo))
    try:
        sid = start_session(ctx, title=request[:40])
        events: list[tuple[str, dict]] = []

        async def on_human(t, p):
            events.append((t, p))

        outcome = asyncio_run(
            run_request(ctx, request, session_id=sid, mode=mode, permission=permission, on_human=on_human)
        )
        return outcome, events, ctx
    except Exception:
        ctx.close()
        raise


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


def test_a1_no_connection(tmp_path, monkeypatch):
    """연결 정보 없는 첫 실행: 안내 후 종료, 빈 오류 없음."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("TALO_HOME", str(home))
    from talo.application.service import create_app_context, run_request, start_session

    ctx = create_app_context()
    try:
        sid = start_session(ctx)
        events: list[tuple[str, dict]] = []

        async def on_human(t, p):
            events.append((t, p))

        outcome = asyncio_run(run_request(ctx, "안녕", session_id=sid, on_human=on_human))
        assert outcome.exit_code == ExitCode.INPUT_ERROR
        types = [t for t, _ in events]
        assert "run.started" in types and "run.failed" in types
        failed = next(p for t, p in events if t == "run.failed")
        assert "talo connect" in failed["message"]
    finally:
        ctx.close()


def test_a4_mock_run_with_tool(env, monkeypatch):
    """실제 도구 실행이 이벤트·검증 근거로 기록됨."""
    script = [
        {"tool": {"name": "file_read", "arguments": {"path": "a.txt"}}},
        {"text": "확인했습니다."},
    ]
    outcome, events, ctx = _run(monkeypatch, env, script, "a.txt 확인해줘")
    try:
        assert outcome.exit_code == ExitCode.COMPLETED
        types = [t for t, _ in events]
        assert "tool.started" in types and "tool.completed" in types
        completed = next(p for t, p in events if t == "run.completed")
        assert completed["summary"] == "확인했습니다."
        # 메시지가 DB에 저장됨
        msgs = ctx.repository.list_messages(outcome.run_id)
        assert any(m["role"] == "assistant" for m in msgs)
    finally:
        ctx.close()


def test_a3_plan_mode_blocks_write(env, monkeypatch):
    script = [
        {"tool": {"name": "file_write", "arguments": {"path": "nope.txt", "content": "x"}}},
        {"text": "기획 결과입니다."},
    ]
    outcome, events, ctx = _run(monkeypatch, env, script, "기획만 해줘", mode="plan")
    try:
        assert outcome.exit_code == ExitCode.COMPLETED
        completed = next(p for t, p in events if t == "tool.completed")
        assert completed["status"] == "denied"
        assert not (env / "nope.txt").exists()
    finally:
        ctx.close()


def test_a11_approval_required_non_interactive(env, monkeypatch):
    script = [{"tool": {"name": "command_run", "arguments": {
        "command": "echo hello", "cwd": ".", "authorization": "Bearer abcdefghijk"}}}]
    outcome, events, ctx = _run(monkeypatch, env, script, "echo 실행해줘")
    try:
        assert outcome.exit_code == ExitCode.APPROVAL_NEEDED
        types = [t for t, _ in events]
        assert "approval.required" in types and "run.paused" in types
        approval = next(p for t, p in events if t == "approval.required")
        assert approval["arguments"]["authorization"] == "<redacted>"
        stored = ctx.repository.list_approval_requests("pending")
        assert len(stored) == 1 and "abcdefghijk" not in stored[0]["scope_json"]
    finally:
        ctx.close()


def test_approval_allow_executes(env, monkeypatch):
    script = [
        {"tool": {"name": "command_run", "arguments": {"command": "echo hello", "cwd": "."}}},
        {"text": "실행 완료"},
    ]
    from talo.application.service import create_app_context, run_request, start_session

    monkeypatch.setenv("TALO_MOCK_SCRIPT", json.dumps(script, ensure_ascii=False))
    ctx = create_app_context(Path(env))
    try:
        sid = start_session(ctx)
        events: list[tuple[str, dict]] = []

        async def on_human(t, p):
            events.append((t, p))

        async def approve(tool, scope):
            return True

        outcome = asyncio_run(
            run_request(ctx, "echo 실행해줘", session_id=sid, on_human=on_human, on_approval=approve)
        )
        assert outcome.exit_code == ExitCode.COMPLETED
        verif = [p for t, p in events if t == "verification.recorded"]
        assert verif and verif[0]["result"] == "passed"
    finally:
        ctx.close()


def test_jsonl_event_schema(env, monkeypatch):
    """talo run --json은 stdout에 스키마 준수 JSONL만 출력하고 종료 코드를 구분한다."""
    import os
    import sys

    script = [{"text": "답변입니다."}]
    monkeypatch.setenv("TALO_MOCK_SCRIPT", json.dumps(script, ensure_ascii=False))
    proc = subprocess.run(
        [sys.executable, "-m", "talo", "run", "질문", "--json"],
        cwd=env, capture_output=True, text=True,
        env={**os.environ, "TALO_HOME": str(env.parent / "home"),
             "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert proc.returncode == 0
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    assert lines
    for line in lines:
        evt = json.loads(line)
        for field in ("schema_version", "event_id", "session_id", "run_id", "seq", "timestamp", "type", "payload"):
            assert field in evt
    types = [json.loads(l)["type"] for l in lines]
    assert "run.started" in types and "run.completed" in types
