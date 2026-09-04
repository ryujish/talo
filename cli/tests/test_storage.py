"""저장 계층·이벤트·기억 테스트."""
from __future__ import annotations

import pytest

from talo.storage.db import Database
from talo.storage.repository import Repository


@pytest.fixture()
def repo(tmp_path):
    db = Database(tmp_path / "state.sqlite")
    db.migrate()
    yield Repository(db)
    db.close()


def test_migration_and_fts(tmp_path):
    db = Database(tmp_path / "state.sqlite")
    db.migrate()
    row = db.get().execute("SELECT version FROM schema_migrations").fetchone()
    assert row["version"] == 1
    db.close()


def test_workspace_session_run_flow(repo):
    ws_id = repo.upsert_workspace("proj_1", "/tmp/repo", None)
    assert ws_id.startswith("ws_")
    sid = repo.create_session(ws_id, "제목", None)
    assert repo.get_session(sid)["title"] == "제목"
    rid = repo.create_run(sid, "req_1", "dev", "preparing")
    repo.update_run_state(rid, "completed")
    assert repo.get_run(rid)["state"] == "completed"


def test_event_seq_unique_and_replay(repo):
    ws_id = repo.upsert_workspace("proj_1", "/tmp/repo", None)
    sid = repo.create_session(ws_id, None, None)
    seq1, eid1 = repo.append_event(sid, "run_1", "run.started", {"a": 1})
    seq2, eid2 = repo.append_event(sid, "run_1", "run.completed", {"a": 2})
    assert seq1 == 1 and seq2 == 2 and eid1 != eid2
    # 같은 seq 재삽입 시 기존 이벤트 반환 (중복 방지)
    seq3, eid3 = repo.append_event(sid, "run_1", "x", {}, seq=1)
    assert seq3 == 1 and eid3 == eid1
    events = repo.replay_events(sid, after_cursor=0)
    assert [e["seq"] for e in events] == [1, 2]


def test_memory_crud_and_search(repo):
    mid = repo.upsert_memory(None, "proj_1", "rule", "confirmed", "테스트는 항상 작성한다", ["run_1"])
    repo.upsert_memory(mid, "proj_1", "rule", "confirmed", "테스트는 항상 작성한다 (수정)")
    rows = repo.search_memories("proj_1", "테스트")
    assert rows and rows[0]["id"] == mid
    assert rows[0]["version"] == 2
    repo.delete_memory(mid, "proj_1")
    assert repo.search_memories("proj_1", "테스트") == []


def test_memory_project_isolation(repo):
    memory_id = repo.upsert_memory(None, "proj_a", "fact", "confirmed", "A 프로젝트 기억")
    repo.upsert_memory(memory_id, "proj_b", "fact", "confirmed", "침범")
    repo.delete_memory(memory_id, "proj_b")
    assert repo.search_memories("proj_a", "A 프로젝트")
    assert repo.search_memories("proj_b", "A 프로젝트") == []


def test_memory_tools_close_learning_loop(repo, tmp_path):
    import asyncio

    from talo.tools import builtin
    from talo.tools.spec import ToolContext

    ctx = ToolContext(repo_root=tmp_path, workdir=tmp_path, project_id="proj_1",
                      session_id="ses_1", run_id="run_1", artifacts_dir=tmp_path / ".art",
                      repository=repo)
    proposed = asyncio.run(builtin.memory_propose(ctx, "rule", "항상 테스트한다"))
    memory_id = proposed["memory_id"]

    other_ctx = ToolContext(repo_root=tmp_path, workdir=tmp_path, project_id="proj_2",
                            session_id="ses_2", run_id="run_2", artifacts_dir=tmp_path / ".art",
                            repository=repo)
    assert not asyncio.run(builtin.memory_confirm(other_ctx, memory_id))["ok"]
    assert not asyncio.run(builtin.memory_update(other_ctx, memory_id, "침범"))["ok"]
    assert not asyncio.run(builtin.memory_retire(other_ctx, memory_id))["ok"]

    confirmed = asyncio.run(builtin.memory_confirm(ctx, memory_id))
    assert confirmed["memory"]["status"] == "confirmed"
    assert asyncio.run(builtin.memory_confirm(ctx, memory_id))["memory"]["version"] == 2

    updated = asyncio.run(builtin.memory_update(ctx, memory_id, "변경 후 항상 테스트한다"))
    assert updated["memory"]["version"] == 3
    assert updated["memory"]["content"] == "변경 후 항상 테스트한다"
    assert asyncio.run(builtin.memory_update(ctx, memory_id, "변경 후 항상 테스트한다"))["memory"]["version"] == 3

    retired = asyncio.run(builtin.memory_retire(ctx, memory_id))
    assert retired["memory"]["status"] == "retired"
    assert asyncio.run(builtin.memory_retire(ctx, memory_id))["memory"]["version"] == 4
    assert repo.list_memories("proj_1", kind="rule", status="confirmed") == []
