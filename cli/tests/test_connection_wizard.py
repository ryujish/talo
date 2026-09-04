"""Talo CLI 대화형 연결 마법사 및 자동 감지 단위 테스트."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from talo.cli.connection_wizard import (
    SERVICE_PRESETS,
    _finalize_connection,
    run_model_picker,
    scan_local_environment,
)
from talo.cli.main import build_parser
from talo.config import Config, ConnectionConfig
from talo.providers.resolver import CredentialStore


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

    deepseek = SERVICE_PRESETS["deepseek"]
    assert deepseek["base_url"] == "https://api.deepseek.com"
    assert "deepseek-chat" in deepseek["default_models"]

    think_along = SERVICE_PRESETS["think_along"]
    assert "mcp.flowpulse.ai.kr" in think_along["base_url"]
    assert think_along["default_key"] == "335d3b38936e1d6d137b71fb32d9e2f667bc6f194540a64cc6f161fff0f3116a"


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

    # 2번 선택 -> openai_1 로 변경
    with patch("builtins.input", return_value="2"):
        picked = run_model_picker(cfg)
        assert picked == "openai_1:gpt-4.1-mini"
        assert cfg.default_model == "openai_1:gpt-4.1-mini"
