"""일일 Markdown 일지 생성.

~/.talo/projects/<project_id>/daily/YYYY-MM-DD.md 에 오늘 작업·결정·미완료를
원자적으로 기록한다. 전날 일지의 미완료 체크박스는 이월하고, 자격 증명과
원문 전체 메시지는 정제(sanitize)한다.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from talo import paths
from talo.sanitize import redact_text


def daily_path(project_id: str, day: str | None = None) -> Path:
    d = day or date.today().isoformat()
    return paths.daily_dir(project_id) / f"{d}.md"


def _day_range(day: str) -> tuple[float, float]:
    parsed = date.fromisoformat(day)
    return time.mktime(parsed.timetuple()), time.mktime((parsed + timedelta(days=1)).timetuple())


def _previous_unchecked(project_id: str, today: str) -> list[str]:
    prev_day = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    prev_path = daily_path(project_id, prev_day)
    if not prev_path.exists():
        return []
    items: list[str] = []
    for line in prev_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- [ ]"):
            items.append(stripped[5:].strip())
    return items


def build_daily_report(ctx: Any, day: str | None = None) -> Path:
    """오늘 일지를 생성하고 원자적으로 저장한다."""
    today = day or date.today().isoformat()
    target = daily_path(ctx.project_id, today)
    target.parent.mkdir(parents=True, exist_ok=True)
    day_start, day_end = _day_range(today)

    sections: list[str] = [f"# Talo 일일 일지 — {today}", ""]

    # 1. 오늘 세션·런 (제목만, 원문 메시지 미포함)
    sections.append("## 오늘 작업")
    session_rows: list[Any] = []
    run_count = 0
    for s in ctx.repository.list_sessions(ctx.workspace_id, limit=50):
        updated = float(s["updated_at"])
        if not (day_start <= updated < day_end):
            continue
        today_runs = [r for r in ctx.repository.list_runs(s["id"])
                      if day_start <= float(r["updated_at"]) < day_end]
        if not today_runs:
            continue
        session_rows.append(s)
        run_count += len(today_runs)
        states = ", ".join(r["state"] for r in today_runs[:10])
        title = redact_text(s["title"] or "(제목 없음)", 120)
        sections.append(f"- 세션 {s['id'][:8]} — {title} — {len(today_runs)}회 ({states})")
    if not session_rows:
        sections.append("- (오늘 실행된 세션이 없음)")

    # 2. 오늘 확정·수정된 기억 (정제된 미리보기만)
    sections.append("")
    sections.append("## 오늘 결정·규칙")
    mem_lines = 0
    for m in ctx.repository.list_memories(ctx.project_id):
        updated = float(m["updated_at"])
        if not (day_start <= updated < day_end):
            continue
        if m["status"] not in ("confirmed", "superseded"):
            continue
        sections.append(f"- [{m['kind']}] {redact_text(m['content'], 120)}")
        mem_lines += 1
        if mem_lines >= 20:
            break
    if mem_lines == 0:
        sections.append("- (오늘 확정된 기억 없음)")

    # 3. 미완료 이월 (전날 체크박스 + 오늘 handoff next_actions)
    sections.append("")
    sections.append("## 미완료 작업")
    carried = _previous_unchecked(ctx.project_id, today)
    for s in session_rows:
        ho = ctx.repository.latest_handoff(s["id"])
        if ho is None:
            continue
        try:
            doc = json.loads(ho["document_json"] or "{}")
        except json.JSONDecodeError:
            doc = {}
        for na in (doc.get("next_actions") or [])[:5]:
            carried.append(f"{s['id'][:8]}: {redact_text(str(na), 120)}")
    if carried:
        for item in carried:
            sections.append(f"- [ ] {redact_text(str(item), 120)}")
    else:
        sections.append("- (미완료 작업 없음)")

    # 4. Git 변경 요약 (정제)
    sections.append("")
    sections.append("## Git 변경")
    sections.append("```")
    sections.append(redact_text(ctx.workspace.diff_stat() or "(변경 없음)", 2000))
    sections.append("```")

    # 원자 쓰기
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text("\n".join(sections) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def cmd_daily(args: Any) -> int:
    """talo daily — 오늘 일지를 생성·저장하고 경로를 출력한다."""
    from talo.application.service import create_app_context
    from talo.schemas import ExitCode

    ctx = create_app_context()
    try:
        day = getattr(args, "date", None)
        target = build_daily_report(ctx, day)
        print(target)
        return int(ExitCode.COMPLETED)
    finally:
        ctx.close()
