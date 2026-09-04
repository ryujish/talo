"""공통 계약: 종료 코드, 이벤트 유형, 실행 상태, 공통 메시지/도구 호출 모델.

기술 설계 15절의 JSONL 이벤트 필드와 종료 코드, 5절의 상태 머신을 코드화한다.
"""
from __future__ import annotations

import enum
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "0.1"


class ExitCode(enum.IntEnum):
    """기술 설계 15절 종료 코드 제안."""

    COMPLETED = 0          # 완료
    FAILED = 1             # 실패·부분 완료
    INPUT_ERROR = 2        # 입력·설정 오류
    APPROVAL_NEEDED = 3    # 승인 필요
    EXTERNAL_PAUSED = 4    # 외부 오류로 일시 중지
    INTERRUPTED = 130      # 사용자 중단


class RunState(str, enum.Enum):
    READY = "ready"
    PREPARING = "preparing"
    CALLING = "calling"
    CHECKING = "checking"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


class WorkMode(str, enum.Enum):
    PLAN = "plan"
    DEV = "dev"


class PermissionProfile(str, enum.Enum):
    READ_ONLY = "read_only"
    PROJECT_EDIT = "project_edit"
    DELEGATED = "delegated"


class ToolEffect(str, enum.Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    EXTERNAL = "external"


class EventType(str, enum.Enum):
    RUN_STARTED = "run.started"
    MESSAGE_DELTA = "message.delta"
    MESSAGE_COMPLETED = "message.completed"
    TOOL_PREPARED = "tool.prepared"
    APPROVAL_REQUIRED = "approval.required"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    WORKSPACE_CHANGED = "workspace.changed"
    CONTEXT_COMPACTED = "context.compacted"
    MODEL_SWITCH_REQUESTED = "model.switch_requested"
    MODEL_SWITCHED = "model.switched"
    VERIFICATION_RECORDED = "verification.recorded"
    RUN_PAUSED = "run.paused"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


class ContentBlockType(str, enum.Enum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ARTIFACT_REF = "artifact_ref"


class Role(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    call_id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    provider_call_id: str | None = None


class ToolResult(BaseModel):
    call_id: str
    status: Literal["success", "error", "unknown"] = "success"
    output_ref: str | None = None
    short_summary: str = ""
    error_code: str | None = None
    output: Any = None


class ContentBlock(BaseModel):
    type: ContentBlockType
    text: str | None = None
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    artifact_ref: str | None = None


class Message(BaseModel):
    id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    role: Role
    created_at: float = Field(default_factory=time.time)
    content_blocks: list[ContentBlock] = Field(default_factory=list)
    source: str = "model"
    connection_id: str | None = None
    model_id: str | None = None
    status: str = "complete"
    provider_sidecar: dict[str, Any] = Field(default_factory=dict)

    @property
    def text(self) -> str:
        return "".join(b.text or "" for b in self.content_blocks if b.type == ContentBlockType.TEXT)

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [b.tool_call for b in self.content_blocks if b.type == ContentBlockType.TOOL_CALL and b.tool_call]

    def as_openai_message(self) -> dict[str, Any]:
        """OpenAI 호환 표현으로 변환. 공급자 전용 항목은 제외한다."""
        content: list[Any] = []
        tool_calls: list[Any] = []
        for block in self.content_blocks:
            if block.type == ContentBlockType.TEXT and block.text:
                content.append({"type": "text", "text": block.text})
            elif block.type == ContentBlockType.TOOL_CALL and block.tool_call:
                tc = block.tool_call
                tool_calls.append(
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": _json_dumps(tc.arguments)},
                    }
                )
            elif block.type == ContentBlockType.TOOL_RESULT and block.tool_result:
                tr = block.tool_result
                content.append(
                    {"type": "tool_result", "tool_use_id": tr.call_id, "content": _json_dumps(tr.output)}
                )
            elif block.type == ContentBlockType.ARTIFACT_REF and block.artifact_ref:
                content.append({"type": "text", "text": f"[artifact:{block.artifact_ref}]"})
        if tool_calls:
            return {"role": "assistant", "content": content or None, "tool_calls": tool_calls}
        if content:
            return {"role": self.role.value, "content": content}
        return {"role": self.role.value, "content": self.text or ""}


def _json_dumps(obj: Any) -> str:
    import json

    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False)


class ToolResultMessage(Message):
    """도구 결과를 표현하는 메시지."""


class RunConfig(BaseModel):
    """기술 설계 5절: 반복·시간 예산. 50은 검증 전 제안값."""

    max_iterations: int = 50
    timeout_seconds: float = 900.0
    context_input_ratio: float = 0.75


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex}"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
