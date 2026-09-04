"""컨텍스트 엔진: 프롬프트 구성, 입력 예산, 축약, 인계.

원본 보존이 기본이며 축약 시 생략 항목과 근거를 반환한다.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from talo.schemas import Message, ToolResult


def estimate_tokens(text: str) -> int:
    """확정 수치가 아닌 추정 토큰. 한글은 음절 단위로 보수적으로 센다."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\uac00" <= ch <= "\ud7a3" or "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    other_tokens = other // 4 if other else 0
    return cjk + other_tokens


def hash_blocks(blocks: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(blocks, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


@dataclass
class ContextBlock:
    name: str
    content: str
    source: str = ""
    version: int = 1


@dataclass
class AssembledContext:
    blocks: list[ContextBlock]
    messages: list[dict[str, Any]]
    estimated_tokens: int
    omitted: list[dict[str, Any]] = field(default_factory=list)
    block_hashes: dict[str, str] = field(default_factory=dict)


class ContextEngine:
    def __init__(self, input_limit: int | None = None, output_reserve: int = 2048,
                 safety_margin: int = 1024, tool_schema_tokens: int = 2048,
                 compact_ratio: float = 0.75):
        self.input_limit = input_limit
        self.output_reserve = output_reserve
        self.safety_margin = safety_margin
        self.tool_schema_tokens = tool_schema_tokens
        self.compact_ratio = compact_ratio
        self.context_version = 1

    def budget(self) -> int | None:
        if self.input_limit is None:
            return None
        usable = self.input_limit - self.output_reserve - self.tool_schema_tokens - self.safety_margin
        return max(1, int(usable * self.compact_ratio))

    def assemble(self, blocks: list[ContextBlock], messages: list[dict[str, Any]],
                 handoff: dict[str, Any] | None = None) -> AssembledContext:
        """블록별 해시·출처를 관리하며 프롬프트를 구성한다."""
        estimated = sum(estimate_tokens(b.content) for b in blocks)
        block_hashes = {b.name: hash_blocks([{"content": b.content, "source": b.source}]) for b in blocks}
        return AssembledContext(blocks=blocks, messages=messages, estimated_tokens=estimated,
                                block_hashes=block_hashes)

    def openai_messages(self, blocks: list[ContextBlock], messages: list[dict[str, Any]],
                        tool_results: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        system_parts = [f"# {b.name}\n{b.content}" for b in blocks]
        out: list[dict[str, Any]] = []
        if system_parts:
            out.append({"role": "system", "content": "\n\n".join(system_parts)})
        out.extend(messages)
        for tr in tool_results or []:
            out.append({"role": "tool", "tool_call_id": tr["call_id"], "content": json.dumps(tr["output"], ensure_ascii=False)})
        return out

    def compact(self, messages: list[dict[str, Any]], tool_results: list[dict[str, Any]],
                max_messages: int = 20) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        """긴 대화 축약: 최근 쌍 보존, 오래된 내용은 요약 블록으로 대체. 원본은 DB에 보존된다."""
        if len(messages) <= max_messages:
            return messages, [], ""
        keep = messages[-max_messages:]
        dropped = messages[:-max_messages]
        summary = (
            f"이전 대화 {len(dropped)}개 메시지 요약: "
            + " ".join(_message_preview(m) for m in dropped[-6:])
        )
        kept_with_summary = [{"role": "system", "content": f"[이전 대화 요약]\n{summary}"}, *keep]
        self.context_version += 1
        return kept_with_summary, dropped, summary

    def handoff_document(self, *, identity: dict[str, Any], goal: str, constraints: dict[str, Any],
                         decisions: list[dict[str, Any]], workspace: dict[str, Any],
                         execution: list[dict[str, Any]], verification: list[dict[str, Any]],
                         next_actions: list[str], context_sources: list[str],
                         previous_handoff_id: str | None = None) -> dict[str, Any]:
        """기술 설계 8.3절 인계 데이터 필드."""
        self.context_version += 1
        return {
            "schema": "talo.handoff/0.1",
            "identity": identity,
            "goal": goal,
            "constraints": constraints,
            "decisions": decisions,
            "workspace": workspace,
            "execution": execution,
            "verification": verification,
            "next_actions": next_actions,
            "context_sources": context_sources,
            "context_version": self.context_version,
            "previous_handoff_id": previous_handoff_id,
            "generated_at": time.time(),
        }

    def cache_key(self, *, connection_id: str, model_id: str, guideline_hash: str,
                  tool_schema_hash: str, memory_version: int, file_state_hash: str) -> str:
        raw = "|".join([connection_id, model_id, guideline_hash, tool_schema_hash,
                        str(memory_version), file_state_hash])
        return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _message_preview(msg: dict[str, Any]) -> str:
    role = msg.get("role", "?")
    content = msg.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    else:
        text = str(content)
    return f"[{role}] {text[:200]}"
