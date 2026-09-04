"""CLI 인자·doctor·스킬·컨텍스트 테스트."""
from __future__ import annotations

import json

from talo.cli.main import build_parser
from talo.context.engine import ContextBlock, ContextEngine, estimate_tokens
from talo.skills.loader import SkillLoader


def test_parser_commands():
    parser = build_parser()
    args = parser.parse_args(["run", "요청", "--plan", "--json"])
    assert args.command == "run" and args.plan and args.json
    args = parser.parse_args(["resume", "ses_abc"])
    assert args.command == "resume" and args.session_id == "ses_abc"
    args = parser.parse_args(["connect", "use", "openrouter_1:model"])
    assert args.command == "connect" and args.action == "use" and args.target == "openrouter_1:model"
    args = parser.parse_args(["doctor"])
    assert args.command == "doctor"


def test_context_engine_handoff():
    engine = ContextEngine()
    blocks = [ContextBlock("기본 규칙", "규칙 내용"), ContextBlock("도구", "file_read")]
    assembled = engine.assemble(blocks, [{"role": "user", "content": "안녕"}])
    assert assembled.estimated_tokens > 0
    assert set(assembled.block_hashes) == {"기본 규칙", "도구"}
    handoff = engine.handoff_document(
        identity={"session_id": "s1"}, goal="목표", constraints={}, decisions=[],
        workspace={}, execution=[], verification=[], next_actions=["다음"],
        context_sources=["session:s1"],
    )
    assert handoff["schema"] == "talo.handoff/0.1"
    assert handoff["identity"]["session_id"] == "s1"


def test_context_compact_preserves_recent():
    engine = ContextEngine()
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(30)]
    kept, dropped, summary = engine.compact(msgs, [], max_messages=10)
    assert len(kept) == 11  # 요약 블록 + 최근 10
    assert len(dropped) == 20
    assert "이전 대화" in kept[0]["content"]


def test_builtin_skills_loaded(tmp_path):
    loader = SkillLoader(tmp_path, None)
    skills = loader.list_skills()
    names = {s["name"] for s in skills}
    assert {"repo_understand", "fix_error", "implement_feature", "review_changes"} <= names
    skill = loader.load_skill("fix_error")
    assert skill and skill["origin"] == "builtin"
    assert "오류 수정" in skill["body"]


def test_project_skill_overrides_builtin(tmp_path):
    (tmp_path / "fix_error").mkdir(parents=True, exist_ok=True)
    (tmp_path / "fix_error" / "SKILL.md").write_text(
        "---\nname: fix_error\ndescription: 프로젝트 전용 오류 수정 절차\n---\n# 프로젝트 절차\n",
        encoding="utf-8",
    )
    loader = SkillLoader(tmp_path, None)
    skill = loader.load_skill("fix_error")
    assert skill["origin"] == "user"
    assert "프로젝트 절차" in skill["body"]


def test_estimate_tokens_cjk():
    assert estimate_tokens("") == 0
    assert estimate_tokens("한글") == 2
    assert estimate_tokens("hello") == 1  # 5자/4 → 1
