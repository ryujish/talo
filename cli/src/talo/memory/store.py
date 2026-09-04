"""기억 저장소: 범위·출처·상태·버전 관리.

MemoryRecord: ID, project_id, kind, content, status, source_refs, version, timestamps.
kind: rule/decision/fact/work_note, status: proposed/confirmed/superseded/retired.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from talo.storage.repository import Repository


@dataclass
class MemoryRecord:
    id: str
    project_id: str
    kind: str
    content: str
    status: str = "proposed"
    source_refs: list[str] = field(default_factory=list)
    version: int = 1
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "project_id": self.project_id, "kind": self.kind,
            "content": self.content, "status": self.status, "source_refs": self.source_refs,
            "version": self.version, "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Any) -> "MemoryRecord":
        return cls(
            id=row["id"], project_id=row["project_id"], kind=row["kind"], content=row["content"],
            status=row["status"], source_refs=json.loads(row["source_refs"] or "[]"),
            version=row["version"], created_at=row["created_at"], updated_at=row["updated_at"],
        )


class MemoryStore:
    def __init__(self, repository: Repository, project_id: str):
        self.repo = repository
        self.project_id = project_id
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    def bump(self) -> int:
        self._version += 1
        return self._version

    def recall(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        rows = self.repo.search_memories(self.project_id, query, limit)
        return [MemoryRecord.from_row(r) for r in rows]

    def propose(self, kind: str, content: str, source_refs: list[str] | None = None) -> MemoryRecord:
        mid = self.repo.upsert_memory(None, self.project_id, kind, "proposed", content, source_refs)
        row = self.repo.get_memory(mid)
        assert row is not None
        self.bump()
        return MemoryRecord.from_row(row)

    def confirm(self, memory_id: str) -> MemoryRecord:
        row = self.repo.get_memory(memory_id)
        if row is None or row["project_id"] != self.project_id:
            raise ValueError("프로젝트 범위의 기억이 아님")
        if row["status"] == "confirmed":
            return MemoryRecord.from_row(row)
        self.repo.upsert_memory(memory_id, self.project_id, row["kind"], "confirmed", row["content"])
        self.bump()
        return MemoryRecord.from_row(self.repo.get_memory(memory_id))

    def revise(self, memory_id: str, content: str) -> MemoryRecord:
        row = self.repo.get_memory(memory_id)
        if row is None or row["project_id"] != self.project_id:
            raise ValueError("프로젝트 범위의 기억이 아님")
        if row["content"] == content:
            return MemoryRecord.from_row(row)
        self.repo.upsert_memory(memory_id, self.project_id, row["kind"], row["status"], content)
        self.bump()
        return MemoryRecord.from_row(self.repo.get_memory(memory_id))

    def retire(self, memory_id: str) -> None:
        row = self.repo.get_memory(memory_id)
        if row is None or row["project_id"] != self.project_id:
            raise ValueError("프로젝트 범위의 기억이 아님")
        if row["status"] == "retired":
            return
        self.repo.upsert_memory(memory_id, self.project_id, row["kind"], "retired", row["content"])
        self.bump()

    def delete(self, memory_id: str) -> None:
        row = self.repo.get_memory(memory_id)
        if row is None or row["project_id"] != self.project_id:
            raise ValueError("프로젝트 범위의 기억이 아님")
        self.repo.delete_memory(memory_id, self.project_id)
        self.bump()

    def list(self, kind: str | None = None, status: str | None = None) -> list[MemoryRecord]:
        rows = self.repo.list_memories(self.project_id, kind, status)
        return [MemoryRecord.from_row(r) for r in rows]

    def active_rules(self) -> list[MemoryRecord]:
        return [m for m in self.list("rule", "confirmed")]
