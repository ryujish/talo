"""Orca가 모르는 TUI에도 추적 가능한 작업을 직접 주입하는 지원 경로."""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

Runner = Callable[[list[str]], Awaitable[dict]]


async def _run_json(argv: list[str]) -> dict:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(stderr.decode("utf-8", "replace") or stdout.decode("utf-8", "replace"))
    return json.loads(stdout)


async def dispatch_to_talo(task_id: str, terminal: str, *, run_id: str | None = None,
                           coordinator: str | None = None, runner: Runner = _run_json) -> dict:
    command = ["orca", "orchestration", "dispatch", "--task", task_id, "--to", terminal,
               "--return-preamble", "--json"]
    if run_id:
        command += ["--run", run_id]
    if coordinator:
        command += ["--from", coordinator]
    dispatched = await runner(command)
    if not dispatched.get("ok"):
        raise RuntimeError(dispatched.get("error", {}).get("message", "Orca dispatch 실패"))
    preamble = dispatched["result"]["preamble"]
    sent = await runner(["orca", "terminal", "send", "--terminal", terminal,
                         "--text", preamble, "--enter", "--json"])
    if not sent.get("ok"):
        raise RuntimeError(sent.get("error", {}).get("message", "Talo 터미널 주입 실패"))
    return dispatched["result"]["dispatch"]
