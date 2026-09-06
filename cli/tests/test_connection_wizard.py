"""Talo CLI 대화형 연결 마법사 및 자동 감지 단위 테스트."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from talo.cli.connection_wizard import (
    SERVICE_PRESETS,
    _finalize_connection,
    run_model_picker,
    scan_local_environment,
)
from talo.cli.main import build_parser
from talo.config import Config, ConnectionConfig
from talo.providers.resolver import CredentialStore
from talo.providers.cli_subprocess import CliSubprocessAdapter


def test_parser_new_commands():
    parser = build_parser()
    args = parser.parse_args(["setup"])
    assert args.command == "setup"

    args = parser.parse_args(["model"])
    assert args.command == "model" and args.target is None

    args = parser.parse_args(["model", "deepcode_1:deepseek-v4-pro"])
    assert args.command == "model" and args.target == "deepcode_1:deepseek-v4-pro"

    args = parser.parse_args(["connect"])
    assert args.command == "connect" and args.action is None


def test_presets_validity():
    assert "deepseek" in SERVICE_PRESETS
    assert "openrouter" in SERVICE_PRESETS
    assert "openai" in SERVICE_PRESETS
    assert "gemini" in SERVICE_PRESETS
    assert "think_along" in SERVICE_PRESETS
    assert len(SERVICE_PRESETS["opencode"]["default_models"]) >= 20
    assert "opencode/big-pickle" in SERVICE_PRESETS["opencode"]["free_models"]
    assert len(SERVICE_PRESETS["agy"]["default_models"]) == 14

    deepseek = SERVICE_PRESETS["deepseek"]
    assert deepseek["base_url"] == "https://api.deepseek.com"
    assert "deepseek-chat" in deepseek["default_models"]

    think_along = SERVICE_PRESETS["think_along"]
    assert "mcp.flowpulse.ai.kr" in think_along["base_url"]
    assert think_along["env_names"] == ["THINK_ALONG_OAUTH_KEY"]
    assert "default_key" not in think_along


def test_scan_local_environment_deepcode_env(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("API_KEY", "sk-test-secret")

    discovered = scan_local_environment()
    deepcode = next((d for d in discovered if d["provider"] == "deepcode"), None)
    assert deepcode is not None
    assert deepcode["base_url"] == "https://api.deepseek.com"
    assert deepcode["model"] == "deepseek-v4-pro"
    assert deepcode["has_secret"] is True


def test_scan_local_environment_gemini_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaTestKey")

    discovered = scan_local_environment()
    gemini = next((d for d in discovered if d["provider"] == "gemini"), None)
    assert gemini is not None
    assert "generativelanguage.googleapis.com" in gemini["base_url"]
    assert gemini["credential_ref"] == "env:GEMINI_API_KEY"


def test_scan_local_environment_codex_file_supported(tmp_path, monkeypatch):
    import shutil
    fake_home = tmp_path / "userhome"
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "auth.json").write_text('{"token": "xyz"}', encoding="utf-8")

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/local/bin/codex" if cmd == "codex" else None)
    discovered = scan_local_environment()
    codex = next((d for d in discovered if d["provider"] == "codex_cli"), None)
    assert codex is not None
    assert "Codex CLI" in codex["title"]
    assert codex["supported"] is True
    assert codex["has_secret"] is True


def test_scan_local_environment_codex_file_unsupported(tmp_path, monkeypatch):
    import shutil
    fake_home = tmp_path / "userhome"
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "auth.json").write_text('{"token": "xyz"}', encoding="utf-8")

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    discovered = scan_local_environment()
    codex = next((d for d in discovered if d["provider"] == "codex"), None)
    assert codex is not None
    assert codex["supported"] is False


def test_finalize_connection_saves_and_activates(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg = Config(path=cfg_file)
    store = CredentialStore()

    with patch("httpx.Client") as mock_client:
        mock_instance = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "deepseek-v4-pro"}, {"id": "deepseek-chat"}]}
        mock_instance.get.return_value = mock_resp
        mock_client.return_value.__enter__.return_value = mock_instance

        with patch("builtins.input", return_value="1"):
            ok = _finalize_connection(
                config=cfg,
                store=store,
                provider_id="deepseek",
                base_url="https://api.deepseek.com",
                credential_ref="env:API_KEY",
                secret="sk-test",
                suggested_model="deepseek-v4-pro",
            )
            assert ok is True

    # 연결과 기본 모델이 한 번에 저장되었는지 확인 (S10 원스톱)
    assert len(cfg.connections) == 1
    conn = list(cfg.connections.values())[0]
    assert conn.provider_id == "deepseek"
    assert conn.model_id == "deepseek-v4-pro"
    assert cfg.default_model == f"{conn.connection_id}:{conn.model_id}"


def test_model_picker_switching(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg = Config(path=cfg_file)
    conn1 = ConnectionConfig("deepseek_1", "deepseek", model_id="deepseek-v4-pro")
    conn2 = ConnectionConfig("openai_1", "openai", model_id="gpt-4.1-mini")
    cfg.set_connection(conn1)
    cfg.set_connection(conn2)
    cfg.set_default_model("deepseek_1:deepseek-v4-pro")

    with patch("builtins.input", side_effect=["1", "1"]):
        picked = run_model_picker(cfg)
        assert picked == "openai_1:gpt-4.1-mini"
        assert cfg.default_model == "openai_1:gpt-4.1-mini"


def test_concurrent_config_instances_merge_connections(tmp_path):
    path = tmp_path / "config.toml"
    first = Config(path=path)
    second = Config(path=path)

    first.set_connection(ConnectionConfig("agy_cli", "agy", model_id="gemini-3.8-flash-high"))
    second.set_connection(ConnectionConfig("opencode_cli", "opencode", model_id="opencode/big-pickle"))
    second.set_default_model("opencode_cli:opencode/big-pickle")

    saved = Config.load(path)
    assert set(saved.connections) == {"agy_cli", "opencode_cli"}
    assert saved.default_model == "opencode_cli:opencode/big-pickle"


def test_model_picker_main_categories_are_fixed(tmp_path):
    cfg = Config(path=tmp_path / "config.toml")
    cfg.set_connection(ConnectionConfig("deepseek_1", "deepseek", model_id="deepseek-chat"))

    with (
        patch("talo.cli.connection_wizard.shutil.which", return_value=None),
        patch("talo.cli.connection_wizard.render.menu_table") as menu_table,
        patch("builtins.input", return_value="0"),
    ):
        run_model_picker(cfg)

    rows = menu_table.call_args.args[1]
    assert [row[1] for row in rows[:6]] == [
        "OpenAI", "Claude", "DeepSeek", "Kimi", "OpenCode", "Google",
    ]
    assert rows[6][1] == "ETC"


def test_model_picker_selects_provider_submodel(tmp_path):
    cfg = Config(path=tmp_path / "config.toml")
    conn = ConnectionConfig("deepseek_1", "deepseek", model_id="deepseek-chat")
    cfg.set_connection(conn)
    cfg.set_default_model("deepseek_1:deepseek-chat")

    with patch("builtins.input", side_effect=["3", "2"]):
        picked = run_model_picker(cfg)

    assert picked == "deepseek_1:deepseek-reasoner"
    assert cfg.default_model == "deepseek_1:deepseek-reasoner"


def test_model_picker_accepts_direct_submodel_id(tmp_path):
    cfg = Config(path=tmp_path / "config.toml")
    conn = ConnectionConfig("openai_1", "openai", model_id="gpt-4.1-mini")
    cfg.set_connection(conn)

    with (
        patch("talo.cli.connection_wizard.shutil.which", return_value=None),
        patch("builtins.input", side_effect=["8", "1", "gpt-custom"]),
    ):
        picked = run_model_picker(cfg)

    assert picked == "openai_1:gpt-custom"


def test_model_picker_shows_opencode_zen_catalog(tmp_path):
    cfg = Config(path=tmp_path / "config.toml")
    conn = ConnectionConfig(
        "opencode_1", "opencode", protocol="cli_subprocess",
        model_id="opencode/big-pickle", command="opencode",
    )
    cfg.set_connection(conn)

    with patch("builtins.input", side_effect=["7", "2"]):
        picked = run_model_picker(cfg)

    assert picked == "opencode_1:opencode/ling-3.0-flash-fin-free"


def test_model_picker_auto_connects_local_opencode(tmp_path):
    cfg = Config(path=tmp_path / "config.toml")
    auth = tmp_path / ".local/share/opencode/auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text("{}", encoding="utf-8")

    with (
        patch("talo.cli.connection_wizard.Path.home", return_value=tmp_path),
        patch("talo.cli.connection_wizard.shutil.which", return_value="/bin/opencode"),
        patch("builtins.input", side_effect=["4", "1"]),
    ):
        picked = run_model_picker(cfg)

    assert picked == "opencode_cli:opencode/kimi-k3"
    assert cfg.connection("opencode_cli").command == "opencode"


def test_model_picker_auto_connects_agy_under_google(tmp_path):
    cfg = Config(path=tmp_path / "config.toml")
    (tmp_path / ".gemini/antigravity-cli").mkdir(parents=True)

    with (
        patch("talo.cli.connection_wizard.Path.home", return_value=tmp_path),
        patch(
            "talo.cli.connection_wizard.shutil.which",
            side_effect=lambda command: "/bin/agy" if command == "agy" else None,
        ),
        patch("builtins.input", side_effect=["6", "1"]),
    ):
        picked = run_model_picker(cfg)

    assert picked == "agy_cli:gemini-3.8-flash-high"
    assert cfg.connection("agy_cli").command == "agy"


def test_agy_bridge_uses_dangerous_permissions_flag(tmp_path):
    conn = ConnectionConfig(
        "agy_cli", "agy", protocol="cli_subprocess",
        model_id="gemini-3.8-flash-high", command="agy", cwd=str(tmp_path),
    )
    called: list[str] = []

    class Process:
        returncode = 0
        stderr = None

        class Stdout:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        stdout = Stdout()

        async def wait(self):
            return 0

    async def spawn(*args, **_kwargs):
        called.extend(args)
        return Process()

    with patch("asyncio.create_subprocess_exec", new=spawn):
        asyncio.run(CliSubprocessAdapter(conn).complete([{"role": "user", "content": "test"}]))

    assert called[:4] == [
        "agy", "--dangerously-skip-permissions", "--model", "gemini-3.8-flash-high",
    ]
    assert called[4:] == ["--print", "test"]


def test_cli_bridge_drains_stderr_before_wait(tmp_path):
    conn = ConnectionConfig(
        "opencode_cli", "opencode", protocol="cli_subprocess",
        model_id="opencode/big-pickle", command="opencode", cwd=str(tmp_path),
    )
    stderr_drained = asyncio.Event()

    class Stream:
        def __init__(self, values, done=None):
            self.values = iter(values)
            self.done = done

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.values)
            except StopIteration:
                if self.done:
                    self.done.set()
                raise StopAsyncIteration

    class Process:
        returncode = 0
        stdout = Stream([b"OK\n"])
        stderr = Stream([b"diagnostic\n"], stderr_drained)

        async def wait(self):
            await asyncio.wait_for(stderr_drained.wait(), timeout=1)
            return 0

    async def spawn(*_args, **_kwargs):
        return Process()

    with patch("asyncio.create_subprocess_exec", new=spawn):
        response = asyncio.run(
            CliSubprocessAdapter(conn).complete([{"role": "user", "content": "test"}])
        )

    assert response.message.text == "OK"


def test_cli_bridge_cancellation_terminates_process(tmp_path):
    conn = ConnectionConfig(
        "opencode_cli", "opencode", protocol="cli_subprocess",
        model_id="opencode/big-pickle", command="opencode", cwd=str(tmp_path),
    )

    class BlockingStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.Future()

    class Process:
        returncode = None
        stdout = BlockingStream()
        stderr = BlockingStream()
        terminated = False

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    process = Process()

    async def spawn(*_args, **_kwargs):
        return process

    async def run():
        with patch("asyncio.create_subprocess_exec", new=spawn):
            task = asyncio.create_task(
                CliSubprocessAdapter(conn).complete([{"role": "user", "content": "test"}])
            )
            await asyncio.sleep(0)
            task.cancel()
    asyncio.run(run())
    assert process.terminated


def test_choose_menu_esc_cancels():
    from talo.cli.connection_wizard import _choose_menu

    rows = [("1", "First", "First option"), ("0", "취소", "돌아갑니다")]
    with patch("builtins.input", return_value="esc"):
        res = _choose_menu("테스트", rows, "선택: ")
    assert res == "0"


def test_model_picker_esc_goes_back_to_category(tmp_path):
    cfg = Config(path=tmp_path / "config.toml")
    conn = ConnectionConfig("deepseek_1", "deepseek", model_id="deepseek-chat")
    cfg.set_connection(conn)

    # 1st input: "3" (DeepSeek category)
    # 2nd input: "esc" (goes back to category menu!)
    # 3rd input: "esc" (exits model picker!)
    with patch("builtins.input", side_effect=["3", "esc", "esc"]):
        picked = run_model_picker(cfg)

    assert picked is None


def test_skills_run_and_info_interactive(tmp_path):
    from unittest.mock import MagicMock
    from talo.cli.interactive import _handle_slash_interactive
    from talo.skills.loader import SkillLoader

    ctx = MagicMock()
    ctx.skill_loader = SkillLoader(tmp_path, None)

    # 1. /skills info fix_error
    res_info = _handle_slash_interactive(ctx, "ses_test", "/skills info fix_error")
    assert res_info is None

    # 2. /skills run fix_error
    res_run = _handle_slash_interactive(ctx, "ses_test", "/skills run fix_error")
    assert isinstance(res_run, dict)
    assert "run_request" in res_run
    assert "fix_error" in res_run["run_request"]


def test_choose_menu_cancel_key_with_agent_keyword():
    from talo.cli.connection_wizard import _choose_menu

    # Korean "에이전트" contains "이전" as a substring.
    # It must NOT be treated as a cancel row!
    rows = [
        ("hermes-agent", "hermes-agent", "Hermes 에이전트 확장 및 오케스트레이션"),
        ("0", "취소", "이전으로 돌아갑니다"),
    ]
    with patch("builtins.input", return_value="esc"):
        res = _choose_menu("스킬 선택", rows, "선택: ")
    assert res == "0"


def test_skills_pick_cancels(tmp_path):
    from unittest.mock import MagicMock
    from talo.cli.interactive import _handle_slash_interactive
    from talo.skills.loader import SkillLoader

    ctx = MagicMock()
    ctx.skill_loader = SkillLoader(tmp_path, None)

    with patch("builtins.input", return_value="0"):
        res = _handle_slash_interactive(ctx, "ses_test", "/skills pick")
    assert res is None

