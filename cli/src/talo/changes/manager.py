"""SQLite journal과 바이트 스냅샷을 사용하는 변경 관리자.

파일 교체와 DB commit은 별개의 작업이다. applying/undoing 상태를 먼저
영속화하고 재시작 시 before/after 바이트를 대조해 복구한다.
"""
from __future__ import annotations

import contextlib
import difflib
import fnmatch
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from talo.workspace.repo import WriteLock, Workspace

SCHEMA = """
CREATE TABLE IF NOT EXISTS change_sets (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, run_id TEXT, session_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL,
    patch_hash TEXT NOT NULL, manifest_json TEXT NOT NULL,
    created_at REAL NOT NULL, updated_at REAL NOT NULL, applied_order INTEGER
);
CREATE INDEX IF NOT EXISTS idx_change_workspace ON change_sets(workspace_id, created_at);
CREATE TABLE IF NOT EXISTS change_events (
    cursor INTEGER PRIMARY KEY AUTOINCREMENT, change_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL, type TEXT NOT NULL, created_at REAL NOT NULL
);
"""
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_BATCH_BYTES = 16 * 1024 * 1024


class ChangeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".talo-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fchmod(out.fileno(), mode)
            os.fsync(out.fileno())
        os.replace(name, path)
        fsync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class ChangeManager:
    def __init__(self, root: Path, db_path: Path, artifacts: Path, workspace_id: str,
                 exclude_paths: list[str] | None = None):
        self.root = root.resolve()
        self.db_path = db_path
        self.artifacts = artifacts.resolve() / "checkpoints"
        self.workspace_id = workspace_id
        self.exclude_paths = exclude_paths or []
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.artifacts, 0o700)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextlib.contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=FULL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def lock(self):
        return WriteLock(self.artifacts / (digest(str(self.root).encode()) + ".lock"))

    def target(self, relative: str) -> Path:
        rel = Path(relative)
        if rel.is_absolute():
            try:
                rel = rel.relative_to(self.root)
            except ValueError:
                raise ChangeError("PATH_ESCAPE", "프로젝트 범위를 벗어난 경로") from None
        if not rel.parts or ".." in rel.parts or any(p in {".git", ".talo"} for p in rel.parts):
            raise ChangeError("PATH_ESCAPE", "프로젝트 메타데이터 또는 잘못된 경로")
        if any(fnmatch.fnmatch(str(rel), pat) or any(fnmatch.fnmatch(p, pat) for p in rel.parts)
               for pat in self.exclude_paths):
            raise ChangeError("POLICY_DENIED", "제외된 파일 경로")
        p = self.root
        for part in rel.parts:
            p = p / part
            if p.is_symlink():
                raise ChangeError("UNSUPPORTED_FILE", "심볼릭 링크 변경은 지원하지 않습니다")
            if p != self.root / rel and (p / ".git").exists():
                raise ChangeError("UNSUPPORTED_FILE", "중첩 저장소·서브모듈 변경은 지원하지 않습니다")
        if p.exists() and (not p.is_file() or p.stat().st_nlink > 1):
            raise ChangeError("UNSUPPORTED_FILE", "일반 단일 링크 파일만 변경할 수 있습니다")
        if p == self.db_path.resolve() or self.artifacts in p.parents:
            raise ChangeError("PATH_ESCAPE", "복구 보관소는 변경할 수 없습니다")
        return p

    def read(self, path: Path) -> bytes | None:
        if not path.exists():
            return None
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ChangeError("FILE_TOO_LARGE", "파일 크기 상한(2 MiB)을 초과했습니다")
        data = path.read_bytes()
        if b"\0" in data:
            raise ChangeError("UNSUPPORTED_FILE", "바이너리 파일 편집은 지원하지 않습니다")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise ChangeError("INVALID_ENCODING", "UTF-8 파일만 변경할 수 있습니다") from None
        return data

    def blob(self, data: bytes | None) -> str | None:
        if data is None:
            return None
        h = digest(data)
        path = self.artifacts / h
        if not path.exists():
            atomic_bytes(path, data)
        elif digest(path.read_bytes()) != h:
            raise ChangeError("CORRUPT_CHECKPOINT", "복구 파일 해시가 일치하지 않습니다")
        return h

    def load_blob(self, h: str | None) -> bytes | None:
        if h is None:
            return None
        if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
            raise ChangeError("CORRUPT_CHECKPOINT", "잘못된 복구 참조")
        data = (self.artifacts / h).read_bytes()
        if digest(data) != h:
            raise ChangeError("CORRUPT_CHECKPOINT", "복구 파일이 손상되었습니다")
        return data

    def propose(self, edits: list[dict[str, Any]], *, run_id: str = "", session_id: str = "",
                match_method: str = "exact") -> dict[str, Any]:
        if not edits or len(edits) > 100:
            raise ChangeError("INVALID_CHANGE", "변경 파일 수는 1~100개여야 합니다")
        with self.lock():
            self._ensure_idle()
            info = Workspace(self.root).detect()
            files, seen, total = [], set(), 0
            for edit in edits:
                p = self.target(edit["path"])
                rel = str(p.relative_to(self.root))
                if rel in seen:
                    raise ChangeError("INVALID_CHANGE", "같은 파일이 변경 묶음에 중복되었습니다")
                seen.add(rel)
                before = self.read(p)
                bh = digest(before) if before is not None else None
                if "expected_hash" in edit and edit["expected_hash"] != bh:
                    raise ChangeError("STALE_BASE", "파일 해시 불일치: 다시 읽고 변경을 생성하세요")
                after = edit.get("content")
                if isinstance(after, str):
                    after = after.encode("utf-8")
                if after is not None:
                    if not isinstance(after, bytes) or len(after) > MAX_FILE_BYTES or b"\0" in after:
                        raise ChangeError("INVALID_CHANGE", "텍스트 파일 크기·형식을 확인하세요")
                    after.decode("utf-8")
                total += len(before or b"") + len(after or b"")
                if total > MAX_BATCH_BYTES:
                    raise ChangeError("CHANGE_TOO_LARGE", "변경 묶음 크기 상한을 초과했습니다")
                if before == after:
                    continue
                files.append({"path": rel, "before": self.blob(before), "after": self.blob(after),
                              "mode": stat.S_IMODE(p.stat().st_mode) if before is not None else 0o644})
            if not files:
                raise ChangeError("NO_CHANGE", "적용할 변경이 없습니다")
            manifest = {"root": str(self.root), "head": info.head_sha, "branch": info.branch,
                        "files": files, "match_method": match_method}
            raw = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
            cid = "chg_" + uuid.uuid4().hex[:16]
            now = time.time()
            with self.connect() as conn:
                conn.execute("INSERT INTO change_sets(id,workspace_id,run_id,session_id,state,patch_hash,"
                             "manifest_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                             (cid, self.workspace_id, run_id, session_id, "proposed", digest(raw.encode()), raw, now, now))
                conn.execute("INSERT INTO change_events(change_id,workspace_id,type,created_at) VALUES(?,?,?,?)",
                             (cid, self.workspace_id, "proposed", now))
            return self.get(cid)

    def get(self, cid: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM change_sets WHERE id=? AND workspace_id=?",
                               (cid, self.workspace_id)).fetchone()
        if row is None:
            raise ChangeError("NOT_FOUND", "현재 작업 공간의 변경을 찾지 못했습니다")
        result = dict(row)
        result["manifest"] = json.loads(result.pop("manifest_json"))
        return result

    def list(self, state: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            query = "SELECT id FROM change_sets WHERE workspace_id=?"
            params: list[Any] = [self.workspace_id]
            if state:
                query += " AND state=?"
                params.append(state)
            rows = conn.execute(query + " ORDER BY created_at DESC LIMIT 100", params).fetchall()
        return [self.get(row["id"]) for row in rows]

    def diff(self, cid: str) -> str:
        change = self.get(cid)
        parts = []
        for f in change["manifest"]["files"]:
            before = (self.load_blob(f["before"]) or b"").decode("utf-8").splitlines(keepends=True)
            after = (self.load_blob(f["after"]) or b"").decode("utf-8").splitlines(keepends=True)
            lines = difflib.unified_diff(before, after, fromfile="a/" + f["path"] if f["before"] else "/dev/null",
                                        tofile="b/" + f["path"] if f["after"] else "/dev/null")
            for line in lines:
                parts.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
        return "".join(parts)

    def _ensure_idle(self):
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM change_sets WHERE workspace_id=? AND state IN "
                               "('applying','undoing','recovery_required') LIMIT 1", (self.workspace_id,)).fetchone()
        if row:
            raise ChangeError("RECOVERY_REQUIRED", f"복구가 필요합니다: talo changes recover {row['id']}")

    def _state(self, cid: str, state: str):
        with self.connect() as conn:
            cursor = conn.execute("INSERT INTO change_events(change_id,workspace_id,type,created_at) VALUES(?,?,?,?)",
                                  (cid, self.workspace_id, state, time.time())).lastrowid
            conn.execute("UPDATE change_sets SET state=?,updated_at=?,applied_order=CASE WHEN ?='applied' "
                         "THEN ? ELSE applied_order END WHERE id=? AND workspace_id=?",
                         (state, time.time(), state, cursor, cid, self.workspace_id))

    def _check_identity(self, change):
        m = change["manifest"]
        info = Workspace(self.root).detect()
        if m["root"] != str(self.root) or m["head"] != info.head_sha or m["branch"] != info.branch:
            raise ChangeError("WORKSPACE_CHANGED", "브랜치·HEAD·작업 경로가 달라졌습니다")

    def _hash(self, f):
        p = self.target(f["path"])
        data = self.read(p)
        if data is not None and stat.S_IMODE(p.stat().st_mode) != f["mode"]:
            raise ChangeError("STALE_BASE", f"파일 권한이 변경되었습니다: {f['path']}")
        return digest(data) if data is not None else None

    def _replace(self, f, side):
        p = self.target(f["path"])
        data = self.load_blob(f[side])
        if data is None:
            if p.exists():
                p.unlink()
                fsync_dir(p.parent)
        else:
            atomic_bytes(p, data, f["mode"])

    def apply(self, cid: str, patch_hash: str) -> dict[str, Any]:
        with self.lock():
            c = self.get(cid)
            if c["patch_hash"] != patch_hash:
                raise ChangeError("STALE_APPROVAL", "검토한 변경과 승인 해시가 다릅니다")
            if c["state"] == "applied":
                return c  # 응답 유실 재시도. 파일 작업을 재생하지 않는다.
            self._ensure_idle()
            if c["state"] != "proposed":
                raise ChangeError("INVALID_STATE", "적용 가능한 제안 상태가 아닙니다")
            self._check_identity(c)
            for f in c["manifest"]["files"]:
                if self._hash(f) != f["before"]:
                    self._state(cid, "stale")
                    raise ChangeError("STALE_BASE", "파일 해시 불일치: 새 diff를 생성하세요")
                self.load_blob(f["before"])
                self.load_blob(f["after"])
            self._state(cid, "applying")
            try:
                for f in c["manifest"]["files"]:
                    if self._hash(f) != f["before"]:
                        raise ChangeError("STALE_BASE", "적용 도중 외부 파일 변경 감지")
                    self._replace(f, "after")
                if any(self._hash(f) != f["after"] for f in c["manifest"]["files"]):
                    raise ChangeError("STALE_BASE", "적용 결과에 외부 변경 감지")
                self._state(cid, "applied")
            except BaseException:
                self._state(cid, "recovery_required")
                raise
            return self.get(cid)

    def cancel(self, cid: str) -> dict[str, Any]:
        with self.lock():
            c = self.get(cid)
            if c["state"] == "proposed":
                self._state(cid, "cancelled")
            elif c["state"] != "cancelled":
                raise ChangeError("INVALID_STATE", "제안 상태의 변경만 취소할 수 있습니다")
            return self.get(cid)

    def undo(self, cid: str | None = None) -> dict[str, Any]:
        with self.lock():
            self._ensure_idle()
            if cid and self.get(cid)["state"] == "rolled_back":
                return self.get(cid)
            with self.connect() as conn:
                row = conn.execute("SELECT id FROM change_sets WHERE workspace_id=? AND state='applied' "
                                   "ORDER BY applied_order DESC LIMIT 1", (self.workspace_id,)).fetchone()
            if not row:
                raise ChangeError("NOT_FOUND", "되돌릴 Talo 변경이 없습니다")
            if cid and cid != row["id"]:
                raise ChangeError("INVALID_ORDER", "가장 최근 적용한 변경부터 되돌려야 합니다")
            cid = row["id"]
            c = self.get(cid)
            self._check_identity(c)
            for f in c["manifest"]["files"]:
                if self._hash(f) != f["after"]:
                    raise ChangeError("UNDO_CONFLICT", f"이후 수정이 있어 보존했습니다: {f['path']}")
                self.load_blob(f["before"])
            self._state(cid, "undoing")
            try:
                for f in reversed(c["manifest"]["files"]):
                    if self._hash(f) != f["after"]:
                        raise ChangeError("UNDO_CONFLICT", "복구 도중 외부 변경 감지")
                    self._replace(f, "before")
                if any(self._hash(f) != f["before"] for f in c["manifest"]["files"]):
                    raise ChangeError("UNDO_CONFLICT", "복구 결과에 외부 변경 감지")
                self._state(cid, "rolled_back")
            except BaseException:
                self._state(cid, "recovery_required")
                raise
            return self.get(cid)

    def recover(self, cid: str) -> dict[str, Any]:
        """명시적 복구는 알려진 before/after만 원래 바이트로 되돌린다."""
        with self.lock():
            c = self.get(cid)
            if c["state"] == "rolled_back":
                return c
            if c["state"] not in {"applying", "undoing", "recovery_required"}:
                raise ChangeError("INVALID_STATE", "복구 대기 중인 변경이 아닙니다")
            self._check_identity(c)
            for f in c["manifest"]["files"]:
                if self._hash(f) not in {f["before"], f["after"]}:
                    raise ChangeError("UNDO_CONFLICT", f"알 수 없는 외부 변경을 보존했습니다: {f['path']}")
                self.load_blob(f["before"])
            for f in reversed(c["manifest"]["files"]):
                if self._hash(f) not in {f["before"], f["after"]}:
                    raise ChangeError("UNDO_CONFLICT", "복구 도중 외부 변경 감지")
                self._replace(f, "before")
            if any(self._hash(f) != f["before"] for f in c["manifest"]["files"]):
                raise ChangeError("UNDO_CONFLICT", "복구 결과 확인이 필요합니다")
            self._state(cid, "rolled_back")
            return self.get(cid)


def for_context(ctx) -> ChangeManager:
    from talo import paths
    root = ctx.repo_root if hasattr(ctx, "repo_root") else ctx.repo_info.root
    db = ctx.repository.db.path if ctx.repository else ctx.artifacts_dir / "changes.sqlite"
    artifacts = paths.artifacts_dir(ctx.project_id) if hasattr(ctx, "repo_info") else ctx.artifacts_dir
    workspace_id = getattr(ctx, "workspace_id", "") or digest(str(root.resolve()).encode())
    exclusions = ctx.config.exclude_paths if hasattr(ctx, "config") else ctx.exclude_paths
    return ChangeManager(root, db, artifacts, workspace_id, exclusions)
