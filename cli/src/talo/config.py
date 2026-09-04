"""개인 설정 로드/저장.

~/.talo/config.toml 에 비밀값 없이 연결 참조만 저장한다.
환경변수는 명시적인 자격 증명 공급원이며 저장된 모델 선택을 조용히 덮어쓰지 않는다.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from talo.paths import config_path

DEFAULT_CONFIG: dict[str, Any] = {
    "default_model": None,
    "default_mode": "dev",
    "default_permission": "project_edit",
    "connections": {},
    "max_iterations": 50,
    "context_input_ratio": 0.75,
    "exclude_paths": [".git", "node_modules", ".venv", "__pycache__", "dist", "build"],
}


@dataclass
class ConnectionConfig:
    connection_id: str
    provider_id: str
    protocol: str = "openai_compat"
    base_url: str = "https://openrouter.ai/api/v1"
    credential_ref: str = "env:TALO_API_KEY"
    model_id: str = ""
    command: str = ""
    cwd: str = ""
    capabilities: dict[str, str] = field(default_factory=dict)
    validated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "provider_id": self.provider_id,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "credential_ref": self.credential_ref,
            "model_id": self.model_id,
            "command": self.command,
            "cwd": self.cwd,
            "capabilities": self.capabilities,
            "validated_at": self.validated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConnectionConfig":
        return cls(**data)


class Config:
    def __init__(self, data: dict[str, Any] | None = None, path: Path | None = None):
        self.path = path or config_path()
        merged = dict(DEFAULT_CONFIG)
        if data:
            merged.update(data)
        self._data = merged

    # -- 접근자 -------------------------------------------------------------
    @property
    def default_model(self) -> str | None:
        return self._data.get("default_model")

    @property
    def default_mode(self) -> str:
        return self._data.get("default_mode", "dev")

    @property
    def default_permission(self) -> str:
        return self._data.get("default_permission", "project_edit")

    @property
    def max_iterations(self) -> int:
        return int(self._data.get("max_iterations", 50))

    @property
    def context_input_ratio(self) -> float:
        return float(self._data.get("context_input_ratio", 0.75))

    @property
    def exclude_paths(self) -> list[str]:
        return list(self._data.get("exclude_paths", DEFAULT_CONFIG["exclude_paths"]))

    @property
    def connections(self) -> dict[str, ConnectionConfig]:
        raw = self._data.get("connections", {}) or {}
        out: dict[str, ConnectionConfig] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                conn = ConnectionConfig.from_dict(value)
                out[conn.connection_id or key] = conn
        return out

    def connection(self, connection_id: str | None) -> ConnectionConfig | None:
        if not connection_id:
            return None
        return self.connections.get(connection_id)

    def active_connection(self) -> ConnectionConfig | None:
        """현재 선택된 연결. default_model 이 connection_id:model_id 형식이거나 단순 모델명이면 일치 모델 탐색."""
        dm = self.default_model
        conns = list(self.connections.values())
        if not conns:
            return None
        if dm:
            if ":" in dm:
                conn_id, _model = dm.split(":", 1)
                if conn_id in self.connections:
                    return self.connections[conn_id]
            for conn in conns:
                if conn.model_id == dm:
                    return conn
            return conns[0]
        return conns[0]

    def selected_model_id(self, connection: ConnectionConfig | None = None) -> str | None:
        conn = connection or self.active_connection()
        if not conn:
            return None
        dm = self.default_model
        if dm and ":" in dm:
            conn_id, model = dm.split(":", 1)
            if conn_id == conn.connection_id:
                return model
        return conn.model_id or None

    # -- 저장 ---------------------------------------------------------------
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(_to_toml(self._data), encoding="utf-8")
        os.replace(tmp, self.path)

    def update(self, **kwargs: Any) -> None:
        self._data.update(kwargs)
        self.save()

    def set_connection(self, conn: ConnectionConfig) -> None:
        conns = dict(self._data.get("connections", {}) or {})
        conns[conn.connection_id] = conn.to_dict()
        self._data["connections"] = conns
        self.save()

    def set_default_model(self, target: str | None) -> None:
        self._data["default_model"] = target
        self.save()

    def remove_connection(self, connection_id: str) -> None:
        conns = dict(self._data.get("connections", {}) or {})
        conns.pop(connection_id, None)
        self._data["connections"] = conns
        if self.default_model and self.default_model.startswith(f"{connection_id}:"):
            self._data["default_model"] = None
        self.save()

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        p = path or config_path()
        if p.exists():
            try:
                with p.open("rb") as fh:
                    data = tomllib.load(fh)
                return cls(data, path=p)
            except (tomllib.TOMLDecodeError, OSError):
                return cls({}, path=p)
        return cls({}, path=p)


def _to_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in data.items():
        lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def _toml_value(value: Any) -> str:
    import json

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(str(k), ensure_ascii=False)} = {_toml_value(v)}" for k, v in value.items()) + "}"
    return json.dumps(str(value), ensure_ascii=False)
