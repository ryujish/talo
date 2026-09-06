import asyncio

from talo.integrations.orca import dispatch_to_talo


def test_dispatch_to_talo_forwards_orca_preamble():
    calls = []

    async def runner(argv):
        calls.append(argv)
        if argv[1:3] == ["orchestration", "dispatch"]:
            return {"ok": True, "result": {"dispatch": {"id": "ctx_1"}, "preamble": "TASK BLOCK"}}
        return {"ok": True}

    result = asyncio.run(dispatch_to_talo("task_1", "term_1", run_id="run_1", runner=runner))
    assert result["id"] == "ctx_1"
    assert calls[0][:6] == ["orca", "orchestration", "dispatch", "--task", "task_1", "--to"]
    assert calls[1] == ["orca", "terminal", "send", "--terminal", "term_1",
                        "--text", "TASK BLOCK", "--enter", "--json"]
