"""워크스페이스: Git 인식, 변경 기준, 스냅샷·비교, 쓰기 잠금.

기본 프로젝트는 현재 작업 폴더가 속한 Git 저장소다. Git이 없는 폴더도
사용할 수 있지만 Git 기반 비교·복구 기능 제한을 표시한다.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 잠금 파일은 프로세스 간 협조용이다. 외부 편집기는 이 잠금을 따르지 않으므로
# 적용 직전·직후 해시로 경합을 감지한다.
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:  # Windows
    HAS_FCNTL = False


def run_git(args: list[str], cwd: Path, timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
    )


@dataclass
class RepoInfo:
    is_git: bool
    root: Path
    common_dir: Path | None
    branch: str | None
    head_sha: str | None
    is_dirty: bool
    untracked: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    staged: list[str] = field(default_factory=list)
    workdir: Path = field(default_factory=Path.cwd)
    limitation_note: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "is_git": self.is_git,
            "root": str(self.root),
            "branch": self.branch,
            "head_sha": self.head_sha,
            "is_dirty": self.is_dirty,
            "changed": self.changed,
            "staged": self.staged,
            "untracked": self.untracked,
            "limitation": self.limitation_note,
        }


class Workspace:
    """현재 폴더 기준 저장소 인식과 변경 추적."""

    def __init__(self, cwd: Path | None = None):
        self.cwd = (cwd or Path.cwd()).resolve()

    def detect(self) -> RepoInfo:
        if not self.cwd.exists():
            return RepoInfo(is_git=False, root=self.cwd, common_dir=None, branch=None,
                            head_sha=None, is_dirty=False, workdir=self.cwd,
                            limitation_note="경로가 존재하지 않음")

        root_proc = run_git(["rev-parse", "--show-toplevel"], self.cwd)
        if root_proc.returncode != 0:
            return RepoInfo(
                is_git=False,
                root=self.cwd,
                common_dir=None,
                branch=None,
                head_sha=None,
                is_dirty=False,
                workdir=self.cwd,
                limitation_note="Git 저장소가 아님 — Git 기반 비교·복구 기능 제한",
            )

        root = Path(root_proc.stdout.strip()).resolve()
        branch_proc = run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
        head_proc = run_git(["rev-parse", "HEAD"], root)
        status_proc = run_git(["status", "--porcelain=v1"], root)

        changed: list[str] = []
        staged: list[str] = []
        untracked: list[str] = []
        if status_proc.returncode == 0:
            for line in status_proc.stdout.splitlines():
                if not line.strip():
                    continue
                xy = line[:2]
                path = line[3:].strip()
                if xy[0] != " ":
                    staged.append(path)
                if xy[1] != " ":
                    changed.append(path)
                elif xy[0] == "?":
                    untracked.append(path)

        common_dir_proc = run_git(["rev-parse", "--git-common-dir"], root)
        common_dir = Path(common_dir_proc.stdout.strip()).resolve() if common_dir_proc.returncode == 0 else None

        branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else None
        head_sha = head_proc.stdout.strip() if head_proc.returncode == 0 else None

        return RepoInfo(
            is_git=True,
            root=root,
            common_dir=common_dir,
            branch=branch,
            head_sha=head_sha,
            is_dirty=bool(changed or staged or untracked),
            changed=changed,
            staged=staged,
            untracked=untracked,
            workdir=self.cwd,
        )

    def snapshot(self) -> dict[str, Any]:
        """현재 파일 상태 스냅샷: 추적·변경 대상 파일의 해시와 HEAD."""
        info = self.detect()
        files: dict[str, str] = {}
        targets: set[str] = set(info.changed + info.staged + info.untracked)
        if info.is_git:
            # 이전에 깨끗했던 추적 파일이 이후 외부 수정되는 경우도 감지하기 위해 추적 파일 포함
            proc = run_git(["ls-files"], info.root)
            if proc.returncode == 0:
                targets.update(line.strip() for line in proc.stdout.splitlines() if line.strip())
        for rel in sorted(targets):
            p = info.root / rel
            if p.is_file():
                files[rel] = hash_file(p)
        return {
            "head": info.head_sha,
            "branch": info.branch,
            "root": str(info.root),
            "files": files,
            "at": time.time(),
        }

    def diff_stat(self) -> str:
        info = self.detect()
        if not info.is_git:
            return info.limitation_note
        proc = run_git(["diff", "--stat"], info.root)
        return proc.stdout.strip() or "(변경 없음)"

    def git_diff(self) -> str:
        info = self.detect()
        if not info.is_git:
            return ""
        proc = run_git(["diff", "HEAD"], info.root)
        return proc.stdout

    def compare_snapshot(self, before: dict[str, Any]) -> dict[str, Any]:
        """스냅샷과 현재 상태 비교. 기존 변경과 새 변경을 구분하는 기준."""
        now = self.snapshot()
        before_files = before.get("files", {})
        now_files = now.get("files", {})
        added = [k for k in now_files if k not in before_files]
        removed = [k for k in before_files if k not in now_files]
        modified = [k for k in before_files if k in now_files and before_files[k] != now_files[k]]
        return {
            "head_before": before.get("head"),
            "head_now": now.get("head"),
            "branch_before": before.get("branch"),
            "branch_now": now.get("branch"),
            "added": added,
            "removed": removed,
            "modified": modified,
            "external_changes": sorted(set(added + removed + modified)),
        }


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class WriteLock:
    """같은 워크스페이스의 Talo 변경을 OS 파일 잠금으로 직렬화."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._fh = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.lock_path.open("a+")
        if HAS_FCNTL:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                return False
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        if HAS_FCNTL:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        self._fh.close()
        self._fh = None

    def __enter__(self) -> "WriteLock":
        if not self.acquire():
            raise RuntimeError("다른 Talo 세션이 이 워크스페이스에 쓰는 중입니다")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()
