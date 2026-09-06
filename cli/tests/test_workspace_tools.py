"""워크스페이스·권한·도구 테스트."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from talo.permissions.policy import Grant, PermissionPolicy, mode_and_profile
from talo.tools.spec import ToolContext
from talo.workspace.repo import Workspace


@pytest.fixture()
def git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "a.txt").write_text("hello\nworld\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)
    return tmp_path


def test_workspace_detect(git_repo):
    ws = Workspace(git_repo)
    info = ws.detect()
    assert info.is_git
    assert info.root == git_repo.resolve()
    assert info.branch in {"master", "main"}
    assert not info.is_dirty


def test_workspace_snapshot_compare(git_repo):
    ws = Workspace(git_repo)
    before = ws.snapshot()
    (git_repo / "a.txt").write_text("changed\n", encoding="utf-8")
    diff = ws.compare_snapshot(before)
    assert "a.txt" in diff["modified"]


def test_plan_mode_denies_write():
    mode, profile = mode_and_profile("plan", "project_edit")
    policy = PermissionPolicy(mode=mode, profile=profile, project_root="/tmp/repo")
    assert policy.evaluate("file_read").allowed
    assert not policy.evaluate("file_write").allowed
    assert not policy.evaluate("command_run").allowed
    # 계획 모드에서도 기획 문서 저장은 허용
    assert policy.evaluate("document_write").allowed


def test_project_edit_requires_command_approval():
    mode, profile = mode_and_profile("dev", "project_edit")
    policy = PermissionPolicy(mode=mode, profile=profile, project_root="/tmp/repo")
    assert policy.evaluate("file_patch").allowed
    decision = policy.evaluate("command_run", {"command": "pytest"})
    assert not decision.allowed and decision.requires_approval
    for tool in ("memory_confirm", "memory_update", "memory_retire"):
        memory_decision = policy.evaluate(tool)
        assert not memory_decision.allowed and memory_decision.requires_approval

    delegated_mode, delegated_profile = mode_and_profile("dev", "delegated")
    delegated = PermissionPolicy(mode=delegated_mode, profile=delegated_profile, project_root="/tmp/repo")
    assert all(delegated.evaluate(tool).allowed
               for tool in ("memory_confirm", "memory_update", "memory_retire"))


def test_grant_matches_saved_scope():
    grant = Grant(scope_json={"tool": "command_run", "project_root": "/tmp/repo",
                              "executable_pattern": "pytest"})
    policy = PermissionPolicy(grants=[grant], project_root="/tmp/repo")
    decision = policy.evaluate("command_run", {"command": "pytest tests", "executable": "pytest",
                                               "argv": ["pytest", "tests"], "cwd": "."})
    assert decision.allowed


def test_tool_path_safety(git_repo):
    ctx = ToolContext(repo_root=git_repo, workdir=git_repo, project_id="p", session_id="s",
                      run_id="r", artifacts_dir=git_repo / ".art")
    assert ctx.resolve_path("a.txt") == (git_repo / "a.txt").resolve()
    with pytest.raises(PermissionError):
        ctx.resolve_path("../outside.txt")


def test_file_read_and_patch(git_repo):
    from talo.tools import builtin

    ctx = ToolContext(repo_root=git_repo, workdir=git_repo, project_id="p", session_id="s",
                      run_id="r", artifacts_dir=git_repo / ".art")
    result = asyncio.run(builtin.file_read(ctx, "a.txt"))
    assert result["ok"] and "hello" in result["content"]

    async def approve(tool, scope):
        return True
    ctx.on_change_review = approve
    h = result["hash"]
    patched = asyncio.run(builtin.file_patch(ctx, "a.txt", "hello", "hi", expected_hash=h))
    assert patched["ok"]
    assert "hi" in (git_repo / "a.txt").read_text()

    # 해시 불일치 시 거부
    result2 = asyncio.run(builtin.file_patch(ctx, "a.txt", "hi", "yo", expected_hash="deadbeef"))
    assert not result2["ok"] and "해시" in result2["error"]


def test_command_run(git_repo):
    from talo.tools import builtin

    ctx = ToolContext(repo_root=git_repo, workdir=git_repo, project_id="p", session_id="s",
                      run_id="r", artifacts_dir=git_repo / ".art")
    result = asyncio.run(builtin.command_run(ctx, "echo hello", cwd=".", timeout=10))
    assert result["ok"] and result["exit_code"] == 0
    assert "hello" in result["stdout"]


def test_document_write(git_repo):
    from talo.tools import builtin

    ctx = ToolContext(repo_root=git_repo, workdir=git_repo, project_id="p", session_id="s",
                      run_id="r", artifacts_dir=git_repo / ".art")
    async def approve(tool, scope):
        return True
    ctx.on_change_review = approve
    result = asyncio.run(builtin.document_write(ctx, "docs/plan.md", "# 계획"))
    assert result["ok"]
    assert (git_repo / "docs" / "plan.md").exists()
