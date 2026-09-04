"""OpenAI 호환 API 어댑터 (OpenRouter·호환 엔드포인트).

스트리밍 SSE를 파싱해 on_delta로 텍스트를 전달하고, 완성된 도구 호출과
사용량을 공통 메시지로 정규화한다.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from talo.providers.base import DeltaCallback, ModelAdapter, ModelResponse
from talo.schemas import ContentBlock, ContentBlockType, Message, ToolCall


class OpenAICompatAdapter(ModelAdapter):
    protocol = "openai_compat"

    def __init__(self, connection: Any, credentials: dict[str, str] | None = None):
        super().__init__(connection, credentials)
        self._client: httpx.AsyncClient | None = None
        self._cancelled = False

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0))
        return self._client

    async def validate(self) -> tuple[bool, str]:
        """최소 요청으로 연결 상태 확인."""
        api_key = self.credentials.get("api_key")
        if not api_key:
            return False, "API 키 없음"
        model = self.connection.model_id
        try:
            resp = await self.client.get(
                f"{self.connection.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 401:
                return False, "인증 실패 (401)"
            if resp.status_code >= 400:
                return False, f"연결 확인 실패 (HTTP {resp.status_code})"
            data = resp.json()
            ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
            if model and ids and model not in ids:
                return True, f"연결됨. 단, 모델 '{model}'은(는) 제공 목록에 없음 — 지원하지 않는 모델일 수 있음"
            return True, "연결됨"
        except httpx.HTTPError as exc:
            return False, f"네트워크 오류: {exc}"

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                       model: str | None = None, on_delta: DeltaCallback | None = None) -> ModelResponse:
        api_key = self.credentials.get("api_key")
        if not api_key:
            raise RuntimeError("API 키 없음")
        self._cancelled = False
        payload: dict[str, Any] = {
            "model": model or self.connection.model_id,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        text_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        finish_reason: str | None = None
        url = f"{self.connection.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        async with self.client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code == 401:
                raise RuntimeError("인증 실패 (401) — API 키를 확인하세요")
            if resp.status_code == 429:
                raise RuntimeError("한도 초과 또는 속도 제한 (429)")
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "replace")[:500]
                raise RuntimeError(f"모델 API 오류 (HTTP {resp.status_code}): {body}")
            async for line in resp.aiter_lines():
                if self._cancelled:
                    break
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta", {})
                    if delta.get("content"):
                        text_parts.append(delta["content"])
                        if on_delta is not None:
                            await on_delta(delta["content"])
                    for tc in delta.get("tool_calls", []) or []:
                        idx = tc.get("index", 0)
                        slot = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                if chunk.get("usage"):
                    usage = chunk["usage"]

        blocks: list[ContentBlock] = []
        text = "".join(text_parts)
        if text:
            blocks.append(ContentBlock(type=ContentBlockType.TEXT, text=text))
        for slot in sorted(tool_calls.values(), key=lambda s: s.get("id", "")):
            args: dict[str, Any] = {}
            if slot["arguments"]:
                try:
                    args = json.loads(slot["arguments"])
                except json.JSONDecodeError:
                    args = {"_raw": slot["arguments"]}
            blocks.append(
                ContentBlock(
                    type=ContentBlockType.TOOL_CALL,
                    tool_call=ToolCall(call_id=slot.get("id") or f"call_{len(blocks)}",
                                       name=slot["name"], arguments=args,
                                       provider_call_id=slot.get("id")),
                )
            )
        message = Message(
            role="assistant",
            content_blocks=blocks,
            connection_id=self.connection.connection_id,
            model_id=model or self.connection.model_id,
        )
        return ModelResponse(message=message, usage=usage, finish_reason=finish_reason)

    def cancel(self) -> None:
        self._cancelled = True

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
