"""macOS 외부 CLI의 파일 쓰기를 임시 작업 공간으로 제한한다.

네트워크·읽기 격리가 아닌 파일 변경 격리다. 원본으로의 적용은 ChangeManager가 한다.
"""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from talo.changes.manager import ChangeError, MAX_FILE_BYTES, digest
from talo.workspace.repo import run_git


class CliWorkspace:
    def __init__(self, root: Path, exclude_paths: list[str]):
        if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
            raise ChangeError("ISOLATION_UNAVAILABLE", "외부 CLI 파일 격리는 현재 macOS에서만 지원합니다. 모델 API 연결을 선택하세요")
        self.root = root.resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="talo-cli-")
        self.stage = Path(self.temp.name).resolve() / "workspace"
        self.stage.mkdir()
        self.exclude = [".git", ".talo", "node_modules", ".venv", "__pycache__", ".env*", "*.pem", "*.key", *exclude_paths]
        self.before: dict[str, str] = {}
        self.modes: dict[str, int] = {}
        try:
            proc = run_git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], root)
            names = proc.stdout.split("\0") if proc.returncode == 0 else [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]
            total = 0
            for name in sorted(set(names)):
                rel = Path(name)
                if not name or self.excluded(rel):
                    continue
                p = root / rel
                if p.is_symlink() or any(parent.is_symlink() for parent in p.parents) or not p.is_file():
                    continue
                if p.stat().st_size > MAX_FILE_BYTES:
                    raise ChangeError("FILE_TOO_LARGE", f"격리 복제 파일 상한 초과: {name}")
                total += p.stat().st_size
                if total > 64 * 1024 * 1024 or len(self.before) >= 10000:
                    raise ChangeError("WORKSPACE_TOO_LARGE", "외부 CLI 격리 복제 상한(64 MiB/10000 파일)을 초과했습니다")
                data = p.read_bytes()
                self.before[name] = digest(data)
                self.modes[name] = p.stat().st_mode & 0o777
                target = self.stage / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(self.modes[name])
            profile = Path(self.temp.name) / "profile.sb"
            profile.write_text('(version 1)\n(allow default)\n(deny file-write*)\n'
                               + '(allow file-write* (subpath ' + json.dumps(str(self.stage)) + ') '
                               + '(literal "/dev/null") (literal "/dev/tty"))\n')
            self.prefix = ["/usr/bin/sandbox-exec", "-f", str(profile)]
        except BaseException:
            self.close()
            raise

    def excluded(self, rel):
        return rel.is_absolute() or ".." in rel.parts or any(fnmatch.fnmatch(str(rel), pattern)
                     or any(fnmatch.fnmatch(part, pattern) for part in rel.parts) for pattern in self.exclude)

    def edits(self):
        names = set(self.before)
        for p in self.stage.rglob("*"):
            rel = p.relative_to(self.stage)
            if self.excluded(rel):
                continue
            if p.is_symlink():
                raise ChangeError("UNSUPPORTED_FILE", "외부 CLI가 심볼릭 링크를 만들었습니다")
            if p.is_file():
                names.add(str(rel))
            if len(names) > 10000:
                raise ChangeError("WORKSPACE_TOO_LARGE", "외부 CLI 결과 파일 상한 초과")
        edits = []
        for name in sorted(names):
            p = self.stage / name
            if p.exists() and (not p.is_file() or p.stat().st_size > MAX_FILE_BYTES):
                raise ChangeError("UNSUPPORTED_FILE", "지원하지 않는 외부 CLI 변경")
            if p.exists() and name in self.modes and (p.stat().st_mode & 0o777) != self.modes[name]:
                raise ChangeError("UNSUPPORTED_FILE", "외부 CLI 파일 모드 변경은 지원하지 않습니다")
            data = p.read_bytes() if p.exists() else None
            h = digest(data) if data is not None else None
            if h != self.before.get(name):
                edits.append({"path": name, "content": data, "expected_hash": self.before.get(name)})
        return edits

    def close(self):
        self.temp.cleanup()
