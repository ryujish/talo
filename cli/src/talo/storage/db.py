"""SQLite 연결·마이그레이션.

WAL, foreign_keys, busy_timeout을 초기화하고 FTS5 지원 여부를 확인한다.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    # v1: 초기 스키마 (기술 설계 12.2절)
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        canonical_path TEXT NOT NULL,
        git_common_dir TEXT,
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
        title TEXT,
        parent_id TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        connection_id TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id),
        request_id TEXT NOT NULL,
        mode TEXT NOT NULL,
        policy_version INTEGER NOT NULL DEFAULT 1,
        state TEXT NOT NULL,
        checkpoint_id TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        UNIQUE(session_id, request_id)
    );
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        role TEXT NOT NULL,
        content_json TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'model',
        status TEXT NOT NULL DEFAULT 'complete',
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        run_id TEXT,
        seq INTEGER,
        type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at REAL NOT NULL,
        UNIQUE(session_id, seq)
    );
    CREATE TABLE IF NOT EXISTS operations (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        call_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        input_hash TEXT NOT NULL,
        state TEXT NOT NULL,
        result_ref TEXT,
        started_at REAL,
        finished_at REAL,
        UNIQUE(run_id, call_id)
    );
    CREATE TABLE IF NOT EXISTS checkpoints (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        event_cursor INTEGER NOT NULL DEFAULT 0,
        workspace_snapshot TEXT,
        context_version INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS handoffs (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id),
        source_run_id TEXT,
        context_version INTEGER NOT NULL DEFAULT 1,
        document_json TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        content TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        source_refs TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY,
        relative_path TEXT NOT NULL,
        hash TEXT,
        size INTEGER NOT NULL DEFAULT 0,
        mime TEXT,
        redaction_status TEXT NOT NULL DEFAULT 'none'
    );
    CREATE TABLE IF NOT EXISTS verifications (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        operation_id TEXT,
        workspace_hash TEXT,
        result TEXT NOT NULL,
        evidence_ref TEXT,
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS grants (
        id TEXT PRIMARY KEY,
        scope_json TEXT NOT NULL,
        policy_version INTEGER NOT NULL DEFAULT 1,
        created_by TEXT,
        expires_at REAL,
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS usage (
        id TEXT PRIMARY KEY,
        request_id TEXT,
        connection_id TEXT,
        model_id TEXT,
        measured_tokens INTEGER,
        estimated_cost REAL,
        source TEXT NOT NULL DEFAULT 'unknown',
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        checksum TEXT NOT NULL,
        applied_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_id, seq);
    CREATE INDEX IF NOT EXISTS idx_messages_run ON messages(run_id);
    CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id, status);
    CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id);
    """,
    # v2: P1 스케줄 (Slice 1 — scheduled_jobs/scheduled_runs만)
    """
    CREATE TABLE IF NOT EXISTS scheduled_jobs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        name TEXT NOT NULL,
        prompt TEXT NOT NULL,
        schedule_json TEXT NOT NULL,
        timezone TEXT NOT NULL DEFAULT 'local',
        enabled INTEGER NOT NULL DEFAULT 1,
        next_run_at REAL NOT NULL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS scheduled_runs (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES scheduled_jobs(id),
        scheduled_for REAL NOT NULL,
        state TEXT NOT NULL,
        session_id TEXT,
        run_id TEXT,
        error TEXT,
        started_at REAL,
        finished_at REAL,
        created_at REAL NOT NULL,
        UNIQUE(job_id, scheduled_for)
    );
    CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_due ON scheduled_jobs(enabled, next_run_at);
    """,
    # v3: P1 승인 요청 Inbox
    """
    CREATE TABLE IF NOT EXISTS approval_requests (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        scope_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','denied')),
        created_at REAL NOT NULL,
        decided_at REAL,
        decided_by TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status, created_at);
    """,
]


# v4: 사용자 검토 변경 묶음과 복구 journal. 이전 migration 체크섬은 유지한다.
from talo.changes.manager import SCHEMA as CHANGES_SCHEMA
from talo.continuity import SCHEMA as CONTINUITY_SCHEMA
MIGRATIONS.append(CHANGES_SCHEMA + CONTINUITY_SCHEMA)
MIGRATIONS.append("""
CREATE TABLE IF NOT EXISTS core_requests (
    workspace_id TEXT NOT NULL, request_id TEXT NOT NULL, body_hash TEXT NOT NULL,
    state TEXT NOT NULL, result_json TEXT, created_at REAL NOT NULL,
    PRIMARY KEY(workspace_id, request_id)
);
""")


class Database:
    """프로젝트·레지스트리 공용 SQLite 래퍼."""

    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()
        self.fts5_available = False

    def connect(self) -> sqlite3.Connection:
        path_str = str(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path_str, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            rows = conn.execute("PRAGMA compile_options").fetchall()
            self.fts5_available = any("ENABLE_FTS5" in str(r[0]) for r in rows)
        except sqlite3.Error:
            self.fts5_available = False
        return conn

    def get(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self.connect()
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def migrate(self) -> None:
        conn = self.get()
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at REAL NOT NULL)")
        for index, sql in enumerate(MIGRATIONS, start=1):
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            row = conn.execute("SELECT checksum FROM schema_migrations WHERE version=?", (index,)).fetchone()
            if row is None:
                import time

                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES(?,?,?)",
                    (index, checksum, time.time()),
                )
                conn.commit()
            elif row["checksum"] != checksum:
                raise RuntimeError(f"마이그레이션 체크섬 불일치: version={index}")
        # FTS5 인덱스는 지원 시에만 생성 (기억 검색용)
        if self.fts5_available:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    content, kind, project_id, content='memories', content_rowid='rowid'
                )
                """
            )
            conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.get().execute(sql, params)

    def commit(self) -> None:
        self.get().commit()

    def transaction(self) -> sqlite3.Connection:
        conn = self.get()
        conn.execute("BEGIN")
        return conn
