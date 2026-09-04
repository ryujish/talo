"""저장소 레포지토리: 세션·런·이벤트·기억·승인·검증 기록의 고수준 연산.

모든 비동기 작업에 project_id/workspace_id/session_id/run_id를 명시한다.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from talo.sanitize import sanitize_scope_json
from talo.storage.db import Database


def _now() -> float:
    return time.time()


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Repository:
    def __init__(self, db: Database):
        self.db = db

    @property
    def conn(self) -> sqlite3.Connection:
        return self.db.get()

    # -- workspace / project -------------------------------------------------
    def upsert_workspace(self, project_id: str, canonical_path: str, git_common_dir: str | None) -> str:
        row = self.conn.execute(
            "SELECT id FROM workspaces WHERE project_id=? AND canonical_path=?",
            (project_id, canonical_path),
        ).fetchone()
        if row:
            return row["id"]
        ws_id = _uid("ws")
        self.conn.execute(
            "INSERT INTO workspaces(id, project_id, canonical_path, git_common_dir, created_at) VALUES(?,?,?,?,?)",
            (ws_id, project_id, canonical_path, git_common_dir, _now()),
        )
        self.conn.commit()
        return ws_id

    def workspace_by_project(self, project_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM workspaces WHERE project_id=? ORDER BY created_at", (project_id,)
        ).fetchall()

    def list_projects(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT project_id, MIN(created_at) AS first_seen, COUNT(*) AS workspace_count "
            "FROM workspaces GROUP BY project_id ORDER BY first_seen DESC"
        ).fetchall()

    # -- sessions -------------------------------------------------------------
    def create_session(self, workspace_id: str, title: str | None, connection_id: str | None,
                       parent_id: str | None = None) -> str:
        sid = _uid("ses")
        self.conn.execute(
            "INSERT INTO sessions(id, workspace_id, title, parent_id, status, connection_id, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (sid, workspace_id, title, parent_id, "open", connection_id, _now(), _now()),
        )
        self.conn.commit()
        return sid

    def get_session(self, session_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()

    def list_sessions(self, workspace_id: str | None = None, limit: int = 20) -> list[sqlite3.Row]:
        if workspace_id:
            return self.conn.execute(
                "SELECT * FROM sessions WHERE workspace_id=? ORDER BY updated_at DESC LIMIT ?",
                (workspace_id, limit),
            ).fetchall()
        return self.conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()

    def touch_session(self, session_id: str, **fields: Any) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE sessions SET {sets}, updated_at=? WHERE id=?", (*fields.values(), _now(), session_id))
        self.conn.commit()

    # -- runs ---------------------------------------------------------------
    def create_run(self, session_id: str, request_id: str, mode: str, state: str, policy_version: int = 1) -> str:
        rid = _uid("run")
        self.conn.execute(
            "INSERT INTO runs(id, session_id, request_id, mode, policy_version, state, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (rid, session_id, request_id, mode, policy_version, state, _now(), _now()),
        )
        self.conn.commit()
        return rid

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()

    def update_run_state(self, run_id: str, state: str, checkpoint_id: str | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET state=?, checkpoint_id=COALESCE(?, checkpoint_id), updated_at=? WHERE id=?",
            (state, checkpoint_id, _now(), run_id),
        )
        self.conn.commit()

    def list_runs(self, session_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM runs WHERE session_id=? ORDER BY created_at", (session_id,)).fetchall()

    # -- messages -------------------------------------------------------------
    def append_message(self, run_id: str, role: str, content_json: str, source: str = "model",
                       status: str = "complete") -> str:
        mid = _uid("msg")
        self.conn.execute(
            "INSERT INTO messages(id, run_id, role, content_json, source, status, created_at) VALUES(?,?,?,?,?,?,?)",
            (mid, run_id, role, content_json, source, status, _now()),
        )
        self.conn.commit()
        return mid

    def list_messages(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM messages WHERE run_id=? ORDER BY created_at, rowid", (run_id,)).fetchall()

    # -- events ----------------------------------------------------------------
    def next_event_seq(self, session_id: str) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(seq), 0) AS m FROM events WHERE session_id=?", (session_id,)).fetchone()
        return int(row["m"]) + 1

    def append_event(self, session_id: str, run_id: str | None, event_type: str, payload: dict[str, Any],
                     seq: int | None = None, event_id: str | None = None) -> tuple[int, str]:
        """이벤트 저장. (session_id, seq) 고유. 커밋 후 전달을 보장한다."""
        if seq is None:
            seq = self.next_event_seq(session_id)
        eid = event_id or _uid("evt")
        payload_json = json.dumps(payload, ensure_ascii=False)
        try:
            self.conn.execute(
                "INSERT INTO events(id, session_id, run_id, seq, type, payload_json, created_at) VALUES(?,?,?,?,?,?,?)",
                (eid, session_id, run_id, seq, event_type, payload_json, _now()),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            # 중복 키면 기존 이벤트를 반환 (재실행 방지)
            self.conn.rollback()
            row = self.conn.execute("SELECT seq, id FROM events WHERE session_id=? AND seq=?", (session_id, seq)).fetchone()
            if row:
                return int(row["seq"]), str(row["id"])
            raise
        return seq, eid

    def replay_events(self, session_id: str, after_cursor: int = 0) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events WHERE session_id=? AND seq>? ORDER BY seq", (session_id, after_cursor)
        ).fetchall()

    # -- operations -------------------------------------------------------------
    def record_operation(self, run_id: str, call_id: str, tool_name: str, input_hash: str, state: str,
                         result_ref: str | None = None, started_at: float | None = None,
                         finished_at: float | None = None) -> str:
        op_id = _uid("op")
        self.conn.execute(
            "INSERT INTO operations(id, run_id, call_id, tool_name, input_hash, state, result_ref, started_at, finished_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (op_id, run_id, call_id, tool_name, input_hash, state, result_ref, started_at, finished_at),
        )
        self.conn.commit()
        return op_id

    def update_operation(self, op_id: str, state: str, result_ref: str | None = None,
                         finished_at: float | None = None) -> None:
        self.conn.execute(
            "UPDATE operations SET state=?, result_ref=COALESCE(?, result_ref), finished_at=COALESCE(?, finished_at) WHERE id=?",
            (state, result_ref, finished_at, op_id),
        )
        self.conn.commit()

    def operations_for_run(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM operations WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()

    # -- checkpoints / handoffs -------------------------------------------------
    def save_checkpoint(self, run_id: str, event_cursor: int, workspace_snapshot: str | None, context_version: int) -> str:
        cid = _uid("ckpt")
        self.conn.execute(
            "INSERT INTO checkpoints(id, run_id, event_cursor, workspace_snapshot, context_version) VALUES(?,?,?,?,?)",
            (cid, run_id, event_cursor, workspace_snapshot, context_version),
        )
        self.conn.commit()
        return cid

    def save_handoff(self, session_id: str, source_run_id: str | None, context_version: int, document: dict[str, Any]) -> str:
        hid = _uid("ho")
        self.conn.execute(
            "INSERT INTO handoffs(id, session_id, source_run_id, context_version, document_json, created_at) VALUES(?,?,?,?,?,?)",
            (hid, session_id, source_run_id, context_version, json.dumps(document, ensure_ascii=False), _now()),
        )
        self.conn.commit()
        return hid

    # -- memories -------------------------------------------------------------
    def upsert_memory(self, memory_id: str | None, project_id: str, kind: str, status: str, content: str,
                      source_refs: list[str] | None = None, version: int | None = None) -> str:
        now = _now()
        refs = json.dumps(source_refs or [], ensure_ascii=False)
        if memory_id:
            self.conn.execute(
                "UPDATE memories SET kind=?, status=?, content=?, source_refs=?, version=version+1, updated_at=? "
                "WHERE id=? AND project_id=?",
                (kind, status, content, refs, now, memory_id, project_id),
            )
            mid = memory_id
        else:
            mid = _uid("mem")
            self.conn.execute(
                "INSERT INTO memories(id, project_id, kind, status, content, version, source_refs, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (mid, project_id, kind, status, content, version or 1, refs, now, now),
            )
        self.conn.commit()
        return mid

    def get_memory(self, memory_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()

    def list_memories(self, project_id: str, kind: str | None = None, status: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM memories WHERE project_id=?"
        params: list[Any] = [project_id]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY updated_at DESC"
        return self.conn.execute(sql, params).fetchall()

    def search_memories(self, project_id: str, query: str, limit: int = 10) -> list[sqlite3.Row]:
        if self.db.fts5_available:
            rows = self.conn.execute(
                "SELECT m.* FROM memories_fts f JOIN memories m ON m.rowid=f.rowid "
                "WHERE f.project_id=? AND memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (project_id, _fts_query(query), limit),
            ).fetchall()
            if rows:
                return rows
        # CJK·부분 문자열 보완 경로
        like = f"%{query}%"
        return self.conn.execute(
            "SELECT * FROM memories WHERE project_id=? AND content LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (project_id, like, limit),
        ).fetchall()

    def delete_memory(self, memory_id: str, project_id: str) -> None:
        self.conn.execute("DELETE FROM memories WHERE id=? AND project_id=?", (memory_id, project_id))
        self.conn.commit()

    # -- verifications ---------------------------------------------------------
    def record_verification(self, run_id: str, operation_id: str | None, workspace_hash: str | None,
                            result: str, evidence_ref: str | None = None) -> str:
        vid = _uid("ver")
        self.conn.execute(
            "INSERT INTO verifications(id, run_id, operation_id, workspace_hash, result, evidence_ref, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (vid, run_id, operation_id, workspace_hash, result, evidence_ref, _now()),
        )
        self.conn.commit()
        return vid

    # -- grants -----------------------------------------------------------------
    def save_grant(self, scope_json: str, policy_version: int, created_by: str, expires_at: float | None = None) -> str:
        gid = _uid("grt")
        self.conn.execute(
            "INSERT INTO grants(id, scope_json, policy_version, created_by, expires_at, created_at) VALUES(?,?,?,?,?,?)",
            (gid, scope_json, policy_version, created_by, expires_at, _now()),
        )
        self.conn.commit()
        return gid

    def list_grants(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM grants ORDER BY created_at").fetchall()

    # -- usage -------------------------------------------------------------------
    def record_usage(self, request_id: str, connection_id: str, model_id: str, measured_tokens: int | None,
                     estimated_cost: float | None, source: str) -> None:
        self.conn.execute(
            "INSERT INTO usage(id, request_id, connection_id, model_id, measured_tokens, estimated_cost, source, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (_uid("use"), request_id, connection_id, model_id, measured_tokens, estimated_cost, source, _now()),
        )
        self.conn.commit()

    # -- artifacts ---------------------------------------------------------------
    def register_artifact(self, relative_path: str, size: int, sha: str | None = None,
                          mime: str | None = None) -> str:
        aid = _uid("art")
        self.conn.execute(
            "INSERT INTO artifacts(id, relative_path, hash, size, mime, redaction_status) VALUES(?,?,?,?,?,?)",
            (aid, relative_path, sha, size, mime, "none"),
        )
        self.conn.commit()
        return aid

    # -- scheduled jobs (Slice 1) -------------------------------------------------
    def create_job(self, project_id: str, name: str, prompt: str, schedule_json: str,
                   timezone: str = "local", next_run_at: float | None = None) -> str:
        jid = _uid("job")
        self.conn.execute(
            "INSERT INTO scheduled_jobs(id, project_id, name, prompt, schedule_json, timezone, enabled,"
            " next_run_at, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (jid, project_id, name, prompt, schedule_json, timezone, 1,
             next_run_at if next_run_at is not None else _now(), _now(), _now()),
        )
        self.conn.commit()
        return jid

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM scheduled_jobs WHERE id=?", (job_id,)).fetchone()

    def list_jobs(self, project_id: str, enabled_only: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM scheduled_jobs WHERE project_id=?"
        params: list[Any] = [project_id]
        if enabled_only:
            sql += " AND enabled=1"
        sql += " ORDER BY created_at"
        return self.conn.execute(sql, params).fetchall()

    def disable_job(self, job_id: str, project_id: str) -> bool:
        cur = self.conn.execute(
            "UPDATE scheduled_jobs SET enabled=0, updated_at=? WHERE id=? AND project_id=?",
            (_now(), job_id, project_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def due_jobs(self, project_id: str, now: float | None = None) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM scheduled_jobs WHERE project_id=? AND enabled=1 AND next_run_at<=?"
            " ORDER BY next_run_at",
            (project_id, now if now is not None else _now()),
        ).fetchall()

    def claim_due_job(self, job_id: str, project_id: str, scheduled_for: float,
                      next_run_at: float) -> str | None:
        """BEGIN IMMEDIATE로 쓰기 트랜잭션을 열고 UNIQUE(job_id, scheduled_for)로 선점한다.

        이미 같은 슬롯이 선점됐거나 job이 다른 프로젝트/비활성화면 None을 반환한다.
        """
        rid = _uid("sch")
        try:
            if self.conn.in_transaction:
                self.conn.commit()
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                "INSERT INTO scheduled_runs(id, job_id, scheduled_for, state, created_at)"
                " VALUES(?,?,?,?,?)",
                (rid, job_id, scheduled_for, "claimed", _now()),
            )
            cur = self.conn.execute(
                "UPDATE scheduled_jobs SET next_run_at=?, updated_at=? WHERE id=? AND project_id=? AND enabled=1",
                (next_run_at, _now(), job_id, project_id),
            )
            if cur.rowcount == 0:
                # 프로젝트 불일치 또는 비활성 job — 선점 무효
                self.conn.rollback()
                return None
            self.conn.commit()
            return rid
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return None

    def mark_scheduled_run(self, scheduled_run_id: str, state: str, *, session_id: str | None = None,
                           run_id: str | None = None, error: str | None = None,
                           started_at: float | None = None, finished_at: float | None = None) -> None:
        self.conn.execute(
            "UPDATE scheduled_runs SET state=?, session_id=COALESCE(?, session_id),"
            " run_id=COALESCE(?, run_id), error=COALESCE(?, error),"
            " started_at=COALESCE(?, started_at), finished_at=COALESCE(?, finished_at) WHERE id=?",
            (state, session_id, run_id, error, started_at, finished_at, scheduled_run_id),
        )
        self.conn.commit()

    def scheduled_run_history(self, job_id: str, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM scheduled_runs WHERE job_id=? ORDER BY created_at DESC LIMIT ?",
            (job_id, max(1, min(limit, 200))),
        ).fetchall()

    # -- approval requests (Inbox) -----------------------------------------------
    def create_approval_request(self, session_id: str, run_id: str, tool_name: str,
                                scope_json: str) -> str:
        aid = _uid("apr")
        self.conn.execute(
            "INSERT INTO approval_requests(id, session_id, run_id, tool_name, scope_json, status, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (aid, session_id, run_id, tool_name, sanitize_scope_json(scope_json), "pending", _now()),
        )
        self.conn.commit()
        return aid

    def get_approval_request(self, request_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM approval_requests WHERE id=?", (request_id,)).fetchone()

    def list_approval_requests(self, status: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        sql = "SELECT * FROM approval_requests"
        params: list[Any] = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(max(1, min(limit, 200)))
        return self.conn.execute(sql, params).fetchall()

    def decide_approval_request(self, request_id: str, status: str, decided_by: str) -> bool:
        """pending 요청만 결정 가능. 이미 결정된 요청은 False 반환."""
        cur = self.conn.execute(
            "UPDATE approval_requests SET status=?, decided_at=?, decided_by=? WHERE id=? AND status='pending'",
            (status, _now(), decided_by, request_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    # -- handoff read ------------------------------------------------------------
    def latest_handoff(self, session_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM handoffs WHERE session_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()


def _fts_query(query: str) -> str:
    """사용자 검색어를 FTS5 MATCH 식으로 변환. 부분 토큰은 * 접미로 보완."""
    tokens = [t for t in query.replace('"', " ").split() if t]
    if not tokens:
        return '""'
    return " AND ".join(f'"{t}"*' for t in tokens)


class Registry:
    """~/.talo/registry.sqlite: 프로젝트 위치 목록."""

    def __init__(self, db: Database):
        self.db = db

    def migrate(self) -> None:
        conn = self.db.get()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects ("
            " id TEXT PRIMARY KEY, canonical_path TEXT NOT NULL, display_name TEXT, created_at REAL NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at REAL NOT NULL)"
        )
        conn.commit()

    def register_project(self, project_id: str, canonical_path: str, display_name: str) -> None:
        self.db.get().execute(
            "INSERT INTO projects(id, canonical_path, display_name, created_at) VALUES(?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET canonical_path=excluded.canonical_path",
            (project_id, canonical_path, display_name, _now()),
        )
        self.db.get().commit()

    def project(self, project_id: str) -> sqlite3.Row | None:
        return self.db.get().execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()

    def find_project_by_path(self, canonical_path: str) -> sqlite3.Row | None:
        return self.db.get().execute("SELECT * FROM projects WHERE canonical_path=?", (canonical_path,)).fetchone()

    def list_projects(self) -> list[sqlite3.Row]:
        return self.db.get().execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
