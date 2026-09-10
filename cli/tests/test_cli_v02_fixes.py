"""Talo v0.2 버그 수정 및 기능 개선 단위 테스트."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from talo.changes.matcher import replacement
from talo.cli.interactive import _handle_slash_interactive
from talo.cli.main import main
from talo.service import serve


def test_matcher_no_double_newline():
    """new가 이미 줄바꿈을 포함할 때 중복 줄바꿈이 생기지 않는지 검증."""
    # 1. CRLF 환경에서 3줄 이상 fuzzy 매칭 시 new 끝 줄바꿈 중복 방지
    source = "def foo():\r\n    a = 1\r\n    return a\r\n"
    old = "def foo():\n    a = 1\n    return a"
    new = "def foo():\r\n    a = 2\r\n    return a\r\n"
    res, method = replacement(source, old, new)
    assert not res.endswith("\r\n\r\n")
    assert res == "def foo():\r\n    a = 2\r\n    return a\r\n"

    # 2. new 끝에 줄바꿈이 없을 때는 원본 블록의 줄바꿈 복원
    new_no_newline = "def foo():\r\n    a = 2\r\n    return a"
    res2, method2 = replacement(source, old, new_no_newline)
    assert res2 == "def foo():\r\n    a = 2\r\n    return a\r\n"


def test_changes_cancel_and_recover_missing_id(tmp_path, monkeypatch, capsys):
    """changes cancel / recover 실행 시 ID가 없으면 명확한 오류 반환."""
    monkeypatch.setenv("TALO_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    code = main(["changes", "cancel"])
    assert code == 1
    out = capsys.readouterr().out
    assert "INVALID_ACTION: 변경 ID가 필요합니다" in out

    code2 = main(["changes", "recover"])
    assert code2 == 1
    out2 = capsys.readouterr().out
    assert "INVALID_ACTION: 변경 ID가 필요합니다" in out2


def test_tasks_done_validation_and_empty_list(tmp_path, monkeypatch, capsys):
    """tasks done의 인자 유효성 검사 및 빈 작업 목록 안내 검증."""
    monkeypatch.setenv("TALO_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    # 1. 빈 작업 목록
    code = main(["tasks", "list"])
    assert code == 0
    assert "열린 작업이 없습니다." in capsys.readouterr().out

    # 2. task_id 누락된 done
    code = main(["tasks", "done"])
    assert code == 2
    assert "작업 ID가 필요합니다" in capsys.readouterr().err


def test_service_tasks_done(tmp_path, monkeypatch, capsys):
    """talo serve에서 tasks.done RPC 정상 동작 검증."""
    from talo.application.service import create_app_context
    from talo.continuity import begin_task

    monkeypatch.setenv("TALO_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()

    ctx = create_app_context(repo)
    tid = begin_task(ctx.repository, ctx.workspace_id, "sess_1", "run_1", "테스트 작업")
    ctx.close()

    # stdio tasks.done 요청
    req = {
        "version": 1,
        "id": "req-done-1",
        "method": "tasks.done",
        "cwd": str(repo),
        "params": {"task_id": tid, "evidence": "테스트 검증 완료"},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(req) + "\n"))
    assert serve() == 0

    resp = json.loads(capsys.readouterr().out.strip())
    assert resp["type"] == "result"
    assert resp["result"]["ok"] is True
    assert resp["result"]["status"] == "done"

    # 상태 확인
    ctx = create_app_context(repo)
    task_row = ctx.repository.conn.execute("SELECT * FROM work_tasks WHERE id=?", (tid,)).fetchone()
    assert task_row["status"] == "done"
    assert task_row["evidence"] == "테스트 검증 완료"
    ctx.close()


def test_interactive_tasks_done(tmp_path, monkeypatch, capsys):
    """대화형 /tasks done 명령 검증."""
    from talo.application.service import create_app_context
    from talo.continuity import begin_task

    monkeypatch.setenv("TALO_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()

    ctx = create_app_context(repo)
    tid = begin_task(ctx.repository, ctx.workspace_id, "sess_1", "run_1", "대화형 테스트 작업")

    # 1. 인자 누락
    _handle_slash_interactive(ctx, "sess_1", "/tasks done")
    assert "사용법: /tasks done" in capsys.readouterr().out

    # 2. 정상 완료 처리
    _handle_slash_interactive(ctx, "sess_1", f"/tasks done {tid} 대화형 확인 근거")
    assert f"작업 완료 처리됨: {tid}" in capsys.readouterr().out

    task_row = ctx.repository.conn.execute("SELECT * FROM work_tasks WHERE id=?", (tid,)).fetchone()
    assert task_row["status"] == "done"
    assert task_row["evidence"] == "대화형 확인 근거"
    ctx.close()


def test_document_path_and_mention_resolution(tmp_path):
    """문서 단독 경로, @멘션, 경로+지시문 처리 검증."""
    from talo.context.documents import resolve_document_request

    doc_file = tmp_path / "plan.md"
    doc_file.write_text("# 계획서\n1단계: 설계\n2단계: 구현\n", encoding="utf-8")

    # 1. 단독 문서 경로
    expanded1, docs1 = resolve_document_request("plan.md", base_dir=tmp_path)
    assert len(docs1) == 1
    assert docs1[0]["name"] == "plan.md"
    assert "계획서" in expanded1
    assert "1단계: 설계" in expanded1

    # 2. @멘션 형태
    expanded2, docs2 = resolve_document_request("@plan.md 핵심 요약해줘", base_dir=tmp_path)
    assert len(docs2) == 1
    assert "`plan.md` 핵심 요약해줘" in expanded2
    assert "2단계: 구현" in expanded2

    # 3. 경로 + 지시문 형태
    expanded3, docs3 = resolve_document_request("plan.md 내용 검토", base_dir=tmp_path)
    assert len(docs3) == 1
    assert "내용 검토" in expanded3
    assert "1단계: 설계" in expanded3


def test_preprocess_argv_file_path_and_commands():
    """서브커맨드 없는 파일 경로/프롬프트가 run 요청으로 자동 변환되는지 검증."""
    from talo.cli.main import preprocess_argv

    # 1. 문서 경로 단독
    assert preprocess_argv(["docs/plan.md"]) == ["run", "docs/plan.md"]

    # 2. 문서 경로 + 지시문 + 플래그
    assert preprocess_argv(["docs/plan.md", "요약해줘", "--plan"]) == ["run", "docs/plan.md 요약해줘", "--plan"]

    # 3. 인자가 있는 플래그 유지
    assert preprocess_argv(["docs/plan.md", "--model", "openai_gpt:gpt-4"]) == ["run", "docs/plan.md", "--model", "openai_gpt:gpt-4"]

    # 4. 기존 정상 서브커맨드 유지
    assert preprocess_argv(["run", "요청"]) == ["run", "요청"]
    assert preprocess_argv(["doctor"]) == ["doctor"]
    assert preprocess_argv(["--version"]) == ["--version"]
    assert preprocess_argv([]) == []


def test_interactive_absolute_document_path(tmp_path, capsys):
    """대화형에서 절대 경로 입력 시 slash command로 오인하지 않고 문서를 로드하는지 검증."""
    from talo.application.service import create_app_context

    doc_file = tmp_path / "spec.md"
    doc_file.write_text("# 스펙 문서\n기능 A 구현 완료\n", encoding="utf-8")

    ctx = create_app_context(tmp_path)
    # 절대 파일 경로 입력
    res = _handle_slash_interactive(ctx, "sess_1", str(doc_file))
    assert res is not None
    assert "run_request" in res
    assert "기능 A 구현 완료" in res["run_request"]
    out = capsys.readouterr().out
    assert "문서 로드됨: spec.md" in out
    assert "알 수 없는 명령" not in out

    # 존재하지 않는 파일 경로
    res_not_found = _handle_slash_interactive(ctx, "sess_1", "/nonexistent/path/document.md")
    assert res_not_found is None
    out_nf = capsys.readouterr().out
    assert "파일을 찾을 수 없습니다" in out_nf
    assert "알 수 없는 명령" not in out_nf

    # 실제 알 수 없는 slash 명령
    res_unknown = _handle_slash_interactive(ctx, "sess_1", "/unknowncmd")
    assert res_unknown is None
    out_uk = capsys.readouterr().out
    assert "알 수 없는 명령: /unknowncmd" in out_uk
    ctx.close()


def test_file_read_allows_external_file(tmp_path):
    """프로젝트 외부 파일도 file_read에서 안전하게 조회 가능한지 검증."""
    import asyncio
    from talo.application.service import create_app_context
    from talo.tools.builtin import file_read
    from talo.tools.spec import ToolContext

    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    ext_file = external / "external_doc.md"
    ext_file.write_text("외부 참조 문서 내용\n두 번째 줄\n", encoding="utf-8")

    tool_ctx = ToolContext(
        repo_root=repo,
        workdir=repo,
        project_id="p1",
        session_id="s1",
        run_id="r1",
        artifacts_dir=tmp_path,
    )

    res = asyncio.run(file_read(tool_ctx, str(ext_file)))
    assert res["ok"] is True
    assert "외부 참조 문서 내용" in res["content"]
    assert res["total_lines"] == 2

