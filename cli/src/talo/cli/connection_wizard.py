"""Talo CLI 대화형 연결·설정 마법사 (Talo_CLI_Connection_UI_Plan_v0.1 구현).

S01. 사용할 연결이 없음 (첫 안내)
S03. 서비스 선택 (검증된 프리셋 자동 설정)
S04. 기존 연결 찾기 (로컬 환경변수·도구 자동 감지)
S06. API 키 입력 (마스킹, macOS 보안 저장소/키체인 기본값)
S08. 연결 확인 (인증·모델 조회 라이브 프로브)
S09. 모델 선택 (검색창 및 번호 선택)
S10. 완료 (저장 및 즉시 활성화 원스톱 완료)
S12. /model (대화 중 및 CLI 모델 전환)
S13. talo connect (연결 목록·관리 대화형 메뉴)
"""
from __future__ import annotations

import asyncio
import getpass
import os
import shutil
from pathlib import Path
from typing import Any

import httpx

from talo.cli import render
from talo.config import Config, ConnectionConfig
from talo.providers.resolver import CredentialStore
from talo.schemas import ExitCode

# --------------------------------------------------------------------------
# 서비스 프리셋 정의 (Base URL 및 기본 추천 모델 카탈로그)
# --------------------------------------------------------------------------
SERVICE_PRESETS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "label": "DeepSeek",
        "description": "API 키로 연결 (api.deepseek.com)",
        "base_url": "https://api.deepseek.com",
        "default_models": ["deepseek-chat", "deepseek-reasoner"],
        "env_names": ["DEEPSEEK_API_KEY", "API_KEY"],
        "key_hint": "DeepSeek API 키 (sk-...)",
    },
    "openrouter": {
        "label": "OpenRouter",
        "description": "다양한 모델 통합 허브 (openrouter.ai)",
        "base_url": "https://openrouter.ai/api/v1",
        "default_models": [
            "anthropic/claude-3.7-sonnet",
            "deepseek/deepseek-r1",
            "google/gemini-2.5-flash",
            "meta-llama/llama-3.3-70b-instruct",
        ],
        "env_names": ["TALO_API_KEY", "OPENROUTER_API_KEY"],
        "key_hint": "OpenRouter API 키 (sk-or-...)",
    },
    "openai": {
        "label": "OpenAI API",
        "description": "공식 OpenAI API 키로 연결 (api.openai.com)",
        "base_url": "https://api.openai.com/v1",
        "default_models": ["gpt-4.1-mini", "gpt-4o", "o3-mini"],
        "env_names": ["OPENAI_API_KEY"],
        "key_hint": "OpenAI API 키 (sk-...)",
    },
    "gemini": {
        "label": "Google Gemini",
        "description": "Google AI Studio API (OpenAI 호환 엔드포인트)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_models": ["gemini-2.5-flash", "gemini-3.8-flash-high"],
        "env_names": ["GEMINI_API_KEY"],
        "key_hint": "Google Gemini API 키 (AIza...)",
    },
    "anthropic": {
        "label": "Anthropic API",
        "description": "Anthropic Claude API (호환 엔드포인트 또는 프록시)",
        "base_url": "https://api.anthropic.com/v1",
        "default_models": ["claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022"],
        "env_names": ["ANTHROPIC_API_KEY"],
        "key_hint": "Anthropic API 키 (sk-ant-...)",
    },
    "codex_cli": {
        "label": "Codex CLI (OAuth)",
        "description": "로컬 Codex CLI의 ChatGPT 로그인 세션 사용 (API 키 불필요)",
        "base_url": "",
        "default_models": ["gpt-5.6-sol"],
        "env_names": [],
        "key_hint": "",
        "bridge": "cli_subprocess",
        "command": "codex",
    },
    "think_along": {
        "label": "Think Along Cloud MCP",
        "description": "공식 Think Along 서버 MCP 통합 연결",
        "base_url": "https://mcp.flowpulse.ai.kr/mcp",
        "default_models": ["flowpulse/thinking-router"],
        "env_names": ["THINK_ALONG_OAUTH_KEY"],
        "key_hint": "OAuth 승인 키 (335d3b38...)",
        "default_key": "335d3b38936e1d6d137b71fb32d9e2f667bc6f194540a64cc6f161fff0f3116a",
    },
    "custom": {
        "label": "직접 설정",
        "description": "사용자 지정 OpenAI 호환 서버 주소 입력",
        "base_url": "",
        "default_models": [],
        "env_names": [],
        "key_hint": "API 키 또는 토큰",
    },
}


# --------------------------------------------------------------------------
# S01. 첫 실행 화면 (사용할 연결이 없음)
# --------------------------------------------------------------------------
def run_first_time_guide(config: Config, store: CredentialStore) -> bool:
    """사용 가능한 연결이 없을 때 첫 안내 화면.

    연결 성공 시 True, 나중에 하기 선택 시 False 반환.
    """
    render.console.print("\n[bold cyan]Talo에 사용할 AI를 연결하세요.[/bold cyan]")
    render.console.print("연결하면 이 프로젝트에서 바로 작업할 수 있습니다.\n")

    options = [
        ("1", "AI 연결하기", "새 AI 서비스(DeepSeek, OpenRouter 등)를 연결합니다"),
        ("2", "기존 연결 찾기", "로컬 환경변수나 설치된 도구 설정을 자동 감지합니다"),
        ("3", "나중에 하기", "연결 없이 기본 도움말 화면으로 이동합니다"),
    ]

    for key, title, desc in options:
        render.console.print(f"  [{key}] [bold]{title}[/bold] — {desc}")

    try:
        choice = input("\n선택 (1/2/3) [1]: ").strip() or "1"
    except (KeyboardInterrupt, EOFError):
        render.console.print("\n[dim]설정이 취소되었습니다.[/dim]")
        return False

    if choice == "2":
        return run_existing_discovery(config, store)
    if choice == "3":
        render.console.print("[dim]나중에 `talo connect` 또는 `talo setup`으로 연결할 수 있습니다.[/dim]")
        return False
    return run_service_picker(config, store)


# --------------------------------------------------------------------------
# S04. 기존 설정 활용 및 자동 감지 (Auto-Discovery Engine)
# --------------------------------------------------------------------------
def scan_local_environment() -> list[dict[str, Any]]:
    """로컬 머신의 환경변수, 설정 파일, 설치된 도구를 스캔."""
    discovered: list[dict[str, Any]] = []

    # 1. DeepCode / DeepSeek 환경변수 세트
    base_url = os.environ.get("BASE_URL")
    model = os.environ.get("MODEL")
    api_key = os.environ.get("API_KEY")
    if base_url and api_key:
        discovered.append({
            "type": "env_pair",
            "provider": "deepcode",
            "title": f"DeepCode / DeepSeek ($BASE_URL={base_url})",
            "base_url": base_url,
            "model": model or "deepseek-v4-pro",
            "credential_ref": "env:API_KEY",
            "has_secret": True,
            "secret": api_key,
            "desc": f"환경변수 $BASE_URL 및 모델 '{model or 'deepseek-v4-pro'}' 감지됨",
        })

    # 2. 명확한 공급자별 API 키 환경변수
    env_provider_map = [
        ("DEEPSEEK_API_KEY", "deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-chat"),
        ("OPENAI_API_KEY", "openai", "OpenAI", "https://api.openai.com/v1", "gpt-4.1-mini"),
        ("GEMINI_API_KEY", "gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
        ("ANTHROPIC_API_KEY", "anthropic", "Anthropic", "https://api.anthropic.com/v1", "claude-3-7-sonnet-20250219"),
        ("TALO_API_KEY", "openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "anthropic/claude-3.7-sonnet"),
    ]
    for env_name, prov_id, label, default_url, default_model in env_provider_map:
        val = os.environ.get(env_name)
        if val:
            discovered.append({
                "type": "env_key",
                "provider": prov_id,
                "title": f"{label} (${env_name})",
                "base_url": default_url,
                "model": default_model,
                "credential_ref": f"env:{env_name}",
                "has_secret": True,
                "secret": val,
                "desc": f"환경변수 ${env_name} 발견됨 (키 등록 생략 가능)",
            })

    # 3. 로컬 도구 파일 감지 (Codex, OpenCode, Hermes)
    codex_auth = Path.home() / ".codex" / "auth.json"
    if codex_auth.exists() and shutil.which("codex"):
        discovered.append({
            "type": "cli_bridge",
            "provider": "codex_cli",
            "title": "Codex CLI (ChatGPT Plus/OAuth 세션)",
            "base_url": "",
            "model": "gpt-5.6-sol",
            "credential_ref": "",
            "has_secret": True,
            "secret": "cli_oauth",
            "desc": "~/.codex/auth.json OAuth 세션 감지됨 (API 키 없이 ChatGPT Plus/Team으로 즉시 연결)",
            "supported": True,
        })
    elif codex_auth.exists():
        discovered.append({
            "type": "tool_install",
            "provider": "codex",
            "title": "Codex CLI (~/.codex/auth.json)",
            "desc": "설치됨 (Codex 실행 파일 확인 필요)",
            "supported": False,
        })

    opencode_auth = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    if opencode_auth.exists():
        discovered.append({
            "type": "tool_install",
            "provider": "opencode",
            "title": "OpenCode (~/.local/share/opencode)",
            "desc": "설치됨 (auth.json 공급자 키 관리 중)",
            "supported": False,
        })

    # 4. 로컬 LLM 서버 (Ollama, LM Studio)
    # 비차단 포트 핑은 생략하거나 환경변수로 식별
    if os.environ.get("OLLAMA_HOST"):
        discovered.append({
            "type": "local_llm",
            "provider": "ollama",
            "title": "Ollama (로컬 서버)",
            "base_url": os.environ.get("OLLAMA_HOST", "http://localhost:11434/v1"),
            "model": "llama3.1",
            "credential_ref": "env:OLLAMA_KEY",
            "has_secret": False,
            "desc": "Ollama 로컬 서버 환경변수 감지됨",
        })

    return discovered


def run_existing_discovery(config: Config, store: CredentialStore) -> bool:
    """S04. 기존 연결 찾기 화면."""
    render.console.print("\n[bold cyan]기존 연결 및 로컬 환경 스캔[/bold cyan]")
    discovered = scan_local_environment()

    if not discovered:
        render.console.print("[yellow]감지된 로컬 AI 설정이나 도구가 없습니다.[/yellow]")
        render.console.print("새 AI 서비스를 직접 연결합니다.\n")
        return run_service_picker(config, store)

    render.console.print(f"{len(discovered)}개의 연결 후보 및 로컬 도구를 발견했습니다:\n")
    for i, item in enumerate(discovered, 1):
        status_tag = "[green]즉시 사용 가능[/green]" if item.get("has_secret") else "[dim]안내[/dim]"
        render.console.print(f"  [{i}] [bold]{item['title']}[/bold] — {status_tag}")
        render.console.print(f"      {item['desc']}")

    render.console.print(f"  [{len(discovered) + 1}] 직접 새 AI 서비스 선택하기")
    render.console.print("  [0] 취소")

    try:
        raw = input(f"\n선택 (1~{len(discovered) + 1}, 0=취소) [1]: ").strip() or "1"
    except (KeyboardInterrupt, EOFError):
        return False

    if raw == "0":
        return False

    try:
        idx = int(raw) - 1
    except ValueError:
        return False

    if idx == len(discovered):
        return run_service_picker(config, store)

    if 0 <= idx < len(discovered):
        chosen = discovered[idx]
        if not chosen.get("has_secret"):
            render.console.print(f"\n[yellow]{chosen['title']}[/yellow]")
            render.console.print(f"{chosen['desc']}")
            render.console.print("이 도구는 현재 직접 API 키 등록을 통해서만 사용할 수 있습니다.")
            return run_service_picker(config, store)

        # 즉시 검증 및 연결
        render.console.print(f"\n[bold green]'{chosen['title']}' 연결을 진행합니다.[/bold green]")
        if chosen.get("provider") == "codex_cli" or chosen.get("type") == "cli_bridge":
            preset = SERVICE_PRESETS.get("codex_cli", {
                "label": "Codex CLI (OAuth)",
                "command": "codex",
                "default_models": ["gpt-5.6-sol", "gpt-4o", "o3-mini"],
            })
            return _finalize_cli_bridge_connection(config, "codex_cli", preset)

        return _finalize_connection(
            config=config,
            store=store,
            provider_id=chosen["provider"],
            base_url=chosen["base_url"],
            credential_ref=chosen["credential_ref"],
            secret=chosen.get("secret", ""),
            suggested_model=chosen.get("model", ""),
        )
    return False


# --------------------------------------------------------------------------
# S03. 서비스 선택 (검증된 프리셋 자동 설정)
# --------------------------------------------------------------------------
def run_service_picker(config: Config, store: CredentialStore) -> bool:
    """S03. 사용할 AI 서비스를 선택하는 화면."""
    render.console.print("\n[bold cyan]사용할 AI 서비스를 선택하세요.[/bold cyan]")
    render.console.print("검증된 서비스 프리셋으로 엔드포인트 주소가 자동 설정됩니다.\n")

    preset_keys = list(SERVICE_PRESETS.keys())
    for i, key in enumerate(preset_keys, 1):
        item = SERVICE_PRESETS[key]
        render.console.print(f"  [{i}] [bold]{item['label']}[/bold] — {item['description']}")

    render.console.print("  [0] 취소")

    try:
        raw = input(f"\n선택 (1~{len(preset_keys)}, 0=취소) [1]: ").strip() or "1"
    except (KeyboardInterrupt, EOFError):
        return False

    if raw == "0":
        return False

    try:
        idx = int(raw) - 1
    except ValueError:
        return False

    if not (0 <= idx < len(preset_keys)):
        render.console.print("[red]잘못된 선택입니다.[/red]")
        return False

    selected_key = preset_keys[idx]
    preset = SERVICE_PRESETS[selected_key]

    base_url = preset["base_url"]
    if selected_key == "custom":
        base_url = input("\n사용자 지정 Base URL (예: https://api.example.com/v1): ").strip()
        if not base_url:
            render.console.print("[red]Base URL이 필요합니다.[/red]")
            return False

    if preset.get("bridge") == "cli_subprocess":
        return _finalize_cli_bridge_connection(config, selected_key, preset)

    return _prompt_credentials_and_connect(config, store, selected_key, preset, base_url)


# --------------------------------------------------------------------------
# S06. API 키 입력 & 보안 저장소 (macOS Keychain)
# --------------------------------------------------------------------------
def _prompt_credentials_and_connect(
    config: Config,
    store: CredentialStore,
    provider_id: str,
    preset: dict[str, Any],
    base_url: str,
) -> bool:
    label = preset["label"]
    key_hint = preset["key_hint"]
    default_key = preset.get("default_key")

    render.console.print(f"\n[bold]{label} 연결 설정[/bold]")

    # Think Along 공식 MCP인 경우 기본 토큰 제공
    if default_key:
        render.console.print(f"공식 승인 토큰이 미리 준비되어 있습니다.")
        use_default = input(f"기본 토큰을 사용하시겠습니까? (Y/n): ").strip().lower()
        if use_default not in {"n", "no"}:
            return _finalize_connection(
                config=config,
                store=store,
                provider_id=provider_id,
                base_url=base_url,
                credential_ref="keychain:think_along_mcp",
                secret=default_key,
                suggested_model=preset["default_models"][0] if preset["default_models"] else "default",
            )

    # 환경변수에 이미 키가 있는지 우선 확인
    for env_name in preset.get("env_names", []):
        env_val = os.environ.get(env_name)
        if env_val:
            render.console.print(f"환경변수 [green]${env_name}[/green]에서 API 키를 발견했습니다.")
            use_env = input(f"이 환경변수(${env_name})를 사용하시겠습니까? (Y/n): ").strip().lower()
            if use_env not in {"n", "no"}:
                return _finalize_connection(
                    config=config,
                    store=store,
                    provider_id=provider_id,
                    base_url=base_url,
                    credential_ref=f"env:{env_name}",
                    secret=env_val,
                    suggested_model=preset["default_models"][0] if preset["default_models"] else "",
                )

    render.console.print(f"\n{key_hint}를 입력하거나 붙여넣으세요.")
    render.console.print("[dim]입력 내용은 마스킹되며, 이 Mac의 보안 저장소(Keychain)에 저장됩니다.[/dim]")

    try:
        secret = getpass.getpass("API 키: ").strip()
    except (KeyboardInterrupt, EOFError):
        return False

    if not secret:
        render.console.print("[red]API 키가 입력되지 않았습니다.[/red]")
        return False

    # 보안 저장소 (macOS Keychain) 저장 시도
    account_name = f"talo_{provider_id}"
    credential_ref = f"keychain:{account_name}"
    ok, msg = store.store(credential_ref, secret)
    if ok:
        render.console.print(f"[green]✓ macOS Keychain에 안전하게 저장되었습니다.[/green]")
    else:
        render.console.print(f"[yellow]키체인 저장 건너뜀 ({msg}). 환경변수 방식 또는 세션 보관을 사용합니다.[/yellow]")
        # 대안: 환경변수명 지정
        env_fallback = preset.get("env_names", ["TALO_API_KEY"])[0]
        credential_ref = f"env:{env_fallback}"
        render.console.print(f"참조: [dim]{credential_ref}[/dim]")

    return _finalize_connection(
        config=config,
        store=store,
        provider_id=provider_id,
        base_url=base_url,
        credential_ref=credential_ref,
        secret=secret,
        suggested_model=preset["default_models"][0] if preset["default_models"] else "",
    )


# --------------------------------------------------------------------------
# S08 & S09 & S10. 연결 검증, 모델 선택, 완료 및 즉시 활성화
# --------------------------------------------------------------------------
def _finalize_cli_bridge_connection(config: Config, provider_id: str, preset: dict[str, Any]) -> bool:
    """CLI 서브프로세스 브릿지 연결: API 키 없이 로컬 CLI OAuth 세션 사용."""
    command = preset.get("command", "codex")
    default_model = preset["default_models"][0] if preset.get("default_models") else ""
    try:
        model_id = input(f"모델 ID [{default_model}]: ").strip() or default_model
    except (KeyboardInterrupt, EOFError):
        return False
    if not model_id:
        model_id = "gpt-5.6-sol"

    from talo.providers.cli_subprocess import CliSubprocessAdapter

    probe = ConnectionConfig(connection_id="__probe__", provider_id=provider_id,
                             protocol="cli_subprocess", model_id=model_id, command=command,
                             base_url="", credential_ref="")
    ok, msg = asyncio.run(CliSubprocessAdapter(probe, {}).validate())
    if not ok:
        render.console.print(f"[red]✗ {msg}[/red]")
        return False
    render.console.print(f"[green]✓ {msg}[/green]")

    connection_id = f"{provider_id}_{model_id.split('/')[-1][:16]}"
    conn = ConnectionConfig(
        connection_id=connection_id,
        provider_id=provider_id,
        protocol="cli_subprocess",
        base_url="",
        credential_ref="",
        model_id=model_id,
        command=command,
        cwd=str(Path.cwd()),
        validated_at="just_now",
    )
    config.set_connection(conn)
    config.set_default_model(f"{conn.connection_id}:{model_id}")

    render.console.print("\n" + "═" * 56)
    render.console.print("[bold green]✓ 연결되었습니다.[/bold green]")
    render.console.print(f"  서비스:    [bold]{preset.get('label', provider_id)}[/bold]")
    render.console.print(f"  모델:      [bold cyan]{model_id}[/bold cyan]")
    render.console.print(f"  연결 ID:   {conn.connection_id}")
    render.console.print("  인증:      로컬 CLI OAuth 세션 사용 (API 키 불필요)")
    render.console.print("═" * 56 + "\n")
    return True


def _finalize_connection(
    config: Config,
    store: CredentialStore,
    provider_id: str,
    base_url: str,
    credential_ref: str,
    secret: str,
    suggested_model: str = "",
) -> bool:
    """S08 연결 확인, S09 모델 선택, S10 완료 및 즉시 활성화."""
    render.console.print("\n[bold]연결 정보를 확인하고 있습니다...[/bold]")

    fetched_models: list[str] = []
    # 1. 라이브 핑 및 모델 목록 조회 시도
    if base_url and secret and not base_url.startswith("https://mcp."):
        try:
            with httpx.Client(timeout=10.0) as client:
                models_url = f"{base_url.rstrip('/')}/models"
                resp = client.get(models_url, headers={"Authorization": f"Bearer {secret}"})
                if resp.status_code == 200:
                    data = resp.json()
                    raw_models = data.get("data", [])
                    if isinstance(raw_models, list):
                        for m in raw_models:
                            mid = m.get("id") if isinstance(m, dict) else str(m)
                            # openrouter/auto 등 자동 선택 모델 제외 (Section 10 원칙)
                            if mid and not mid.endswith("/auto"):
                                fetched_models.append(mid)
                    render.console.print(f"[green]✓ 인증 확인 성공[/green]")
                    if fetched_models:
                        render.console.print(f"[green]✓ {len(fetched_models)}개의 모델을 조회했습니다.[/green]")
                elif resp.status_code == 401:
                    render.console.print("[red]✗ 연결 정보(API 키)가 거절되었습니다 (401). 키를 다시 확인하세요.[/red]")
                    return False
                else:
                    render.console.print(f"[yellow]! 모델 목록 응답 (HTTP {resp.status_code}). 프리셋 카탈로그를 사용합니다.[/yellow]")
        except Exception as exc:  # noqa: BLE001
            render.console.print(f"[yellow]! 실시간 모델 조회 지연 ({exc}). 기본 프리셋 모델 목록으로 진행합니다.[/yellow]")

    # 2. S09. 모델 선택
    preset = SERVICE_PRESETS.get(provider_id, {})
    candidate_models: list[str] = []
    if fetched_models:
        # 최근 추천/인기 모델 또는 첫 10개
        candidate_models = fetched_models[:15]
    else:
        candidate_models = list(preset.get("default_models", []))

    if suggested_model and suggested_model not in candidate_models:
        candidate_models.insert(0, suggested_model)

    chosen_model = ""
    if candidate_models:
        render.console.print("\n[bold cyan]어떤 모델로 작업할까요?[/bold cyan]")
        for i, m in enumerate(candidate_models, 1):
            star = " (추천)" if i == 1 else ""
            render.console.print(f"  [{i}] {m}{star}")
        render.console.print(f"  [{len(candidate_models) + 1}] 모델 ID 직접 입력")

        try:
            m_choice = input(f"\n선택 (1~{len(candidate_models) + 1}) [1]: ").strip() or "1"
        except (KeyboardInterrupt, EOFError):
            return False

        try:
            m_idx = int(m_choice) - 1
            if 0 <= m_idx < len(candidate_models):
                chosen_model = candidate_models[m_idx]
            elif m_idx == len(candidate_models):
                chosen_model = input("모델 ID 직접 입력: ").strip()
        except ValueError:
            chosen_model = m_choice  # 사용자가 직접 모델명을 쳤을 경우

    if not chosen_model:
        chosen_model = suggested_model or (preset.get("default_models", ["default"])[0] if preset.get("default_models") else "default")

    # 3. ConnectionConfig 생성 및 저장
    safe_suffix = chosen_model.split("/")[-1][:16].replace(":", "_")
    connection_id = f"{provider_id}_{safe_suffix}"

    conn = ConnectionConfig(
        connection_id=connection_id,
        provider_id=provider_id,
        base_url=base_url,
        credential_ref=credential_ref,
        model_id=chosen_model,
        validated_at="just_now",
    )

    config.set_connection(conn)
    # 기본 모델 즉시 활성화 (validate/use 수동 실행 불필요 - Section 10 S10)
    config.set_default_model(f"{conn.connection_id}:{chosen_model}")

    # S10. 완료 메시지
    render.console.print("\n" + "═" * 56)
    render.console.print("[bold green]✓ 연결되었습니다.[/bold green]")
    render.console.print(f"  서비스:    [bold]{preset.get('label', provider_id)}[/bold]")
    render.console.print(f"  모델:      [bold cyan]{chosen_model}[/bold cyan]")
    render.console.print(f"  연결 ID:   {conn.connection_id}")
    render.console.print(f"  작업 상태: [green]코드 작업 사용 가능[/green]")
    render.console.print("═" * 56 + "\n")
    return True


# --------------------------------------------------------------------------
# S12. 대화 중 /model 및 CLI talo model (모델 선택 및 전환)
# --------------------------------------------------------------------------
def run_model_picker(config: Config) -> str | None:
    """등록된 연결 중 사용할 모델을 선택하고 기본 모델로 전환."""
    conns = list(config.connections.values())
    if not conns:
        render.console.print("[yellow]연결된 AI가 없습니다. `talo setup`으로 먼저 연결하세요.[/yellow]")
        return None

    active = config.default_model or ""
    active_conn_id = active.split(":")[0] if active else ""

    render.console.print("\n[bold cyan]사용할 모델을 선택하세요:[/bold cyan]\n")
    for i, c in enumerate(conns, 1):
        is_active = (c.connection_id == active_conn_id)
        marker = " [bold green]● (현재 사용 중)[/bold green]" if is_active else ""
        render.console.print(f"  [{i}] [bold]{c.connection_id}[/bold] ({c.model_id}){marker}")
        render.console.print(f"      공급자: {c.provider_id} · 엔드포인트: {c.base_url}")

    render.console.print(f"  [{len(conns) + 1}] 새 AI 연결 추가하기")
    render.console.print("  [0] 취소")

    try:
        raw = input(f"\n선택 (1~{len(conns) + 1}, 0=취소): ").strip()
    except (KeyboardInterrupt, EOFError):
        return None

    if not raw or raw == "0":
        return None

    try:
        idx = int(raw) - 1
    except ValueError:
        return None

    if idx == len(conns):
        store = CredentialStore()
        run_service_picker(config, store)
        return config.default_model

    if 0 <= idx < len(conns):
        selected_conn = conns[idx]
        target = f"{selected_conn.connection_id}:{selected_conn.model_id}"
        config.set_default_model(target)
        render.console.print(f"\n[green]✓ 기본 모델이 '{target}'(으)로 변경되었습니다.[/green]")
        return target
    return None


# --------------------------------------------------------------------------
# S13. talo connect 대화형 관리 메뉴
# --------------------------------------------------------------------------
def run_connect_interactive(config: Config, store: CredentialStore) -> int:
    """talo connect 를 인자 없이 실행했을 때의 대화형 관리 메뉴."""
    conns = list(config.connections.values())
    active = config.default_model or ""
    active_id = active.split(":")[0] if active else None

    render.console.print("\n[bold]Talo AI 연결 관리[/bold]")
    render.connections_table(conns, active_id)

    menu = [
        ("1", "새 AI 서비스 연결하기 (프리셋 마법사)"),
        ("2", "기존 로컬 연결 자동 감지"),
        ("3", "활성 모델 변경"),
        ("4", "연결 상태 전체 검증"),
        ("5", "연결 해제 (삭제)"),
        ("0", "나가기"),
    ]
    render.console.print("\n[bold cyan]수행할 작업을 선택하세요:[/bold cyan]")
    for k, title in menu:
        render.console.print(f"  [{k}] {title}")

    try:
        choice = input("\n선택 (0~5) [1]: ").strip() or "1"
    except (KeyboardInterrupt, EOFError):
        return int(ExitCode.COMPLETED)

    if choice == "1":
        run_service_picker(config, store)
    elif choice == "2":
        run_existing_discovery(config, store)
    elif choice == "3":
        run_model_picker(config)
    elif choice == "4":
        from talo.providers.resolver import ConnectionResolver
        resolver = ConnectionResolver(config, store)
        render.console.print("\n[bold]연결 상태 검증 중...[/bold]")
        for c in config.connections.values():
            ok, msg = asyncio.run(resolver.validate(c))
            mark = "green" if ok else "red"
            status = "정상 ●" if ok else "실패 ✗"
            render.console.print(f"  [{mark}]{c.connection_id}[/{mark}]: {status} ({msg})")
    elif choice == "5":
        if not conns:
            render.console.print("[yellow]해제할 연결이 없습니다.[/yellow]")
            return int(ExitCode.COMPLETED)
        render.console.print("\n[bold red]삭제할 연결 번호를 선택하세요:[/bold red]")
        for i, c in enumerate(conns, 1):
            render.console.print(f"  [{i}] {c.connection_id} ({c.model_id})")
        try:
            del_raw = input(f"삭제 번호 (1~{len(conns)}, Enter=취소): ").strip()
            if del_raw:
                del_idx = int(del_raw) - 1
                if 0 <= del_idx < len(conns):
                    target_id = conns[del_idx].connection_id
                    config.remove_connection(target_id)
                    render.console.print(f"[green]연결 해제됨: {target_id}[/green]")
        except (ValueError, KeyboardInterrupt, EOFError):
            pass
    return int(ExitCode.COMPLETED)
