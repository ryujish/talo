"""내장 도구: 파일 검색·읽기·편집, Git, 명령 실행, 기억, 스킬.

각 함수는 ToolContext와 검증된 인자를 받아 결과 dict를 반환한다.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from talo.tools.spec import ToolContext, input_hash
from talo.workspace.repo import hash_file, run_git


def _short(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…(잘림, 전체 {len(text)}자)"


# --------------------------------------------------------------------------
# 파일 도구
# --------------------------------------------------------------------------

async def file_search(ctx: ToolContext, pattern: str, path: str = ".", max_results: int = 40) -> dict[str, Any]:
    """ripgrep 기반 검색. rg가 없으면 Python 폴백."""
    target = ctx.resolve_path(path)
    excludes = ctx.exclude_paths or []
    cmd = ["rg", "--line-number", "--no-heading", "--color", "never"]
    for ex in excludes:
        cmd += ["-g", f"!{ex}"]
    cmd += ["--", pattern, str(target)]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=str(ctx.repo_root),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": "검색 시간 초과"}
    if proc.returncode not in (0, 1):
        # rg 미설치 시 폴백
        return await _search_fallback(ctx, pattern, target, max_results)
    lines = out.decode("utf-8", "replace").splitlines()[:max_results]
    return {"ok": True, "matches": lines, "count": len(lines)}


async def _search_fallback(ctx: ToolContext, pattern: str, target: Path, max_results: int) -> dict[str, Any]:
    try:
        regex = re.compile(pattern)
    except re.error:
        regex = re.compile(re.escape(pattern))
    matches: list[str] = []
    for p in target.rglob("*") if target.is_dir() else [target]:
        if not p.is_file():
            continue
        if any(part in (ctx.exclude_paths or []) for part in p.parts):
            continue
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{p.relative_to(ctx.repo_root)}:{i}:{line}")
                    if len(matches) >= max_results:
                        return {"ok": True, "matches": matches, "count": len(matches)}
        except OSError:
            continue
    return {"ok": True, "matches": matches, "count": len(matches)}


async def file_list(ctx: ToolContext, path: str = ".", depth: int = 2) -> dict[str, Any]:
    target = ctx.resolve_path(path)
    if not target.exists():
        return {"ok": False, "error": f"경로 없음: {path}"}
    entries: list[str] = []
    base = target
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(ctx.repo_root)
        if any(part in (ctx.exclude_paths or []) for part in rel.parts):
            continue
        try:
            rel_depth = len(rel.parts)
        except ValueError:
            rel_depth = 0
        if p.is_dir() and rel_depth > depth:
            continue
        entries.append(str(rel) + ("/" if p.is_dir() else ""))
    return {"ok": True, "entries": entries[:200]}


async def file_read(ctx: ToolContext, path: str, offset: int = 0, limit: int = 400) -> dict[str, Any]:
    target = ctx.resolve_path(path)
    if not target.is_file():
        return {"ok": False, "error": f"파일이 아님: {path}"}
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    chunk = lines[offset:offset + limit]
    return {
        "ok": True,
        "path": str(target.relative_to(ctx.repo_root)),
        "offset": offset,
        "total_lines": len(lines),
        "content": "\n".join(chunk),
        "hash": hash_file(target),
    }


async def file_patch(ctx: ToolContext, path: str, old_text: str, new_text: str,
                     expected_hash: str | None = None) -> dict[str, Any]:
    """단일 파일 치환. 기대 해시 확인 후 원자적 교체."""
    target = ctx.resolve_path(path)
    if not target.is_file():
        return {"ok": False, "error": f"파일이 아님: {path}"}
    before_hash = hash_file(target)
    if expected_hash and expected_hash != before_hash:
        return {"ok": False, "error": "파일이 외부에서 변경됨(해시 불일치). 다시 읽은 뒤 적용해야 함.",
                "current_hash": before_hash}
    content = target.read_text(encoding="utf-8", errors="replace")
    if old_text not in content:
        return {"ok": False, "error": "치환 대상 텍스트를 찾지 못함. 파일이 변경되었을 수 있음."}
    if content.count(old_text) > 1:
        return {"ok": False, "error": "치환 대상이 여러 곳에서 발견됨. 더 긴 문맥을 지정해야 함."}
    updated = content.replace(old_text, new_text, 1)
    _atomic_write(target, updated)
    return {"ok": True, "path": str(target.relative_to(ctx.repo_root)),
            "before_hash": before_hash, "after_hash": hash_file(target)}


async def file_write(ctx: ToolContext, path: str, content: str, expected_hash: str | None = None) -> dict[str, Any]:
    target = ctx.resolve_path(path)
    if target.exists():
        before = hash_file(target)
        if expected_hash and expected_hash != before:
            return {"ok": False, "error": "파일이 외부에서 변경됨(해시 불일치)."}
    else:
        before = None
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, content)
    return {"ok": True, "path": str(target.relative_to(ctx.repo_root)),
            "before_hash": before, "after_hash": hash_file(target)}


async def document_write(ctx: ToolContext, path: str, content: str) -> dict[str, Any]:
    """기획 문서 저장 전용. 계획 모드에서도 허용되는 문서 범위."""
    target = ctx.resolve_path(path)
    if not (target.suffix in {".md", ".txt"} or target.name.endswith(".md")):
        return {"ok": False, "error": "document_write는 Markdown/텍스트 문서만 저장합니다."}
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, content)
    return {"ok": True, "path": str(target.relative_to(ctx.repo_root))}


def _atomic_write(target: Path, content: str) -> None:
    tmp = target.with_name(target.name + f".talo-tmp-{os.getpid()}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, target)


# --------------------------------------------------------------------------
# Git 도구
# --------------------------------------------------------------------------

async def git_status(ctx: ToolContext) -> dict[str, Any]:
    info = ctx.workspace.detect() if getattr(ctx, "workspace", None) else None
    if info is None:
        from talo.workspace.repo import Workspace
        info = Workspace(ctx.repo_root).detect()
    return {"ok": True, "status": info.summary()}


async def git_diff(ctx: ToolContext) -> dict[str, Any]:
    proc = run_git(["diff", "HEAD", "--stat"], ctx.repo_root)
    full = run_git(["diff", "HEAD"], ctx.repo_root)
    return {"ok": True, "stat": _short(proc.stdout, 4000), "diff": _short(full.stdout, 24000)}


async def git_log(ctx: ToolContext, count: int = 10) -> dict[str, Any]:
    proc = run_git(["log", "--oneline", f"-{max(1, min(count, 50))}"], ctx.repo_root)
    return {"ok": True, "log": proc.stdout if proc.returncode == 0 else ""}


# --------------------------------------------------------------------------
# 명령 실행
# --------------------------------------------------------------------------

async def command_run(ctx: ToolContext, command: str, cwd: str = ".", timeout: float = 120.0) -> dict[str, Any]:
    """고정 cwd에서 명령 실행. stdout/stderr는 아티팩트 파일에 보관하고 요약을 반환."""
    workdir = ctx.resolve_path(cwd)
    if not workdir.is_dir():
        return {"ok": False, "error": f"작업 폴더가 아님: {cwd}"}
    argv = shlex.split(command)
    if not argv:
        return {"ok": False, "error": "빈 명령"}
    started = time.time()
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        env={**os.environ, "LC_ALL": "C.UTF-8"},
    )
    ctx._current_process = proc
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await _kill_process(proc)
        return {"ok": False, "error": "명령 시간 초과", "exit_code": None, "duration": time.time() - started}
    finally:
        ctx._current_process = None
    stdout = out.decode("utf-8", "replace")
    stderr = err.decode("utf-8", "replace")
    duration = time.time() - started
    combined = stdout + ("\n[stderr]\n" + stderr if stderr.strip() else "")
    artifact_ref = None
    if len(combined) > ctx.large_output_threshold:
        artifact_ref = _store_artifact(ctx, combined, suffix=".log")
        summary = _short(combined, 2000)
    else:
        summary = combined
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "duration": round(duration, 3),
        "stdout": summary,
        "artifact_ref": artifact_ref,
        "command": command,
        "cwd": str(workdir.relative_to(ctx.repo_root)),
    }


async def command_status(ctx: ToolContext) -> dict[str, Any]:
    proc = getattr(ctx, "_current_process", None)
    if proc is None:
        return {"ok": True, "running": False}
    return {"ok": True, "running": proc.returncode is None, "pid": proc.pid}


async def _kill_process(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), 15)
        await asyncio.sleep(0.5)
        os.killpg(os.getpgid(proc.pid), 9)
    except (ProcessLookupError, PermissionError):
        pass


def _store_artifact(ctx: ToolContext, content: str, suffix: str) -> str:
    ctx.artifacts_dir.mkdir(parents=True, exist_ok=True)
    name = f"op_{input_hash({'t': time.time()})}{suffix}"
    (ctx.artifacts_dir / name).write_text(content, encoding="utf-8")
    if ctx.repository is not None:
        ctx.repository.register_artifact(name, len(content))
    return name


# --------------------------------------------------------------------------
# 기억 도구
# --------------------------------------------------------------------------

async def memory_search(ctx: ToolContext, query: str, limit: int = 10) -> dict[str, Any]:
    if ctx.repository is None:
        return {"ok": False, "error": "저장소가 연결되지 않음"}
    rows = ctx.repository.search_memories(ctx.project_id, query, limit)
    return {"ok": True, "memories": [dict(r) for r in rows]}


async def memory_propose(ctx: ToolContext, kind: str, content: str) -> dict[str, Any]:
    if ctx.repository is None:
        return {"ok": False, "error": "저장소가 연결되지 않음"}
    if kind not in {"rule", "decision", "fact", "work_note"}:
        return {"ok": False, "error": f"kind는 rule/decision/fact/work_note 중 하나여야 함: {kind}"}
    mid = ctx.repository.upsert_memory(None, ctx.project_id, kind, "proposed", content)
    return {"ok": True, "memory_id": mid, "status": "proposed"}


async def memory_confirm(ctx: ToolContext, memory_id: str) -> dict[str, Any]:
    if ctx.repository is None:
        return {"ok": False, "error": "저장소가 연결되지 않음"}
    from talo.memory.store import MemoryStore

    try:
        memory = MemoryStore(ctx.repository, ctx.project_id).confirm(memory_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "memory": memory.to_dict()}


async def memory_update(ctx: ToolContext, memory_id: str, content: str) -> dict[str, Any]:
    if ctx.repository is None:
        return {"ok": False, "error": "저장소가 연결되지 않음"}
    from talo.memory.store import MemoryStore

    try:
        memory = MemoryStore(ctx.repository, ctx.project_id).revise(memory_id, content)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "memory": memory.to_dict()}


async def memory_retire(ctx: ToolContext, memory_id: str) -> dict[str, Any]:
    if ctx.repository is None:
        return {"ok": False, "error": "저장소가 연결되지 않음"}
    from talo.memory.store import MemoryStore

    try:
        store = MemoryStore(ctx.repository, ctx.project_id)
        store.retire(memory_id)
        memory = store.repo.get_memory(memory_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "memory": dict(memory)}


# --------------------------------------------------------------------------
# 스킬 도구
# --------------------------------------------------------------------------

async def skill_list(ctx: ToolContext) -> dict[str, Any]:
    if ctx.skill_loader is None:
        return {"ok": True, "skills": []}
    skills = ctx.skill_loader.list_skills()
    return {"ok": True, "skills": skills}


async def skill_read(ctx: ToolContext, name: str) -> dict[str, Any]:
    if ctx.skill_loader is None:
        return {"ok": False, "error": "스킬 로더가 없음"}
    skill = ctx.skill_loader.load_skill(name)
    if skill is None:
        return {"ok": False, "error": f"스킬을 찾지 못함: {name}"}
    return {"ok": True, "skill": skill}
