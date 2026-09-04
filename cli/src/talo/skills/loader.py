"""스킬 로더: 기본→사용자→프로젝트 우선순위, SKILL.md 파싱.

프로젝트에 새 스킬이 있다는 이유만으로 명령을 자동 실행하지 않는다.
스킬 열람은 명시적 실행(/skills, skill_read)으로 제한한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BUILTIN_SKILLS: dict[str, dict[str, Any]] = {
    "repo_understand": {
        "name": "repo_understand",
        "title": "저장소 파악",
        "description": "프로젝트 구조·기술 스택·주요 모듈·변경 지점을 파악한다.",
        "goal": "요청과 관련된 코드 위치와 의존 관계를 근거와 함께 제시한다.",
        "steps": ["구조 파악", "관련 파일 검색", "의존·진입점 확인", "요약 보고"],
        "tools": ["file_list", "file_search", "file_read", "git_log"],
        "completion": "관련 파일·모듈·남은 확인 항목이 보고됨",
    },
    "fix_error": {
        "name": "fix_error",
        "title": "오류 수정",
        "description": "재현·원인 파악·수정·검증 순서로 오류를 고친다.",
        "goal": "원인을 특정하고 최소 수정 후 검증 결과를 보고한다.",
        "steps": ["오류 재현", "원인 파악", "수정", "검증", "결과 정리"],
        "tools": ["file_search", "file_read", "file_patch", "command_run", "git_diff"],
        "completion": "변경 이유·파일·검증 결과·남은 문제가 보고됨",
    },
    "implement_feature": {
        "name": "implement_feature",
        "title": "기능 구현",
        "description": "요구사항을 범위로 나눠 구현하고 검증한다.",
        "goal": "요구 범위를 구현하고 검증 근거와 함께 보고한다.",
        "steps": ["범위 파악", "설계", "구현", "검증", "결과 정리"],
        "tools": ["file_search", "file_read", "file_write", "file_patch", "command_run", "git_diff"],
        "completion": "구현 파일·검증 결과·남은 일이 보고됨",
    },
    "review_changes": {
        "name": "review_changes",
        "title": "변경 검토",
        "description": "작업 변경과 기존 변경을 구분해 검토한다.",
        "goal": "이번 작업 변경을 식별하고 위험·검증 상태를 보고한다.",
        "steps": ["변경 구분", "차이 확인", "위험 검토", "보고"],
        "tools": ["git_status", "git_diff", "file_read"],
        "completion": "이번 변경 목록과 검토 의견이 보고됨",
    },
}


@dataclass
class Skill:
    name: str
    title: str
    description: str
    body: str
    origin: str
    goal: str = ""
    steps: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    completion: str = ""
    version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "title": self.title, "description": self.description,
            "origin": self.origin, "goal": self.goal, "steps": self.steps,
            "tools": self.tools, "completion": self.completion, "version": self.version,
            "body": self.body,
        }


class SkillLoader:
    def __init__(self, user_skills_dir: Path, project_skills_dir: Path | None = None):
        self.user_skills_dir = user_skills_dir
        self.project_skills_dir = project_skills_dir

    def list_skills(self) -> list[dict[str, Any]]:
        skills: dict[str, Skill] = {}
        # 기본 → 사용자 → 프로젝트 우선순위 (뒤가 덮어씀)
        for name, meta in BUILTIN_SKILLS.items():
            skills[name] = Skill(
                name=name, title=meta["title"], description=meta["description"],
                body=meta.get("body", _builtin_body(meta)), origin="builtin",
                goal=meta.get("goal", ""), steps=meta.get("steps", []),
                tools=meta.get("tools", []), completion=meta.get("completion", ""),
            )
        for origin, base in (("user", self.user_skills_dir), ("project", self.project_skills_dir)):
            if base is None:
                continue
            for skill in _load_from_dir(base, origin):
                skills[skill.name] = skill
        return [s.to_dict() for s in skills.values()]

    def load_skill(self, name: str) -> dict[str, Any] | None:
        for s in self.list_skills():
            if s["name"] == name:
                return s
        return None

    def builtin_names(self) -> list[str]:
        return list(BUILTIN_SKILLS)


def _builtin_body(meta: dict[str, Any]) -> str:
    lines = [
        f"# {meta['title']}",
        "",
        meta["description"],
        "",
        "## 목표",
        meta.get("goal", ""),
        "",
        "## 단계",
    ]
    lines += [f"{i + 1}. {s}" for i, s in enumerate(meta.get("steps", []))]
    lines += ["", "## 필요한 도구", ", ".join(meta.get("tools", []))]
    lines += ["", "## 완료 조건", meta.get("completion", "")]
    return "\n".join(lines)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _load_from_dir(base: Path, origin: str) -> list[Skill]:
    out: list[Skill] = []
    if not base.exists():
        return out
    for skill_md in sorted(base.glob("*/SKILL.md")):
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        meta: dict[str, Any] = {}
        body = text
        m = _FRONTMATTER_RE.match(text)
        if m:
            body = text[m.end():]
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
        name = meta.get("name") or skill_md.parent.name
        out.append(Skill(
            name=name,
            title=meta.get("title", name),
            description=meta.get("description", ""),
            body=body.strip(),
            origin=origin,
            version=meta.get("version", "1"),
        ))
    return out
