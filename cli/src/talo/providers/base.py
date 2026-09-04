"""공급자·모델 어댑터 계약.

complete()는 on_delta 콜백으로 스트리밍 텍스트를 전달하고,
완성된 공통 Message·사용량을 반환한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from talo.schemas import ContentBlock, ContentBlockType, Message

DeltaCallback = Callable[[str], Awaitable[None]]


@dataclass
class ModelCapabilities:
    tool_calls: str = "unknown"     # true | false | unknown
    streaming: str = "unknown"
    images: str = "unknown"
    input_limit: int | None = None
    output_limit: int | None = None
    token_accounting: str = "unknown"

    def to_dict(self) -> dict[str, str]:
        return {
            "tool_calls": self.tool_calls,
            "streaming": self.streaming,
            "images": self.images,
            "input_limit": str(self.input_limit) if self.input_limit else "unknown",
            "output_limit": str(self.output_limit) if self.output_limit else "unknown",
            "token_accounting": self.token_accounting,
        }


@dataclass
class ModelResponse:
    message: Message
    usage: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class ModelAdapter:
    """공급자 결과를 공통 메시지·사용량으로 변환한다."""

    protocol = "openai_compat"

    def __init__(self, connection: Any, credentials: dict[str, str] | None = None):
        self.connection = connection
        self.credentials = credentials or {}

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities()

    async def validate(self) -> tuple[bool, str]:
        raise NotImplementedError

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                       model: str | None = None, on_delta: DeltaCallback | None = None) -> ModelResponse:
        raise NotImplementedError

    def cancel(self) -> None:
        pass

    async def aclose(self) -> None:
        pass


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
