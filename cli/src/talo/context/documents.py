"""문서 및 파일 경로 인식·멘션 확장 유틸리티."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# 파일 멘션 패턴: @경로 (예: @docs/plan.md, @/Users/.../file.txt)
FILE_MENTION_RE = re.compile(r"@(?P<path>[^\s,;]+)")

# 텍스트 파일로 취급할 일반적인 확장자
TEXT_EXTENSIONS = {
    ".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml", ".rst",
    ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss", ".sh",
    ".bash", ".zsh", ".sql", ".graphql", ".env", ".xml", ".csv",
    ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".java", ".kt", ".swift",
    ".rb", ".php", ".proto", ".ini", ".cfg", ".conf",
}


def is_document_path(candidate: str, base_dir: Path | None = None) -> bool:
    """문서나 소스 파일 경로인지 검사."""
    cleaned = candidate.strip().strip("'\"")
    if cleaned.startswith("@"):
        cleaned = cleaned[1:].strip()
    if not cleaned:
        return False
    base = (base_dir or Path.cwd()).resolve()
    p = Path(cleaned).expanduser()
    target = p if p.is_absolute() else (base / p)
    return target.is_file()


def read_file_safe(file_path: Path, max_chars: int = 50_000) -> dict[str, Any]:
    """파일을 안전하게 텍스트로 읽는다. 바이너리이거나 크기가 큰 경우 처리."""
    p = file_path.expanduser().resolve()
    if not p.exists():
        return {"ok": False, "error": f"파일을 찾을 수 없습니다: {file_path}"}
    if not p.is_file():
        return {"ok": False, "error": f"파일이 아닙니다: {file_path}"}

    try:
        raw = p.read_bytes()
        if b"\x00" in raw[:1024]:
            return {"ok": False, "error": f"바이너리 파일은 텍스트로 읽을 수 없습니다: {p.name}"}
        text = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": f"파일 읽기 오류 ({p.name}): {exc}"}

    lines = text.splitlines()
    total_lines = len(lines)
    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True

    return {
        "ok": True,
        "path": str(p),
        "name": p.name,
        "size": len(raw),
        "total_lines": total_lines,
        "content": text,
        "truncated": truncated,
    }


def resolve_document_request(
    request: str,
    base_dir: Path | None = None,
    repo_root: Path | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """요청 문자열에서 문서 경로 / @멘션을 찾아 내용을 첨부한 프롬프트로 변환한다.

    반환:
        (변환된_요청, 로드된_문서_목록)
    """
    base = (base_dir or Path.cwd()).resolve()
    root = (repo_root or base).resolve()
    raw = request.strip()
    if not raw:
        return request, []

    # 1. 요청 전체가 순수 파일 경로인 경우 (예: "docs/plan.md", "@/Users/.../foo.md")
    path_candidate = raw[1:].strip() if raw.startswith("@") else raw
    # 따옴표 제거
    path_candidate = path_candidate.strip("'\"")
    p = Path(path_candidate).expanduser()
    target = p if p.is_absolute() else (base / p)
    if target.is_file():
        info = read_file_safe(target)
        if info["ok"]:
            try:
                rel = str(target.relative_to(root))
            except ValueError:
                rel = str(target)
            trunc_note = f"\n...(총 {info['total_lines']}줄 중 앞부분 {len(info['content'])}자만 표시됨)" if info["truncated"] else ""
            ext = target.suffix.lstrip(".") or "text"
            expanded = (
                f"다음 문서({rel})의 내용을 확인하고 주요 내용을 요약 및 안내해줘:\n\n"
                f"[문서: {rel} ({info['total_lines']}줄)]\n"
                f"```{ext}\n{info['content']}{trunc_note}\n```"
            )
            return expanded, [info]

    # 2. @경로 멘션 포함된 경우 (예: "@docs/plan.md 3단계 요약해줘", "이 파일 @src/main.py 리팩토링")
    loaded_docs: list[dict[str, Any]] = []
    attached_blocks: list[str] = []

    def _replace_mention(match: re.Match[str]) -> str:
        mention_path = match.group("path").strip("'\"")
        mp = Path(mention_path).expanduser()
        mtarget = mp if mp.is_absolute() else (base / mp)
        if mtarget.is_file():
            minfo = read_file_safe(mtarget)
            if minfo["ok"]:
                try:
                    mrel = str(mtarget.relative_to(root))
                except ValueError:
                    mrel = str(mtarget)
                loaded_docs.append(minfo)
                trunc_note = f"\n...(총 {minfo['total_lines']}줄 중 앞부분 {len(minfo['content'])}자만 표시됨)" if minfo["truncated"] else ""
                ext = mtarget.suffix.lstrip(".") or "text"
                attached_blocks.append(
                    f"\n\n[참조 문서: {mrel} ({minfo['total_lines']}줄)]\n"
                    f"```{ext}\n{minfo['content']}{trunc_note}\n```"
                )
                return f"`{mrel}`"
        return match.group(0)

    transformed = FILE_MENTION_RE.sub(_replace_mention, raw)
    if attached_blocks:
        transformed += "".join(attached_blocks)
        return transformed, loaded_docs

    # 3. 맨 첫 단어가 파일 경로이고 뒤에 지시문이 붙은 경우 (예: "docs/plan.md 요약해줘", "/path/to/doc.md 검토")
    parts = raw.split(maxsplit=1)
    if len(parts) == 2:
        cand = parts[0].strip().strip("'\"")
        if cand.startswith("@"):
            cand = cand[1:].strip()
        cp = Path(cand).expanduser()
        ctarget = cp if cp.is_absolute() else (base / cp)
        if ctarget.is_file():
            cinfo = read_file_safe(ctarget)
            if cinfo["ok"]:
                try:
                    crel = str(ctarget.relative_to(root))
                except ValueError:
                    crel = str(ctarget)
                trunc_note = f"\n...(총 {cinfo['total_lines']}줄 중 앞부분 {len(cinfo['content'])}자만 표시됨)" if cinfo["truncated"] else ""
                ext = ctarget.suffix.lstrip(".") or "text"
                expanded = (
                    f"{parts[1]}\n\n"
                    f"[참조 문서: {crel} ({cinfo['total_lines']}줄)]\n"
                    f"```{ext}\n{cinfo['content']}{trunc_note}\n```"
                )
                return expanded, [cinfo]

    return request, []
