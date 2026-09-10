"""스킬 로더: 기본→사용자→프로젝트 우선순위, SKILL.md 파싱.

시스템 OS 설정에 따라 한국어/영어를 자동 감지하며, 간결한 설명을 제공합니다.
프로젝트에 새 스킬이 있다는 이유만으로 명령을 자동 실행하지 않는다.
스킬 열람은 명시적 실행(/skills, skill_read)으로 제한한다.
"""
from __future__ import annotations

import locale
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def detect_system_language() -> str:
    """시스템 OS 설정 또는 환경 변수에 따라 'ko' 또는 'en'을 반환한다."""
    override = os.environ.get("TALO_LANG") or os.environ.get("TALO_LOCALE")
    if override:
        return "ko" if "ko" in override.lower() else "en"

    # macOS 시스템 기본 설정 확인
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["defaults", "read", "-g", "AppleLocale"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip().lower()
            if "ko" in out:
                return "ko"
            if "en" in out:
                return "en"
        except Exception:
            pass

        try:
            out = subprocess.check_output(
                ["defaults", "read", "-g", "AppleLanguages"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip().lower()
            if "ko" in out:
                return "ko"
            if "en" in out:
                return "en"
        except Exception:
            pass

    for env in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(env)
        if val:
            val_lower = val.lower()
            if "ko" in val_lower:
                return "ko"
            if "en" in val_lower:
                return "en"

    try:
        loc = locale.getlocale()[0]
        if loc and "ko" in loc.lower():
            return "ko"
    except Exception:
        pass

    return "en"


BUILTIN_SKILLS: dict[str, dict[str, Any]] = {
    "repo_understand": {
        "name": "repo_understand",
        "title": "저장소 파악",
        "title_ko": "저장소 파악",
        "title_en": "Understand Repository",
        "description": "프로젝트 구조·의존성·코드 파악",
        "description_ko": "프로젝트 구조·의존성·코드 파악",
        "description_en": "Analyze repo structure & code",
        "goal": "요청과 관련된 코드 위치와 의존 관계를 근거와 함께 제시한다.",
        "goal_ko": "요청과 관련된 코드 위치와 의존 관계를 근거와 함께 제시한다.",
        "goal_en": "Identify relevant code locations and dependencies with rationale.",
        "steps": ["구조 파악", "관련 파일 검색", "의존·진입점 확인", "요약 보고"],
        "steps_ko": ["구조 파악", "관련 파일 검색", "의존·진입점 확인", "요약 보고"],
        "steps_en": ["Understand structure", "Search relevant files", "Check dependencies", "Summary report"],
        "tools": ["file_list", "file_search", "file_read", "git_log"],
        "completion": "관련 파일·모듈·남은 확인 항목이 보고됨",
        "completion_ko": "관련 파일·모듈·남은 확인 항목이 보고됨",
        "completion_en": "Relevant files, modules, and next steps reported",
    },
    "fix_error": {
        "name": "fix_error",
        "title": "오류 수정",
        "title_ko": "오류 수정",
        "title_en": "Fix Error",
        "description": "오류 원인 파악 및 수정·검증",
        "description_ko": "오류 원인 파악 및 수정·검증",
        "description_en": "Diagnose, fix, and verify errors",
        "goal": "원인을 특정하고 최소 수정 후 검증 결과를 보고한다.",
        "goal_ko": "원인을 특정하고 최소 수정 후 검증 결과를 보고한다.",
        "goal_en": "Isolate root cause, make minimal fix, and report verification.",
        "steps": ["오류 재현", "원인 파악", "수정", "검증", "결과 정리"],
        "steps_ko": ["오류 재현", "원인 파악", "수정", "검증", "결과 정리"],
        "steps_en": ["Reproduce error", "Identify cause", "Apply fix", "Verify", "Organize results"],
        "tools": ["file_search", "file_read", "file_patch", "command_run", "git_diff"],
        "completion": "변경 이유·파일·검증 결과·남은 문제가 보고됨",
        "completion_ko": "변경 이유·파일·검증 결과·남은 문제가 보고됨",
        "completion_en": "Root cause, files, verification results, and remaining issues reported",
    },
    "implement_feature": {
        "name": "implement_feature",
        "title": "기능 구현",
        "title_ko": "기능 구현",
        "title_en": "Implement Feature",
        "description": "요구사항 구현 및 검증",
        "description_ko": "요구사항 구현 및 검증",
        "description_en": "Implement requirements and verify",
        "goal": "요구 범위를 구현하고 검증 근거와 함께 보고한다.",
        "goal_ko": "요구 범위를 구현하고 검증 근거와 함께 보고한다.",
        "goal_en": "Implement scoped requirements with verification evidence.",
        "steps": ["범위 파악", "설계", "구현", "검증", "결과 정리"],
        "steps_ko": ["범위 파악", "설계", "구현", "검증", "결과 정리"],
        "steps_en": ["Scope requirements", "Design", "Implement", "Verify", "Summarize results"],
        "tools": ["file_search", "file_read", "file_write", "file_patch", "command_run", "git_diff"],
        "completion": "구현 파일·검증 결과·남은 일이 보고됨",
        "completion_ko": "구현 파일·검증 결과·남은 일이 보고됨",
        "completion_en": "Implemented files, verification results, and next steps reported",
    },
    "review_changes": {
        "name": "review_changes",
        "title": "변경 검토",
        "title_ko": "변경 검토",
        "title_en": "Review Changes",
        "description": "작업 변경 검토 및 위험 분석",
        "description_ko": "작업 변경 검토 및 위험 분석",
        "description_en": "Review diffs and assess risks",
        "goal": "이번 작업 변경을 식별하고 위험·검증 상태를 보고한다.",
        "goal_ko": "이번 작업 변경을 식별하고 위험·검증 상태를 보고한다.",
        "goal_en": "Identify current changes and report risk and verification status.",
        "steps": ["변경 구분", "차이 확인", "위험 검토", "보고"],
        "steps_ko": ["변경 구분", "차이 확인", "위험 검토", "보고"],
        "steps_en": ["Identify changes", "Inspect diff", "Assess risk", "Report findings"],
        "tools": ["git_status", "git_diff", "file_read"],
        "completion": "이번 변경 목록과 검토 의견이 보고됨",
        "completion_ko": "이번 변경 목록과 검토 의견이 보고됨",
        "completion_en": "List of changes and review comments reported",
    },
}

KNOWN_SKILL_LOCALIZATION: dict[str, dict[str, str]] = {
    "airtable": {
        "ko": "Airtable REST API 레코드 관리 (CRUD, 필터)",
        "en": "Manage Airtable records via REST API (CRUD, filters)",
    },
    "apple-notes": {
        "ko": "memo CLI로 Apple 메모 생성·검색·편집",
        "en": "Manage Apple Notes via memo CLI",
    },
    "apple-reminders": {
        "ko": "remindctl로 Apple 미리알림 관리",
        "en": "Manage Apple Reminders via remindctl",
    },
    "architecture-diagram": {
        "ko": "SVG 아키텍처/인프라 다이어그램 생성",
        "en": "Generate SVG architecture & infra diagrams",
    },
    "arxiv": {
        "ko": "arXiv 논문 검색 (키워드, 저자, 카테고리)",
        "en": "Search arXiv papers by keyword, author, or category",
    },
    "ascii-video": {
        "ko": "비디오/오디오를 컬러 ASCII MP4/GIF로 변환",
        "en": "Convert video/audio to colored ASCII MP4/GIF",
    },
    "baoyu-infographic": {
        "ko": "다양한 레이아웃과 스타일의 인포그래픽 생성",
        "en": "Generate infographics in diverse layouts & styles",
    },
    "blocked-page-recovery": {
        "ko": "403/429, WAF, 봇 차단 페이지 우회 및 복구",
        "en": "Bypass & recover from 403/429, WAF, bot blocks",
    },
    "box": {
        "ko": "Box 클라우드 파일 관리, 공유 및 검색",
        "en": "Manage, share, and search Box cloud files",
    },
    "claude-code": {
        "ko": "Claude Code CLI로 코딩 및 아키텍처 작업 위임",
        "en": "Delegate coding workflows to Claude Code CLI",
    },
    "claude-design": {
        "ko": "단일 HTML 아티팩트 디자인 (랜딩, 프로토타입)",
        "en": "Design single HTML artifacts (landing, prototype)",
    },
    "codebase-inspection": {
        "ko": "pygount 기반 코드베이스 라인수/언어 통계 검사",
        "en": "Inspect codebase LOC & language statistics via pygount",
    },
    "codex": {
        "ko": "OpenAI Codex CLI로 코딩 및 리팩토링 위임",
        "en": "Delegate coding & refactoring to Codex CLI",
    },
    "competitor-news-monitor": {
        "ko": "기업 주요 뉴스 모니터링 및 출처 요약",
        "en": "Monitor company news and cited digests",
    },
    "computer-use": {
        "ko": "데스크톱 UI 자동화 및 화면 제어",
        "en": "Automate desktop UI and control screen",
    },
    "design-md": {
        "ko": "DESIGN.md 디자인 토큰 사양 작성·검증",
        "en": "Author & validate DESIGN.md token specs",
    },
    "document-to-action-items": {
        "ko": "문서에서 마감일, 할 일 및 액션 아이템 추출",
        "en": "Extract deadlines and action items from docs",
    },
    "docx": {
        "ko": "Word .docx 파일 생성, 편집 및 템플릿 처리",
        "en": "Create, read, and edit Word .docx files",
    },
    "dogfood": {
        "ko": "웹 애플리케이션 탐색적 QA 및 버그 리포트",
        "en": "Exploratory QA & bug reports for web apps",
    },
    "ego-browser": {
        "ko": "Chromium 기반 AI 격리 웹 브라우징 및 자동화",
        "en": "Chromium-based AI browser automation",
    },
    "email-inbox-triage": {
        "ko": "이메일 수신함 분류, 우선순위 지정 및 답장 초안",
        "en": "Triage inbox, prioritize threads, draft replies",
    },
    "findmy": {
        "ko": "macOS FindMy로 Apple 기기 및 AirTag 위치 조회",
        "en": "Query Apple devices and AirTags via FindMy",
    },
    "gif-search": {
        "ko": "Tenor API로 GIF 검색 및 다운로드",
        "en": "Search and download GIFs from Tenor",
    },
    "github": {
        "ko": "gh CLI로 GitHub PR, 이슈, 저장소 관리",
        "en": "Manage GitHub PRs, issues, and repos via gh CLI",
    },
    "google-workspace": {
        "ko": "Gmail, Calendar, Drive, Docs, Sheets 자동화",
        "en": "Automate Gmail, Calendar, Drive, Docs, Sheets",
    },
    "grounded-citations": {
        "ko": "신뢰할 수 있는 검증 출처 기반 답변 구성",
        "en": "Ground answers in cited, verifiable sources",
    },
    "hermes-agent": {
        "ko": "Hermes 에이전트 설정, 확장 및 오케스트레이션",
        "en": "Configure, extend, and orchestrate Hermes Agent",
    },
    "hermes-agent-skill-authoring": {
        "ko": "저장소 내 SKILL.md 작성 및 구조 설계",
        "en": "Author in-repo SKILL.md specs and structure",
    },
    "himalaya": {
        "ko": "Himalaya CLI로 터미널 이메일(IMAP/SMTP) 송수신",
        "en": "Terminal email via Himalaya CLI (IMAP/SMTP)",
    },
    "humanizer": {
        "ko": "AI 어투를 자연스러운 인간 문체로 변환",
        "en": "Humanize text and remove AI clichés",
    },
    "imessage": {
        "ko": "macOS imsg CLI로 iMessage/SMS 송수신 및 검색",
        "en": "Send & receive iMessages/SMS via imsg CLI",
    },
    "inspecting-hermes-desktop-dom": {
        "ko": "CDP로 Hermes 데스크톱 DOM/CSS 실시간 검사",
        "en": "Inspect Hermes desktop DOM/CSS via CDP",
    },
    "llm-wiki": {
        "ko": "상호 연결된 마크다운 지식 베이스(LLM Wiki) 구축",
        "en": "Build & query interlinked markdown knowledge base",
    },
    "manim-video": {
        "ko": "Manim CE 기반 수학/알고리즘 애니메이션 제작",
        "en": "Create math/algorithm animations with Manim CE",
    },
    "maps": {
        "ko": "지오코딩, POI, 경로 및 시간대 검색 (OSM)",
        "en": "Geocoding, POIs, routes & timezones via OSM",
    },
    "meeting-action-items": {
        "ko": "회의록에서 결정 사항 및 담당자 티켓 추출",
        "en": "Extract decisions, owners, and tickets from notes",
    },
    "node-inspect-debugger": {
        "ko": "Node.js --inspect 및 Chrome DevTools 디버깅",
        "en": "Debug Node.js via --inspect and DevTools Protocol",
    },
    "notion": {
        "ko": "Notion API로 페이지, 데이터베이스, 마크다운 관리",
        "en": "Manage Notion pages, DBs, and markdown via API",
    },
    "obsidian": {
        "ko": "Obsidian 볼트 내 노트 검색, 작성 및 편집",
        "en": "Search, create, and edit notes in Obsidian vault",
    },
    "opencode": {
        "ko": "OpenCode CLI로 코딩 및 PR 리뷰 작업 위임",
        "en": "Delegate coding and PR review to OpenCode CLI",
    },
    "p5js": {
        "ko": "p5.js 생성 예술, 셰이더 및 인터랙티브 스케치",
        "en": "Create generative art & interactive p5.js sketches",
    },
    "pdf": {
        "ko": "PDF 파일 생성, 병합, 텍스트 편집 및 OCR",
        "en": "Create, merge, edit text, and OCR PDF files",
    },
    "popular-web-designs": {
        "ko": "유명 웹 서비스(Stripe, Linear 등) 디자인 시스템 구현",
        "en": "HTML/CSS design systems from Stripe, Linear, etc.",
    },
    "powerpoint": {
        "ko": "python-pptx로 PowerPoint(.pptx) 생성 및 편집",
        "en": "Create and edit .pptx decks with python-pptx",
    },
    "product-price-monitor": {
        "ko": "상품/항공권 가격 변동 모니터링 및 알림",
        "en": "Monitor prices for products or flights with alerts",
    },
    "python-debugpy": {
        "ko": "Python pdb 및 debugpy 원격 디버깅 (DAP)",
        "en": "Debug Python via pdb and remote debugpy (DAP)",
    },
    "requesting-code-review": {
        "ko": "커밋 전 코드 보안 검사 및 품질 리뷰",
        "en": "Pre-commit review, security scan, and auto-fix",
    },
    "sdlc-review": {
        "ko": "칸반 핸드오프 검토 및 검증 결과 라우팅",
        "en": "Review Kanban handoffs and route verified outcomes",
    },
    "simplify-code": {
        "ko": "최근 코드 변경점 리팩토링 및 정리",
        "en": "Refactor and simplify recent code changes",
    },
    "songsee": {
        "ko": "CLI 오디오 스펙트로그램 및 음향 특징 분석",
        "en": "Audio spectrograms & feature analysis via CLI",
    },
    "songwriting-and-ai-music": {
        "ko": "작사 및 Suno AI 음악 프롬프트 제작",
        "en": "Songwriting craft and Suno AI music prompts",
    },
    "spike": {
        "ko": "사전 타당성 검증을 위한 일회성 실험 구현",
        "en": "Throwaway experiments to validate ideas before build",
    },
    "systematic-debugging": {
        "ko": "4단계 체계적 원인 분석 및 디버깅",
        "en": "4-phase systematic root cause debugging",
    },
    "teams-meeting-pipeline": {
        "ko": "Teams 회의 요약 및 Graph API 파이프라인",
        "en": "Teams meeting summaries & Graph API pipeline",
    },
    "test-driven-development": {
        "ko": "TDD: Red-Green-Refactor 테스트 주도 개발",
        "en": "TDD: Red-Green-Refactor test-driven development",
    },
    "weekly-review-planning": {
        "ko": "주간 업무 정리, 정체 작업 점검 및 계획 수립",
        "en": "Weekly reset, stalled work review, and planning",
    },
    "xlsx": {
        "ko": "Excel .xlsx 워크북 및 CSV 파일 생성·편집",
        "en": "Create, read, and edit Excel .xlsx & CSV files",
    },
    "xurl": {
        "ko": "xurl CLI로 X/트위터 포스팅, 검색, DM 관리",
        "en": "X/Twitter posting, search, and DMs via xurl CLI",
    },
    "youtube-content": {
        "ko": "YouTube 자막 추출 및 요약·블로그 변환",
        "en": "YouTube transcripts to summaries, threads, blogs",
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
    lang: str = "ko"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "title": self.title, "description": self.description,
            "origin": self.origin, "goal": self.goal, "steps": self.steps,
            "tools": self.tools, "completion": self.completion, "version": self.version,
            "body": self.body, "lang": self.lang,
        }


class SkillLoader:
    def __init__(self, user_skills_dir: Path, project_skills_dir: Path | None = None, lang: str | None = None):
        self.user_skills_dir = user_skills_dir
        self.project_skills_dir = project_skills_dir
        self.lang = lang or detect_system_language()
        self._list_cache: list[dict[str, Any]] | None = None
        self._list_cache_key: tuple[Any, ...] | None = None

    def list_skills(self) -> list[dict[str, Any]]:
        cache_key = tuple(
            (str(base), base.stat().st_mtime_ns if base and base.exists() else None)
            for base in (self.user_skills_dir, self.project_skills_dir)
        )
        if self._list_cache is not None and cache_key == self._list_cache_key:
            return [dict(skill) for skill in self._list_cache]
        skills: dict[str, Skill] = {}
        # 기본 → 사용자 → 프로젝트 우선순위 (뒤가 덮어씀)
        for name, meta in BUILTIN_SKILLS.items():
            title = meta.get(f"title_{self.lang}") or meta.get("title", name)
            desc = meta.get(f"description_{self.lang}") or meta.get("description", "")
            goal = meta.get(f"goal_{self.lang}") or meta.get("goal", "")
            steps = meta.get(f"steps_{self.lang}") or meta.get("steps", [])
            completion = meta.get(f"completion_{self.lang}") or meta.get("completion", "")
            skills[name] = Skill(
                name=name, title=title, description=desc,
                body=meta.get("body", _builtin_body(meta, self.lang)), origin="builtin",
                goal=goal, steps=steps,
                tools=meta.get("tools", []), completion=completion,
                lang=self.lang,
            )
        for origin, base in (("user", self.user_skills_dir), ("project", self.project_skills_dir)):
            if base is None:
                continue
            for skill in _load_from_dir(base, origin, lang=self.lang):
                skills[skill.name] = skill
        result = [s.to_dict() for s in skills.values()]
        self._list_cache_key = cache_key
        self._list_cache = result
        return [dict(skill) for skill in result]

    def load_skill(self, name: str) -> dict[str, Any] | None:
        for s in self.list_skills():
            if s["name"] == name:
                return s
        return None

    def builtin_names(self) -> list[str]:
        return list(BUILTIN_SKILLS)


def _builtin_body(meta: dict[str, Any], lang: str = "ko") -> str:
    title_ko = meta.get("title_ko") or meta.get("title", "")
    title_en = meta.get("title_en") or meta.get("title", "")
    desc = meta.get(f"description_{lang}") or meta.get("description", "")
    goal = meta.get(f"goal_{lang}") or meta.get("goal", "")
    steps = meta.get(f"steps_{lang}") or meta.get("steps", [])
    tools = meta.get("tools", [])
    completion = meta.get(f"completion_{lang}") or meta.get("completion", "")

    if lang == "en":
        title_header = f"# {title_en} ({title_ko})" if title_ko and title_ko != title_en else f"# {title_en}"
        lines = [
            title_header,
            "",
            desc,
            "",
            "## Goal",
            goal,
            "",
            "## Steps",
        ]
        lines += [f"{i + 1}. {s}" for i, s in enumerate(steps)]
        lines += ["", "## Required Tools", ", ".join(tools)]
        lines += ["", "## Completion Criteria", completion]
    else:
        lines = [
            f"# {title_ko}",
            "",
            desc,
            "",
            "## 목표",
            goal,
            "",
            "## 단계",
        ]
        lines += [f"{i + 1}. {s}" for i, s in enumerate(steps)]
        lines += ["", "## 필요한 도구", ", ".join(tools)]
        lines += ["", "## 완료 조건", completion]

    return "\n".join(lines)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _load_from_dir(base: Path, origin: str, lang: str = "ko") -> list[Skill]:
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
                    meta[k.strip()] = v.strip().strip("\"'")
        name = meta.get("name") or skill_md.parent.name

        # 언어별 설명 및 간결화 처리
        known = KNOWN_SKILL_LOCALIZATION.get(name, {})
        if lang == "ko":
            desc = meta.get("description_ko") or known.get("ko") or meta.get("description", "")
            title = meta.get("title_ko") or meta.get("title", name)
        else:
            desc = meta.get("description_en") or known.get("en") or meta.get("description", "")
            title = meta.get("title_en") or meta.get("title", name)

        # 설명이 너무 길 경우 가급적 짧게 요약
        if len(desc) > 80:
            first_sentence = re.split(r"[.\n]", desc)[0].strip()
            desc = first_sentence if first_sentence and len(first_sentence) <= 80 else desc[:77] + "..."

        out.append(Skill(
            name=name,
            title=title,
            description=desc,
            body=body.strip(),
            origin=origin,
            version=meta.get("version", "1"),
            lang=lang,
        ))
    return out
