"""자격 증명 참조 해석과 연결 선택.

credential_ref 형식:
  env:NAME      -> 환경변수에서 읽기
  keychain:ACCT -> macOS Keychain (security CLI), 불가 시 안내
비밀값은 설정·세션·로그에 기록하지 않는다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from talo.config import Config, ConnectionConfig


@dataclass
class ResolvedConnection:
    connection: ConnectionConfig
    credentials: dict[str, str]
    warnings: list[str]


class CredentialStore:
    def resolve(self, credential_ref: str) -> str | None:
        if credential_ref.startswith("env:"):
            return os.environ.get(credential_ref[4:])
        if credential_ref.startswith("keychain:"):
            return self._keychain_get(credential_ref[9:])
        return None

    def _keychain_get(self, account: str) -> str | None:
        if shutil.which("security") is None:
            return None
        proc = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", "talo", "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
        return None

    def store(self, credential_ref: str, secret: str) -> tuple[bool, str]:
        """키체인 저장. 실패하면 환경변수 안내."""
        if credential_ref.startswith("keychain:"):
            account = credential_ref[9:]
            if shutil.which("security") is None:
                return False, "security CLI 없음. env: 방식으로 설정하세요."
            proc = subprocess.run(
                ["security", "add-generic-password", "-a", account, "-s", "talo", "-w", secret, "-U"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                return True, "macOS Keychain에 저장됨"
            return False, proc.stderr.strip() or "Keychain 저장 실패"
        return False, "이 참조 방식은 저장을 지원하지 않음. 환경변수로 설정하세요."


class ConnectionResolver:
    def __init__(self, config: Config, credential_store: CredentialStore | None = None):
        self.config = config
        self.credentials_store = credential_store or CredentialStore()

    def resolve(self, connection: ConnectionConfig | None) -> ResolvedConnection | None:
        if connection is None:
            return None
        warnings: list[str] = []
        creds: dict[str, str] = {}
        if connection.protocol == "cli_subprocess":
            creds["oauth"] = "local_cli"
            creds["api_key"] = "cli_oauth"
            return ResolvedConnection(connection, creds, warnings)
        secret = self.credentials_store.resolve(connection.credential_ref)
        if secret:
            creds["api_key"] = secret
        else:
            warnings.append(f"자격 증명을 찾지 못함: {connection.credential_ref}")
        return ResolvedConnection(connection, creds, warnings)

    def available_connections(self) -> list[ConnectionConfig]:
        return list(self.config.connections.values())

    def active(self) -> ResolvedConnection | None:
        return self.resolve(self.config.active_connection())

    def by_id(self, connection_id: str) -> ResolvedConnection | None:
        return self.resolve(self.config.connection(connection_id))

    async def validate(self, connection: ConnectionConfig) -> tuple[bool, str]:
        resolved = self.resolve(connection)
        if resolved is None:
            return False, "연결 정보 없음"
        if connection.protocol == "cli_subprocess":
            from talo.providers.cli_subprocess import CliSubprocessAdapter

            adapter = CliSubprocessAdapter(connection, resolved.credentials)
            return await adapter.validate()
        if not resolved.credentials.get("api_key"):
            return False, f"자격 증명 없음: {connection.credential_ref}"
        from talo.providers.openai_compat import OpenAICompatAdapter

        adapter = OpenAICompatAdapter(connection, resolved.credentials)
        return await adapter.validate()
