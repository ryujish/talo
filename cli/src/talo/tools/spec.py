"""도구 스펙과 실행 컨텍스트."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from talo.schemas import ToolEffect


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    effect: ToolEffect = ToolEffect.READ
    cancellable: bool = True
    retry_class: str = "safe"  # safe | idempotent | unknown
    resource_scope: str = "project"
    availability: str = "available"

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


@dataclass
class ToolContext:
    """도구 실행에 필요한 의존성 묶음."""

    repo_root: Path
    workdir: Path
    project_id: str
    session_id: str
    run_id: str
    artifacts_dir: Path
    policy: Any = None
    repository: Any = None
    skill_loader: Any = None
    on_approval: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None
    large_output_threshold: int = 16_000
    exclude_paths: list[str] = field(default_factory=list)
    workspace: Any = None
    workspace_id: str = ""
    on_change_review: Callable[[str, dict[str, Any]], Awaitable[bool | str]] | None = None

    def is_path_allowed(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        root = self.repo_root.resolve()
        return resolved == root or root in resolved.parents

    def resolve_path(self, rel: str, *, allow_external: bool = False) -> Path:
        p = Path(rel).expanduser()
        candidate = p.resolve() if p.is_absolute() else (self.repo_root / p).resolve()
        if not self.is_path_allowed(candidate):
            if allow_external and candidate.exists():
                return candidate
            raise PermissionError(f"프로젝트 범위를 벗어난 경로: {rel}")
        return candidate


def input_hash(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(arguments, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
