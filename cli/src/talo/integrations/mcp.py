"""MCP 연결 관리 (초기 범위: 명시적으로 등록한 stdio 연결)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class McpConnection:
    connection_id: str
    command: str
    status: str = "registered"  # registered | connected | failed
    tools: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        return {"connection_id": self.connection_id, "command": self.command,
                "status": self.status, "tools": len(self.tools), "error": self.error}


class McpManager:
    """MCP 서버 연결 목록 관리. 실행은 명시적 허용 후 도구 레지스트리로 노출한다."""

    def __init__(self) -> None:
        self._connections: dict[str, McpConnection] = {}

    def register(self, connection_id: str, command: str) -> None:
        self._connections[connection_id] = McpConnection(connection_id=connection_id, command=command)

    def list(self) -> list[dict[str, Any]]:
        return [c.summary() for c in self._connections.values()]

    def get(self, connection_id: str) -> McpConnection | None:
        return self._connections.get(connection_id)
