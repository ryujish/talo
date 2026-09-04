"""모의 어댑터: 실제 API 없이 실행 루프·도구·이벤트를 검증하기 위한 공급자.

provider_id="mock" 연결 또는 TALO_PROVIDER=mock으로 사용한다.
응답 스크립트는 단계별로 텍스트 또는 도구 호출을 반환한다.
"""
from __future__ import annotations

from typing import Any

from talo.providers.base import DeltaCallback, ModelAdapter, ModelCapabilities, ModelResponse
from talo.schemas import ContentBlock, ContentBlockType, Message, ToolCall


class MockAdapter(ModelAdapter):
    protocol = "mock"

    def __init__(self, connection: Any, credentials: dict[str, str] | None = None,
                 script: list[dict[str, Any]] | None = None):
        super().__init__(connection, credentials)
        # script: [{"text": "..."} | {"tool": {"name":..., "arguments": {...}}}]
        self.script = script or [{"text": "모의 응답입니다. 실제 모델이 연결되지 않았습니다."}]

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tool_calls="true", streaming="true", token_accounting="false")

    async def validate(self) -> tuple[bool, str]:
        return True, "mock 연결은 항상 유효함"

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                       model: str | None = None, on_delta: DeltaCallback | None = None) -> ModelResponse:
        blocks: list[ContentBlock] = []
        for step in self.script:
            if "text" in step:
                blocks.append(ContentBlock(type=ContentBlockType.TEXT, text=step["text"]))
                if on_delta is not None:
                    await on_delta(step["text"])
            elif "tool" in step:
                t = step["tool"]
                blocks.append(
                    ContentBlock(
                        type=ContentBlockType.TOOL_CALL,
                        tool_call=ToolCall(call_id=f"mock_call_{len(blocks)}",
                                           name=t["name"], arguments=t.get("arguments", {})),
                    )
                )
        return ModelResponse(
            message=Message(role="assistant", content_blocks=blocks,
                            connection_id=self.connection.connection_id, model_id=model),
            usage={"source": "mock"},
            finish_reason="stop",
        )


class ScriptedMockAdapter(MockAdapter):
    """도구 호출 결과를 받은 뒤 이어지는 스크립트 단계를 소비하는 어댑터."""

    def __init__(self, connection: Any, credentials: dict[str, str] | None = None,
                 script: list[dict[str, Any]] | None = None):
        super().__init__(connection, credentials, script)
        self._cursor = 0

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                       model: str | None = None, on_delta: DeltaCallback | None = None) -> ModelResponse:
        if self._cursor >= len(self.script):
            text = "완료했습니다."
            if on_delta is not None:
                await on_delta(text)
            return ModelResponse(
                message=Message(role="assistant",
                                content_blocks=[ContentBlock(type=ContentBlockType.TEXT, text=text)],
                                connection_id=self.connection.connection_id, model_id=model),
                usage={"source": "mock"}, finish_reason="stop",
            )
        step = self.script[self._cursor]
        self._cursor += 1
        blocks: list[ContentBlock] = []
        has_tool = "tool" in step
        if "text" in step:
            blocks.append(ContentBlock(type=ContentBlockType.TEXT, text=step["text"]))
            if on_delta is not None:
                await on_delta(step["text"])
        elif has_tool:
            t = step["tool"]
            blocks.append(
                ContentBlock(
                    type=ContentBlockType.TOOL_CALL,
                    tool_call=ToolCall(call_id=f"mock_call_{self._cursor}", name=t["name"],
                                       arguments=t.get("arguments", {})),
                )
            )
        return ModelResponse(
            message=Message(role="assistant", content_blocks=blocks,
                            connection_id=self.connection.connection_id, model_id=model),
            usage={"source": "mock"}, finish_reason="tool_calls" if has_tool else "stop",
        )
