"""도구 실행기: 준비→권한 평가→(승인)→실행→기록 순서.

기술 설계 10절의 도구 실행 순서를 구현한다.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from talo.permissions.policy import Decision, PermissionPolicy
from talo.tools.spec import ToolContext, input_hash
from talo.tools.registry import ToolRegistry


@dataclass
class ExecutionOutcome:
    call_id: str
    tool_name: str
    status: str  # success | error | denied | approval_required | unknown
    output: Any = None
    error: str | None = None
    operation_id: str | None = None
    result_ref: str | None = None
    decision: Decision | None = None


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, policy: PermissionPolicy, repository: Any = None):
        self.registry = registry
        self.policy = policy
        self.repository = repository

    def prepare(self, tool_name: str, arguments: dict[str, Any]) -> tuple[bool, str, Decision | None]:
        """스키마·권한·경로·가용성 검사. 실행 전 확인 단계."""
        tool = self.registry.get(tool_name)
        if tool is None:
            return False, f"등록되지 않은 도구: {tool_name}", None
        if tool.spec.availability != "available":
            return False, f"현재 사용 불가능한 도구: {tool_name} ({tool.spec.availability})", None
        scope = self._scope(tool_name, arguments)
        decision = self.policy.evaluate(tool_name, scope)
        if not decision.allowed:
            return False, decision.reason, decision
        return True, "ok", decision

    def _scope(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        scope: dict[str, Any] = {"tool": tool_name, "project_root": self.policy.project_root}
        if tool_name == "command_run":
            import shlex

            command = arguments.get("command", "")
            scope["command"] = command
            try:
                argv = shlex.split(command)
            except ValueError:
                argv = []
            if argv:
                scope["executable"] = argv[0]
                scope["argv"] = argv
            scope["cwd"] = arguments.get("cwd", ".")
        if "path" in arguments:
            scope["path"] = arguments["path"]
        return scope

    async def execute(self, ctx: ToolContext, tool_name: str, arguments: dict[str, Any],
                      call_id: str | None = None) -> ExecutionOutcome:
        call_id = call_id or f"call_{int(time.time() * 1000)}"
        ok, reason, decision = self.prepare(tool_name, arguments)
        if not ok:
            if decision is not None and decision.requires_approval:
                approved = False
                if ctx.on_approval is not None:
                    approved = await ctx.on_approval(tool_name, self._scope(tool_name, arguments))
                if approved:
                    return await self._run(ctx, tool_name, arguments, call_id)
                self.policy.record_denial(tool_name, self._scope(tool_name, arguments), reason)
                return ExecutionOutcome(call_id, tool_name, "approval_required", error=reason, decision=decision)
            self.policy.record_denial(tool_name, self._scope(tool_name, arguments), reason)
            return ExecutionOutcome(call_id, tool_name, "denied", error=reason, decision=decision)
        return await self._run(ctx, tool_name, arguments, call_id)

    async def _run(self, ctx: ToolContext, tool_name: str, arguments: dict[str, Any], call_id: str) -> ExecutionOutcome:
        tool = self.registry.get(tool_name)
        assert tool is not None
        ih = input_hash(arguments)
        started = time.time()
        op_id = None
        if self.repository is not None:
            op_id = self.repository.record_operation(ctx.run_id, call_id, tool_name, ih, "prepared", started_at=started)
        try:
            result = await tool.handler(ctx, **arguments)
            status = "review_required" if result.get("review_required") else ("success" if result.get("ok", True) else "error")
            error = None if status == "success" else result.get("error", "도구 실행 실패")
            if self.repository is not None and op_id:
                self.repository.update_operation(op_id, "succeeded" if status == "success" else "failed",
                                                finished_at=time.time())
            return ExecutionOutcome(call_id, tool_name, status, output=result, error=error, operation_id=op_id)
        except PermissionError as exc:
            if self.repository is not None and op_id:
                self.repository.update_operation(op_id, "failed", finished_at=time.time())
            return ExecutionOutcome(call_id, tool_name, "denied", error=str(exc), operation_id=op_id)
        except Exception as exc:  # noqa: BLE001 - 도구 오류를 이벤트로 기록
            if self.repository is not None and op_id:
                self.repository.update_operation(op_id, "failed", finished_at=time.time())
            return ExecutionOutcome(call_id, tool_name, "error", error=f"{type(exc).__name__}: {exc}",
                                    operation_id=op_id)

    async def cancel(self, ctx: ToolContext) -> None:
        proc = getattr(ctx, "_current_process", None)
        if proc is not None and proc.returncode is None:
            import os

            try:
                os.killpg(os.getpgid(proc.pid), 15)
            except (ProcessLookupError, PermissionError):
                pass
