"""실제 파일·SQLite·프로세스 재생성을 통한 변경 및 복구 계약."""
import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from talo.changes.manager import ChangeError, ChangeManager
from talo.changes.matcher import replacement


@pytest.fixture
def manager(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return ChangeManager(root, tmp_path / "state.sqlite", tmp_path / "artifacts", "w")


def test_review_before_write_restart_and_undo(manager):
    p = manager.root / "a.txt"
    p.write_bytes(b"user's unstaged\r\n")
    p.chmod(0o755)
    c = manager.propose([{"path": "a.txt", "content": "changed\r\n"}, {"path": "new.txt", "content": "new"}])
    assert p.read_bytes() == b"user's unstaged\r\n"
    assert "user's unstaged" in manager.diff(c["id"])
    manager.apply(c["id"], c["patch_hash"])
    restarted = ChangeManager(manager.root, manager.db_path, manager.artifacts.parent, "w")
    restarted.undo(c["id"])
    assert p.read_bytes() == b"user's unstaged\r\n"
    assert p.stat().st_mode & 0o777 == 0o755
    assert not (manager.root / "new.txt").exists()
    assert restarted.undo(c["id"])["state"] == "rolled_back"


def test_stale_approval_and_user_edits(manager):
    p = manager.root / "a"
    p.write_text("original")
    c = manager.propose([{"path": "a", "content": "changed"}])
    with pytest.raises(ChangeError, match="승인 해시"):
        manager.apply(c["id"], "wrong")
    p.write_text("outside")
    with pytest.raises(ChangeError, match="해시"):
        manager.apply(c["id"], c["patch_hash"])
    assert p.read_text() == "outside"


def test_undo_preserves_later_edit(manager):
    p = manager.root / "a"
    p.write_text("original")
    c = manager.propose([{"path": "a", "content": "changed"}])
    manager.apply(c["id"], c["patch_hash"])
    p.write_text("later user edit")
    with pytest.raises(ChangeError):
        manager.undo()
    assert p.read_text() == "later user edit"


def test_crash_between_files_and_explicit_recovery(manager, monkeypatch):
    for name in ["a", "b"]:
        (manager.root / name).write_text("before")
    c = manager.propose([{"path": name, "content": "after"} for name in ["a", "b"]])
    original = manager._replace
    def crash(f, side):
        if f["path"] == "b":
            raise OSError("disk full")
        original(f, side)
    monkeypatch.setattr(manager, "_replace", crash)
    with pytest.raises(OSError):
        manager.apply(c["id"], c["patch_hash"])
    assert (manager.root / "a").read_text() == "after"
    restarted = ChangeManager(manager.root, manager.db_path, manager.artifacts.parent, "w")
    with pytest.raises(ChangeError, match="복구"):
        restarted.propose([{"path": "z", "content": "x"}])
    restarted.recover(c["id"])
    assert all((manager.root / name).read_text() == "before" for name in ["a", "b"])


def test_recovery_never_overwrites_unknown_content(manager):
    p = manager.root / "a"
    p.write_text("before")
    c = manager.propose([{"path": "a", "content": "after"}])
    manager._state(c["id"], "applying")
    p.write_text("external")
    with pytest.raises(ChangeError):
        manager.recover(c["id"])
    assert p.read_text() == "external"


def test_delete_and_duplicate_apply(manager):
    p = manager.root / "a"
    p.write_text("before")
    c = manager.propose([{"path": "a", "content": None}])
    manager.apply(c["id"], c["patch_hash"])
    assert not p.exists()
    manager.apply(c["id"], c["patch_hash"])
    manager.undo()
    assert p.read_text() == "before"


@pytest.mark.parametrize("path", ["../other", ".git/config", ".talo/project.toml"])
def test_protected_paths(manager, path):
    with pytest.raises(ChangeError):
        manager.propose([{"path": path, "content": "bad"}])


def test_symlink_binary_and_corrupt_blob(manager):
    (manager.root / "link").symlink_to(manager.root / "target")
    with pytest.raises(ChangeError):
        manager.propose([{"path": "link", "content": "bad"}])
    (manager.root / "binary").write_bytes(b"\0\xff")
    with pytest.raises(ChangeError):
        manager.propose([{"path": "binary", "content": "bad"}])
    c = manager.propose([{"path": "new", "content": "hello"}])
    (manager.artifacts / c["manifest"]["files"][0]["after"]).write_text("corrupt")
    with pytest.raises(ChangeError):
        manager.apply(c["id"], c["patch_hash"])
    assert not (manager.root / "new").exists()


def test_git_index_untouched(manager):
    root = manager.root
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout
    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    (root / "a").write_text("base")
    git("add", "a")
    git("commit", "-qm", "base")
    (root / "a").write_text("staged")
    git("add", "a")
    (root / "a").write_text("unstaged")
    before_index = git("show", ":a")
    c = manager.propose([{"path": "a", "content": "agent"}])
    manager.apply(c["id"], c["patch_hash"])
    manager.undo()
    assert git("show", ":a") == before_index == b"staged"
    assert (root / "a").read_text() == "unstaged"


def test_matching_preserves_newlines_and_rejects_ambiguity():
    updated, method = replacement("first\r\nvalue=1\r\nlast\r\n", "first\nvalue=1\nlast", "first\nvalue=2\nlast")
    assert updated == "first\r\nvalue=2\r\nlast\r\n"
    assert method == "newline"
    with pytest.raises(ChangeError):
        replacement("same\nsame\n", "same", "different")
    updated, method = replacement("def item():\n    value = 12\n    return value\n",
                                  "def item():\n    value = 10\n    return value",
                                  "def item():\n    value = 20\n    return value")
    assert method == "fuzzy" and "20" in updated


def test_workspace_scope(manager):
    c = manager.propose([{"path": "a", "content": "a"}])
    other = ChangeManager(manager.root, manager.db_path, manager.artifacts.parent, "another")
    with pytest.raises(ChangeError):
        other.get(c["id"])


def test_runtime_noninteractive_proposal_and_continuity(tmp_path, monkeypatch):
    from talo.application.service import create_app_context, start_session, run_request
    from talo.config import Config, ConnectionConfig
    from talo.changes.manager import for_context
    monkeypatch.setenv("TALO_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    config = Config(path=tmp_path / "config.toml")
    config.set_connection(ConnectionConfig(connection_id="mock", provider_id="mock", protocol="mock", model_id="mock"))
    config.set_default_model("mock:mock")
    ctx = create_app_context(root, config)
    try:
        sid = start_session(ctx)
        monkeypatch.setenv("TALO_MOCK_SCRIPT", json.dumps([{"tool": {"name": "file_write", "arguments": {"path": "a", "content": "hello"}}}]))
        outcome = asyncio.run(run_request(ctx, "a 파일 생성", session_id=sid))
        assert outcome.state.value == "awaiting_approval"
        assert not (root / "a").exists()
        assert outcome.handoff["schema"] == "talo.handoff/0.2"
        assert outcome.handoff["identity"]["workspace_id"] == ctx.workspace_id
        manager = for_context(ctx)
        proposal = manager.list("proposed")[0]
        manager.apply(proposal["id"], proposal["patch_hash"])
        assert (root / "a").read_text() == "hello"
        from talo.continuity import recent_messages
        assert any(m["content"] == "a 파일 생성" for m in recent_messages(ctx.repository, sid))
    finally:
        ctx.close()


def test_next_request_receives_history_decisions_and_tool_pairs(tmp_path, monkeypatch):
    from talo.application.service import create_app_context, start_session, run_request
    from talo.config import Config, ConnectionConfig
    from talo.providers.mock import ScriptedMockAdapter
    from talo.memory.store import MemoryStore
    monkeypatch.setenv("TALO_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a").write_text("hello")
    config = Config(path=tmp_path / "config.toml")
    config.set_connection(ConnectionConfig(connection_id="mock", provider_id="mock", protocol="mock", model_id="one"))
    config.set_default_model("mock:one")
    ctx = create_app_context(root, config)
    seen = []
    original = ScriptedMockAdapter.complete
    async def capture(self, messages, *args, **kwargs):
        seen.append(json.loads(json.dumps(messages)))
        return await original(self, messages, *args, **kwargs)
    monkeypatch.setattr(ScriptedMockAdapter, "complete", capture)
    try:
        memory = MemoryStore(ctx.repository, ctx.project_id)
        decision = memory.propose("decision", "로그인 화면은 이번 수정에서 제외")
        memory.confirm(decision.id)
        sid = start_session(ctx)
        monkeypatch.setenv("TALO_MOCK_SCRIPT", json.dumps([{"tool": {"name": "file_read", "arguments": {"path": "a"}}}, {"text": "첫 결과"}]))
        result = asyncio.run(run_request(ctx, "첫 목표", session_id=sid))
        assert result.exit_code == 0
        second_call = seen[-1]
        call = next(m for m in second_call if m.get("tool_calls"))
        assert any(m.get("tool_call_id") == call["tool_calls"][0]["id"] for m in second_call)
        monkeypatch.setenv("TALO_MOCK_SCRIPT", json.dumps([{"text": "두 번째 결과"}]))
        result = asyncio.run(run_request(ctx, "이어서 해줘", session_id=sid, model_id="two"))
        assert result.exit_code == 0
        prompt = json.dumps(seen[-1], ensure_ascii=False)
        assert "첫 목표" in prompt and "첫 결과" in prompt and "로그인 화면은 이번 수정에서 제외" in prompt
        assert "이전 작업 인계" in prompt
    finally:
        ctx.close()


def test_saved_grant_cannot_bypass_plan():
    from talo.permissions.policy import Grant, PermissionPolicy
    from talo.schemas import WorkMode
    policy = PermissionPolicy(mode=WorkMode.PLAN, grants=[Grant({"tool": "file_write"})])
    assert not policy.evaluate("file_write").allowed
    assert not policy.evaluate("file_write").requires_approval


def test_external_cli_sandbox_blocks_original_writes(tmp_path):
    import sys
    if sys.platform != "darwin":
        pytest.skip("macOS 파일 격리")
    from talo.changes.isolation import CliWorkspace
    root = tmp_path / "root"
    root.mkdir()
    p = root / "a"
    p.write_text("original")
    isolated = CliWorkspace(root, [])
    try:
        # 실제 별도 프로세스에 OS 정책 적용. 프롬프트 지시만으로 보호하지 않는다.
        code = "from pathlib import Path;import sys;Path(sys.argv[1]).write_text('updated')"
        allowed = subprocess.run([*isolated.prefix, sys.executable, "-c", code, str(isolated.stage / "a")], capture_output=True)
        assert allowed.returncode == 0, allowed.stderr.decode()
        denied = subprocess.run([*isolated.prefix, sys.executable, "-c", code, str(p)], capture_output=True)
        assert denied.returncode != 0
        assert p.read_text() == "original"
        assert isolated.edits()[0]["content"] == b"updated"
    finally:
        isolated.close()
