"""도구 레지스트리: 스키마·처리기·가용성 등록."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from talo.schemas import ToolEffect
from talo.tools import builtin
from talo.tools.spec import ToolContext, ToolSpec

Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]


@dataclass
class RegisteredTool:
    spec: ToolSpec
    handler: Handler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: Handler) -> None:
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def list(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def describe(self, name: str) -> dict[str, Any] | None:
        tool = self._tools.get(name)
        if tool is None:
            return None
        s = tool.spec
        return {
            "name": s.name,
            "description": s.description,
            "effect": s.effect.value,
            "cancellable": s.cancellable,
            "retry_class": s.retry_class,
            "resource_scope": s.resource_scope,
            "availability": s.availability,
        }

    def available(self, names: set[str] | None = None) -> list[ToolSpec]:
        specs = [t.spec for t in self._tools.values() if t.spec.availability == "available"]
        if names is not None:
            specs = [s for s in specs if s.name in names]
        return specs

    def openai_tools(self, names: set[str] | None = None) -> list[dict[str, Any]]:
        return [s.openai_schema() for s in self.available(names)]


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()

    def obj_schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": "object", "properties": props}
        if required is not None:
            schema["required"] = required
        return schema

    str_prop = {"type": "string"}
    int_prop = {"type": "integer"}

    registry.register(
        ToolSpec("file_search", "프로젝트에서 패턴을 검색한다. rg 기반, 미설치 시 폴백.",
                 obj_schema({"pattern": str_prop, "path": str_prop, "max_results": int_prop}, ["pattern"]),
                 effect=ToolEffect.READ, retry_class="safe"),
        builtin.file_search,
    )
    registry.register(
        ToolSpec("file_list", "프로젝트 파일·폴더 목록을 본다.",
                 obj_schema({"path": str_prop, "depth": int_prop}), effect=ToolEffect.READ, retry_class="safe"),
        builtin.file_list,
    )
    registry.register(
        ToolSpec("file_read", "파일 일부를 읽는다. offset/limit 지원.",
                 obj_schema({"path": str_prop, "offset": int_prop, "limit": int_prop}, ["path"]),
                 effect=ToolEffect.READ, retry_class="safe"),
        builtin.file_read,
    )
    registry.register(
        ToolSpec("file_patch", "기대 해시를 확인한 뒤 파일의 유일한 텍스트를 치환한다.",
                 obj_schema({"path": str_prop, "old_text": str_prop, "new_text": str_prop, "expected_hash": str_prop},
                            ["path", "old_text", "new_text"]),
                 effect=ToolEffect.WRITE, retry_class="idempotent"),
        builtin.file_patch,
    )
    registry.register(
        ToolSpec("file_write", "프로젝트 파일을 생성하거나 덮어쓴다.",
                 obj_schema({"path": str_prop, "content": str_prop, "expected_hash": str_prop}, ["path", "content"]),
                 effect=ToolEffect.WRITE, retry_class="idempotent"),
        builtin.file_write,
    )
    registry.register(
        ToolSpec("document_write", "기획 문서(Markdown/텍스트)를 저장한다. 계획 모드에서 허용되는 문서 범위.",
                 obj_schema({"path": str_prop, "content": str_prop}, ["path", "content"]),
                 effect=ToolEffect.WRITE, retry_class="idempotent"),
        builtin.document_write,
    )
    registry.register(
        ToolSpec("git_status", "Git 상태(브랜치·HEAD·변경 파일)를 본다.",
                 obj_schema({}), effect=ToolEffect.READ, retry_class="safe"),
        builtin.git_status,
    )
    registry.register(
        ToolSpec("git_diff", "Git 변경 차이를 본다.", obj_schema({}), effect=ToolEffect.READ, retry_class="safe"),
        builtin.git_diff,
    )
    registry.register(
        ToolSpec("git_log", "최근 커밋을 본다.", obj_schema({"count": int_prop}), effect=ToolEffect.READ, retry_class="safe"),
        builtin.git_log,
    )
    registry.register(
        ToolSpec("command_run", "고정 작업 폴더에서 명령을 실행한다. stdout/stderr는 보관되고 요약이 반환된다.",
                 obj_schema({"command": str_prop, "cwd": str_prop, "timeout": {"type": "number"}}, ["command"]),
                 effect=ToolEffect.EXECUTE, cancellable=True, retry_class="unknown"),
        builtin.command_run,
    )
    registry.register(
        ToolSpec("command_status", "실행 중인 명령 상태를 확인한다.", obj_schema({}),
                 effect=ToolEffect.READ, retry_class="safe"),
        builtin.command_status,
    )
    registry.register(
        ToolSpec("memory_search", "프로젝트 기억을 검색한다.",
                 obj_schema({"query": str_prop, "limit": int_prop}, ["query"]), effect=ToolEffect.READ, retry_class="safe"),
        builtin.memory_search,
    )
    registry.register(
        ToolSpec("memory_propose", "기억(rule/decision/fact/work_note)을 제안 상태로 저장한다.",
                 obj_schema({"kind": str_prop, "content": str_prop}, ["kind", "content"]),
                 effect=ToolEffect.WRITE, retry_class="safe"),
        builtin.memory_propose,
    )
    registry.register(
        ToolSpec("memory_confirm", "제안된 프로젝트 기억을 사람이 검토할 확정 상태로 전환한다.",
                 obj_schema({"memory_id": str_prop}, ["memory_id"]),
                 effect=ToolEffect.WRITE, retry_class="idempotent"),
        builtin.memory_confirm,
    )
    registry.register(
        ToolSpec("memory_update", "프로젝트 기억 내용을 수정하고 버전을 올린다.",
                 obj_schema({"memory_id": str_prop, "content": str_prop}, ["memory_id", "content"]),
                 effect=ToolEffect.WRITE, retry_class="idempotent"),
        builtin.memory_update,
    )
    registry.register(
        ToolSpec("memory_retire", "더 이상 유효하지 않은 프로젝트 기억을 폐기 상태로 전환한다.",
                 obj_schema({"memory_id": str_prop}, ["memory_id"]),
                 effect=ToolEffect.WRITE, retry_class="idempotent"),
        builtin.memory_retire,
    )
    registry.register(
        ToolSpec("skill_list", "사용 가능한 스킬 목록을 본다.", obj_schema({}), effect=ToolEffect.READ, retry_class="safe"),
        builtin.skill_list,
    )
    registry.register(
        ToolSpec("skill_read", "스킬 본문을 읽는다.", obj_schema({"name": str_prop}, ["name"]),
                 effect=ToolEffect.READ, retry_class="safe"),
        builtin.skill_read,
    )
    return registry
