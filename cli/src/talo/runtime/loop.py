"""AgentRuntime: 상태 머신과 실행 루프.

기술 설계 5절의 상태 전이와 10절의 도구 실행 순서를 한 경로에서 수행한다.
한 세션에서 한 Run만 변경 작업을 소유하며, UI는 이벤트를 받아 표시만 한다.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from talo.config import Config
from talo.context.engine import ContextBlock, ContextEngine
from talo.memory.store import MemoryStore
from talo.permissions.policy import Decision, Grant, PermissionPolicy, mode_and_profile
from talo.providers.base import ModelAdapter
from talo.providers.mock import ScriptedMockAdapter
from talo.providers.openai_compat import OpenAICompatAdapter
from talo.providers.resolver import ConnectionResolver, ResolvedConnection
from talo.sanitize import redact_scope
from talo.schemas import ContentBlock, ContentBlockType, ExitCode, Message, RunConfig, RunState, ToolCall, ToolResult, new_id
from talo.skills.loader import SkillLoader
from talo.storage.repository import Repository
from talo.tools.executor import ToolExecutor
from talo.tools.registry import ToolRegistry
from talo.tools.spec import ToolContext
from talo.workspace.repo import Workspace

EmitFn = Callable[[str, dict[str, Any], bool], Awaitable[None]]
ApprovalFn = Callable[[str, dict[str, Any]], Awaitable[bool]]


@dataclass
class RunOutcome:
    run_id: str
    session_id: str
    state: RunState
    exit_code: ExitCode
    summary: str = ""
    handoff: dict[str, Any] | None = None
    details: dict[str, Any] = field(default_factory=dict)


class AgentRuntime:
    def __init__(self, *, config: Config, repository: Repository, workspace: Workspace,
                 registry: ToolRegistry, context_engine: ContextEngine, resolver: ConnectionResolver,
                 skill_loader: SkillLoader, run_config: RunConfig | None = None,
                 artifacts_dir: Any = None):
        self.config = config
        self.repository = repository
        self.workspace = workspace
        self.registry = registry
        self.context_engine = context_engine
        self.resolver = resolver
        self.skill_loader = skill_loader
        self.run_config = run_config or RunConfig()
        self._artifacts_dir = artifacts_dir
        self.cancel_requested = asyncio.Event()
        self._adapter: ModelAdapter | None = None
        self._executor: ToolExecutor | None = None
        self._steer_queue: asyncio.Queue[str] = asyncio.Queue()
        self._current_tool_context: ToolContext | None = None

    # -- 공개 API -------------------------------------------------------------
    async def start(self, request: str, *, session_id: str, mode: str = "dev",
                    permission: str = "project_edit", connection_id: str | None = None,
                    model_id: str | None = None, project_id: str,
                    workspace_id: str, emit: EmitFn | None = None,
                    on_approval: ApprovalFn | None = None) -> RunOutcome:
        emit = emit or (lambda t, p, d: asyncio.sleep(0))
        self.cancel_requested = asyncio.Event()
        if self._artifacts_dir is None:
            from talo import paths
            self._artifacts_dir = paths.artifacts_dir(project_id)
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        resolved = self.resolver.by_id(connection_id) if connection_id else self.resolver.active()

        # A1: 연결 정보 없는 첫 실행 — 안내 후 빈 오류로 종료하지 않음
        if resolved is None or resolved.connection is None:
            guidance = ("연결된 AI가 없습니다. `talo connect`로 연결을 설정하세요. "
                        "연결되지 않아도 도움말·설정·기존 기록 열람은 가능합니다.")
            run_id = self.repository.create_run(session_id, new_id("req"), mode, RunState.FAILED.value)
            await emit("run.started", {"run_id": run_id, "session_id": session_id, "mode": mode}, True)
            await emit("run.failed", {"run_id": run_id, "error": "no_connection", "message": guidance,
                                      "exit_code": int(ExitCode.INPUT_ERROR)}, True)
            return RunOutcome(run_id, session_id, RunState.FAILED, ExitCode.INPUT_ERROR, guidance)

        if (not resolved.credentials.get("api_key") and resolved.connection.provider_id != "mock"
                and resolved.connection.protocol != "cli_subprocess"):
            guidance = (f"연결 '{resolved.connection.connection_id}'의 자격 증명을 찾지 못했습니다. "
                        f"환경변수 {resolved.connection.credential_ref} 또는 `talo connect`로 설정하세요.")
            run_id = self.repository.create_run(session_id, new_id("req"), mode, RunState.FAILED.value)
            await emit("run.started", {"run_id": run_id, "session_id": session_id, "mode": mode}, True)
            await emit("run.failed", {"run_id": run_id, "error": "missing_credential", "message": guidance,
                                      "exit_code": int(ExitCode.INPUT_ERROR)}, True)
            return RunOutcome(run_id, session_id, RunState.FAILED, ExitCode.INPUT_ERROR, guidance)

        self._adapter = self._build_adapter(resolved, model_id)
        policy = self._build_policy(project_id, mode, permission)
        self._executor = ToolExecutor(self.registry, policy, self.repository)

        run_id = self.repository.create_run(session_id, new_id("req"), mode, RunState.PREPARING.value)
        self.repository.update_run_state(run_id, RunState.PREPARING.value)
        await emit("run.started", {
            "run_id": run_id, "session_id": session_id, "mode": mode,
            "permission": permission, "connection_id": resolved.connection.connection_id,
            "model": model_id or resolved.connection.model_id,
        }, True)

        snapshot_before = self.workspace.snapshot()
        memory_store = MemoryStore(self.repository, project_id)
        conversation: list[dict[str, Any]] = [{"role": "user", "content": request}]
        self.repository.append_message(run_id, "user", json.dumps({"text": request}, ensure_ascii=False), source="user")

        try:
            outcome = await self._loop(
                run_id=run_id, session_id=session_id, resolved=resolved, model_id=model_id,
                project_id=project_id, policy=policy, memory_store=memory_store, conversation=conversation,
                snapshot_before=snapshot_before, emit=emit, on_approval=on_approval,
            )
        except asyncio.CancelledError:
            await self._teardown(run_id)
            raise
        await self._close_adapter()
        return outcome

    async def steer(self, text: str) -> None:
        await self._steer_queue.put(text)

    def request_cancel(self) -> None:
        self.cancel_requested.set()
        if self._adapter is not None:
            self._adapter.cancel()

    # -- 내부 -----------------------------------------------------------------
    def _build_adapter(self, resolved: ResolvedConnection, model_id: str | None) -> ModelAdapter:
        conn = resolved.connection
        if conn.provider_id == "mock" or conn.protocol == "mock":
            import os

            script = None
            raw = os.environ.get("TALO_MOCK_SCRIPT", "")
            if raw:
                try:
                    script = json.loads(raw)
                except json.JSONDecodeError:
                    script = None
            if script:
                return ScriptedMockAdapter(conn, resolved.credentials, script)
            return ScriptedMockAdapter(conn, resolved.credentials, [{"text": "모의 응답입니다."}])
        if conn.protocol == "cli_subprocess":
            from talo.providers.cli_subprocess import CliSubprocessAdapter
            return CliSubprocessAdapter(conn, resolved.credentials)
        return OpenAICompatAdapter(conn, resolved.credentials)

    def _build_policy(self, project_id: str, mode: str, permission: str) -> PermissionPolicy:
        work_mode, profile = mode_and_profile(mode, permission)
        grants: list[Grant] = []
        for row in self.repository.list_grants():
            try:
                grants.append(Grant(scope_json=json.loads(row["scope_json"]),
                                    policy_version=row["policy_version"], grant_id=row["id"]))
            except json.JSONDecodeError:
                continue
        repo_root = str(self.workspace.detect().root)
        return PermissionPolicy(mode=work_mode, profile=profile, grants=grants, project_root=repo_root)

    async def _loop(self, *, run_id: str, session_id: str, resolved: ResolvedConnection, model_id: str | None,
                    project_id: str, policy: PermissionPolicy, memory_store: MemoryStore,
                    conversation: list[dict[str, Any]], snapshot_before: dict[str, Any], emit: EmitFn,
                    on_approval: ApprovalFn | None) -> RunOutcome:
        repo_info = self.workspace.detect()
        tool_results: list[dict[str, Any]] = []
        execution_events: list[dict[str, Any]] = []
        verification_events: list[dict[str, Any]] = []
        max_iter = self.run_config.max_iterations
        final_text = ""
        last_state = RunState.CALLING

        for iteration in range(max_iter):
            if self.cancel_requested.is_set():
                await self._teardown(run_id)
                self.repository.update_run_state(run_id, RunState.INTERRUPTED.value)
                await emit("run.failed", {"run_id": run_id, "error": "interrupted",
                                          "message": "사용자 중단", "exit_code": int(ExitCode.INTERRUPTED)}, True)
                return RunOutcome(run_id, session_id, RunState.INTERRUPTED, ExitCode.INTERRUPTED, "사용자 중단")

            # 다음 경계에서 추가 요청 반영
            steered = await self._drain_steer()
            if steered:
                conversation.append({"role": "user", "content": steered})
                self.repository.append_message(run_id, "user", json.dumps({"text": steered}, ensure_ascii=False), source="user")

            self.repository.update_run_state(run_id, RunState.CALLING.value)
            last_state = RunState.CALLING
            blocks = self._context_blocks(repo_info, policy, memory_store, resolved.connection, iteration)
            messages = self.context_engine.openai_messages(blocks, conversation, tool_results)
            tools = self.registry.openai_tools()

            try:
                resp = await self._adapter.complete(
                    messages, tools, model_id or resolved.connection.model_id,
                    on_delta=lambda text: emit("message.delta",
                                               {"run_id": run_id, "text": text}, False),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return await self._handle_model_error(run_id, session_id, exc, emit)

            assistant = resp.message
            self.repository.append_message(
                run_id, "assistant",
                json.dumps([b.model_dump(mode="json") for b in assistant.content_blocks], ensure_ascii=False),
                source="model",
            )
            await emit("message.completed", {
                "run_id": run_id,
                "text": assistant.text,
                "tool_calls": [tc.call_id for tc in assistant.tool_calls],
                "finish_reason": resp.finish_reason,
            }, True)

            if resp.usage:
                self.repository.record_usage(
                    new_id("req"), resolved.connection.connection_id,
                    model_id or resolved.connection.model_id,
                    measured_tokens=_usage_tokens(resp.usage), estimated_cost=None,
                    source=resp.usage.get("source", "unknown"),
                )

            tool_calls = assistant.tool_calls
            if not tool_calls:
                final_text = assistant.text or "완료"
                break

            self.repository.update_run_state(run_id, RunState.CHECKING.value)
            last_state = RunState.CHECKING
            tool_results = []
            for tc in tool_calls:
                outcome = await self._execute_tool(
                    run_id=run_id, session_id=session_id, project_id=project_id, policy=policy,
                    repo_info=repo_info, tc=tc, emit=emit, on_approval=on_approval,
                )
                if outcome.status == "approval_required":
                    safe_arguments = redact_scope(tc.arguments)
                    approval_request_id = self.repository.create_approval_request(
                        session_id, run_id, tc.name,
                        json.dumps(safe_arguments, ensure_ascii=False))
                    self.repository.update_run_state(run_id, RunState.AWAITING_APPROVAL.value)
                    await emit("approval.required", {
                        "run_id": run_id, "tool": tc.name, "arguments": safe_arguments,
                        "message": outcome.error or "승인 필요",
                        "approval_request_id": approval_request_id,
                    }, True)
                    if on_approval is None:
                        # 비대화형 실행: 무한 대기하지 않고 승인 필요 상태로 종료
                        # (요청은 pending으로 Inbox에 남는다)
                        await emit("run.paused", {"run_id": run_id, "reason": "approval_required",
                                                  "exit_code": int(ExitCode.APPROVAL_NEEDED)}, True)
                        return RunOutcome(run_id, session_id, RunState.AWAITING_APPROVAL,
                                          ExitCode.APPROVAL_NEEDED, "승인 필요")
                    approved = await on_approval(tc.name, tc.arguments)
                    self.repository.decide_approval_request(
                        approval_request_id, "approved" if approved else "denied", "user")
                    if not approved:
                        tool_results.append({"call_id": tc.call_id, "output": {"denied": True,
                                              "reason": outcome.error}})
                        continue
                    outcome = await self._execute_tool(
                        run_id=run_id, session_id=session_id, project_id=project_id, policy=policy,
                        repo_info=repo_info, tc=tc, emit=emit, on_approval=None, skip_policy=True,
                    )
                if outcome.status == "denied":
                    tool_results.append({"call_id": tc.call_id, "output": {"denied": True, "reason": outcome.error}})
                elif outcome.status == "error":
                    tool_results.append({"call_id": tc.call_id, "output": {"error": outcome.error}})
                else:
                    tool_results.append({"call_id": tc.call_id, "output": outcome.output})
                    if outcome.status == "success":
                        execution_events.append({"call_id": tc.call_id, "tool": tc.name,
                                                 "status": "success", "at": time.time()})
                if tc.name == "command_run":
                    result = "passed" if outcome.status == "success" else "failed"
                    self.repository.record_verification(run_id, outcome.operation_id,
                                                        snapshot_before.get("head"), result)
                    verification_events.append({"command": tc.arguments.get("command"), "result": result})
                    await emit("verification.recorded", {
                        "run_id": run_id, "result": result,
                        "command": tc.arguments.get("command"),
                    }, True)
                if outcome.status == "success" and outcome.output and _touches_workspace(tc.name):
                    await emit("workspace.changed", {
                        "run_id": run_id, "tool": tc.name,
                        "paths": _changed_paths(tc.arguments),
                    }, True)

        else:
            self.repository.update_run_state(run_id, RunState.FAILED.value)
            await emit("run.failed", {"run_id": run_id, "error": "iteration_limit",
                                      "message": f"반복 제한({max_iter}) 도달 — 부분 완료",
                                      "exit_code": int(ExitCode.FAILED)}, True)
            return RunOutcome(run_id, session_id, RunState.FAILED, ExitCode.FAILED,
                              f"반복 제한({max_iter}) 도달")

        # 종료: 완료 주장을 검증 기록과 대조
        snapshot_after = self.workspace.snapshot()
        changes = self.workspace.compare_snapshot(snapshot_before)
        handoff = self.context_engine.handoff_document(
            identity={"project_id": repo_info.root.name, "workspace_id": repo_info.root.name,
                      "session_id": session_id, "run_id": run_id},
            goal=conversation[0]["content"] if conversation else "",
            constraints={"mode": policy.mode.value, "permission": policy.profile.value,
                         "policy_version": policy.policy_version},
            decisions=[],
            workspace={"branch": repo_info.branch, "head": repo_info.head_sha, "changes": changes},
            execution=execution_events,
            verification=verification_events,
            next_actions=["검증 결과 확인" if verification_events else "변경 검토"],
            context_sources=["session:" + session_id],
        )
        self.repository.save_handoff(session_id, run_id, self.context_engine.context_version, handoff)
        self.repository.update_run_state(run_id, RunState.COMPLETED.value)
        await emit("run.completed", {
            "run_id": run_id,
            "summary": final_text,
            "changes": changes,
            "verifications": verification_events,
            "exit_code": int(ExitCode.COMPLETED),
        }, True)
        return RunOutcome(run_id, session_id, RunState.COMPLETED, ExitCode.COMPLETED, final_text, handoff)

    async def _execute_tool(self, *, run_id: str, session_id: str, project_id: str,
                            policy: PermissionPolicy, repo_info: Any, tc: ToolCall, emit: EmitFn,
                            on_approval: ApprovalFn | None, skip_policy: bool = False):
        ctx = ToolContext(
            repo_root=repo_info.root,
            workdir=repo_info.workdir,
            project_id=project_id,
            session_id=session_id,
            run_id=run_id,
            artifacts_dir=self._artifacts_dir or (repo_info.root / ".talo" / "artifacts"),
            policy=policy,
            repository=self.repository,
            skill_loader=self.skill_loader,
            on_approval=None,
            exclude_paths=self.config.exclude_paths,
            workspace=self.workspace,
        )
        self._current_tool_context = ctx
        await emit("tool.prepared", {"run_id": run_id, "call_id": tc.call_id, "tool": tc.name,
                                     "arguments": tc.arguments}, False)
        if skip_policy and self._executor is not None:
            outcome = await self._executor._run(ctx, tc.name, tc.arguments, tc.call_id)
        else:
            assert self._executor is not None
            outcome = await self._executor.execute(ctx, tc.name, tc.arguments, tc.call_id)
        await emit("tool.started", {"run_id": run_id, "call_id": tc.call_id, "tool": tc.name}, True)
        if outcome.status in {"success", "error", "denied"}:
            await emit("tool.completed", {
                "run_id": run_id, "call_id": tc.call_id, "tool": tc.name,
                "status": outcome.status,
                "summary": outcome.error or _summarize(outcome.output),
                "result_ref": outcome.result_ref,
            }, True)
        return outcome

    async def _handle_model_error(self, run_id: str, session_id: str, exc: Exception, emit: EmitFn) -> RunOutcome:
        text = str(exc)
        if "한도" in text or "429" in text:
            self.repository.update_run_state(run_id, RunState.PAUSED.value)
            await emit("run.paused", {"run_id": run_id, "reason": "limit_exceeded", "message": text,
                                      "exit_code": int(ExitCode.EXTERNAL_PAUSED)}, True)
            return RunOutcome(run_id, session_id, RunState.PAUSED, ExitCode.EXTERNAL_PAUSED,
                              f"한도 초과: {text}")
        self.repository.update_run_state(run_id, RunState.PAUSED.value)
        await emit("run.paused", {"run_id": run_id, "reason": "model_error", "message": text,
                                  "exit_code": int(ExitCode.EXTERNAL_PAUSED)}, True)
        return RunOutcome(run_id, session_id, RunState.PAUSED, ExitCode.EXTERNAL_PAUSED, text)

    async def _drain_steer(self) -> str | None:
        items: list[str] = []
        while True:
            try:
                items.append(self._steer_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return "\n".join(items) if items else None

    def _context_blocks(self, repo_info: Any, policy: PermissionPolicy, memory_store: MemoryStore,
                        connection: Any, iteration: int) -> list[ContextBlock]:
        blocks = [
            ContextBlock("기본 규칙",
                         "너는 Talo 개발자 CLI 에이전트다. 저장소에서 바로 작업하고, 실행 계획과 관찰한 근거를 보여라. "
                         "추론 내부가 아니라 실행 계획과 관찰 근거를 보고한다. "
                         "완료 주장은 실제 검증 기록과 대조한다. '작성 완료'와 '검증 완료'를 구분한다.",
                         source="talo"),
            ContextBlock("프로젝트", f"루트: {repo_info.root}\n브랜치: {repo_info.branch or '없음'}\n"
                         f"HEAD: {repo_info.head_sha or '없음'}\nGit: {'있음' if repo_info.is_git else '없음'}",
                         source="workspace"),
            ContextBlock("작업 방식·권한",
                         f"작업 방식: {policy.mode.value}\n권한 프로필: {policy.profile.value}\n"
                         "계획 모드에서는 변경·실행을 하지 않는다. 승인 범위를 벗어난 실행은 요청하지 않는다.",
                         source="policy"),
        ]
        rules = memory_store.active_rules()
        if rules:
            blocks.append(ContextBlock("프로젝트 규칙",
                                       "\n".join(f"- {r.content}" for r in rules), source="memory"))
        tools_desc = "\n".join(f"- {s.name}: {s.description}" for s in self.registry.available())
        blocks.append(ContextBlock("도구", tools_desc or "(없음)", source="tools"))
        skills = self.skill_loader.list_skills()
        if skills:
            blocks.append(ContextBlock("스킬",
                                       "\n".join(f"- {s['name']}: {s['description']}" for s in skills),
                                       source="skills"))
        return blocks

    async def _teardown(self, run_id: str) -> None:
        if self._executor is not None and self._current_tool_context is not None:
            await self._executor.cancel(self._current_tool_context)

    async def _close_adapter(self) -> None:
        if self._adapter is not None:
            await self._adapter.aclose()
            self._adapter = None


def _usage_tokens(usage: dict[str, Any]) -> int | None:
    for key in ("total_tokens", "totalTokens"):
        if usage.get(key) is not None:
            return int(usage[key])
    prompt = usage.get("prompt_tokens") or 0
    completion = usage.get("completion_tokens") or 0
    if prompt or completion:
        return int(prompt) + int(completion)
    return None


def _touches_workspace(tool_name: str) -> bool:
    return tool_name in {"file_patch", "file_write", "document_write", "command_run"}


def _changed_paths(arguments: dict[str, Any]) -> list[str]:
    if "path" in arguments:
        return [arguments["path"]]
    if "command" in arguments:
        return [f"<command> {arguments['command']}"]
    return []


def _summarize(output: Any) -> str:
    if not isinstance(output, dict):
        return str(output)[:300]
    if output.get("error"):
        return str(output["error"])[:300]
    for key in ("content", "stdout", "summary"):
        if key in output:
            return str(output[key])[:300]
    return str(output)[:300]
