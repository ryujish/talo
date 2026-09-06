"""작업 서비스: 세션 시작·재개·전환·내보내기와 실행 배선."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from talo import paths
from talo.config import Config
from talo.context.engine import ContextEngine
from talo.memory.store import MemoryStore
from talo.providers.resolver import ConnectionResolver, CredentialStore
from talo.runtime.loop import AgentRuntime, RunOutcome
from talo.schemas import SCHEMA_VERSION, ExitCode, RunConfig, new_event_id
from talo.skills.loader import SkillLoader
from talo.storage.db import Database
from talo.storage.repository import Registry, Repository
from talo.tools.registry import ToolRegistry, build_default_registry
from talo.workspace.repo import RepoInfo, Workspace


@dataclass
class AppContext:
    cwd: Path
    repo_info: RepoInfo
    project_id: str
    workspace_id: str
    config: Config
    repository: Repository
    registry: Registry
    tool_registry: ToolRegistry
    context_engine: ContextEngine
    resolver: ConnectionResolver
    skill_loader: SkillLoader
    workspace: Workspace
    db: Database
    registry_db: Database

    def close(self) -> None:
        self.db.close()
        self.registry_db.close()


def _project_id_for(canonical_path: str) -> str:
    return "proj_" + uuid.uuid5(uuid.NAMESPACE_URL, f"talo:{canonical_path}").hex[:12]


def create_app_context(cwd: Path | None = None, config: Config | None = None) -> AppContext:
    workdir = (cwd or Path.cwd()).resolve()
    ws = Workspace(workdir)
    repo_info = ws.detect()
    root = repo_info.root.resolve()

    paths.ensure_talo_dirs()
    registry_db = Database(paths.registry_db_path())
    registry_db.migrate()
    registry = Registry(registry_db)
    registry.migrate()

    canonical = str(root)
    existing = registry.find_project_by_path(canonical)
    if existing:
        project_id = existing["id"]
    else:
        project_id = _project_id_for(canonical)
        registry.register_project(project_id, canonical, root.name)

    paths.ensure_talo_dirs(project_id)
    db = Database(paths.project_db_path(project_id))
    db.migrate()
    repository = Repository(db)
    workspace_id = repository.upsert_workspace(project_id, canonical, str(repo_info.common_dir) if repo_info.common_dir else None)

    cfg = config or Config.load()
    resolver = ConnectionResolver(cfg, CredentialStore())
    tool_registry = build_default_registry()
    context_engine = ContextEngine()
    skill_loader = SkillLoader(paths.user_skills_dir(), paths.project_skills_dir(root))

    return AppContext(
        cwd=workdir, repo_info=repo_info, project_id=project_id, workspace_id=workspace_id,
        config=cfg, repository=repository, registry=registry, tool_registry=tool_registry,
        context_engine=context_engine, resolver=resolver, skill_loader=skill_loader,
        workspace=ws, db=db, registry_db=registry_db,
    )


class EventPublisher:
    """이벤트에 seq를 부여해 저장하고, JSONL(stdout) 또는 사람용(stderr/콜백)으로 전달한다."""

    def __init__(self, repository: Repository, session_id: str, json_out: bool = False,
                 on_human: Callable[[str, dict[str, Any]], None] | None = None,
                 out_stream: Any = None):
        self.repository = repository
        self.session_id = session_id
        self.json_out = json_out
        self.on_human = on_human
        self.out_stream = out_stream

    async def emit(self, event_type: str, payload: dict[str, Any], durable: bool) -> None:
        run_id = payload.get("run_id")
        seq: int | None = None
        event_id: str | None = None
        if durable:
            seq, event_id = self.repository.append_event(self.session_id, run_id, event_type, payload)
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id or new_event_id(),
            "session_id": self.session_id,
            "run_id": run_id,
            "seq": seq,
            "timestamp": time.time(),
            "type": event_type,
            "payload": payload,
        }
        if self.json_out:
            stream = self.out_stream
            if stream is None:
                import sys
                stream = sys.stdout
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
        elif self.on_human is not None:
            import inspect

            result = self.on_human(event_type, payload)
            if inspect.isawaitable(result):
                await result


def make_runtime(ctx: AppContext, run_config: RunConfig | None = None) -> AgentRuntime:
    return AgentRuntime(
        config=ctx.config,
        repository=ctx.repository,
        workspace=ctx.workspace,
        registry=ctx.tool_registry,
        context_engine=ctx.context_engine,
        resolver=ctx.resolver,
        skill_loader=ctx.skill_loader,
        run_config=run_config,
        artifacts_dir=paths.artifacts_dir(ctx.project_id),
    )


def start_session(ctx: AppContext, title: str | None = None, parent_id: str | None = None) -> str:
    conn = ctx.resolver.active()
    connection_id = conn.connection.connection_id if conn and conn.connection else None
    sid = ctx.repository.create_session(ctx.workspace_id, title, connection_id, parent_id)
    return sid


def list_sessions(ctx: AppContext, limit: int = 20) -> list[Any]:
    return ctx.repository.list_sessions(ctx.workspace_id, limit)


def export_session(ctx: AppContext, session_id: str, fmt: str = "markdown") -> str:
    session = ctx.repository.get_session(session_id)
    if session is None:
        raise ValueError(f"세션을 찾지 못함: {session_id}")
    runs = ctx.repository.list_runs(session_id)
    lines: list[str] = []
    if fmt == "json":
        doc: dict[str, Any] = {
            "session": dict(session),
            "runs": [dict(r) for r in runs],
        }
        for run in runs:
            doc.setdefault("messages", {})[run["id"]] = [dict(m) for m in ctx.repository.list_messages(run["id"])]
        return json.dumps(doc, ensure_ascii=False, indent=2)
    lines.append(f"# Talo 세션 내보내기 — {session['title'] or session_id}")
    lines.append(f"- 세션 ID: {session_id}")
    lines.append(f"- 생성: {session['created_at']}")
    for run in runs:
        lines.append(f"\n## Run {run['id']} ({run['mode']}, 상태: {run['state']})")
        for msg in ctx.repository.list_messages(run["id"]):
            try:
                content = json.loads(msg["content_json"])
                text = content.get("text", "") if isinstance(content, dict) else str(content)
            except json.JSONDecodeError:
                text = msg["content_json"]
            lines.append(f"\n### {msg['role']}\n{text}")
    return "\n".join(lines)


async def _run_request(ctx: AppContext, request: str, *, session_id: str, mode: str = "dev",
                      permission: str = "project_edit", connection_id: str | None = None,
                      model_id: str | None = None, json_out: bool = False,
                      on_approval: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
                      on_human: Callable[[str, dict[str, Any]], None] | None = None,
                      run_config: RunConfig | None = None,
                      out_stream: Any = None) -> RunOutcome:
    runtime = make_runtime(ctx, run_config)
    publisher = EventPublisher(ctx.repository, session_id, json_out=json_out,
                               on_human=on_human, out_stream=out_stream)
    outcome = await runtime.start(
        request,
        session_id=session_id,
        mode=mode,
        permission=permission,
        connection_id=connection_id,
        model_id=model_id,
        project_id=ctx.project_id,
        workspace_id=ctx.workspace_id,
        emit=publisher.emit,
        on_approval=on_approval,
    )
    return outcome


def memory_store(ctx: AppContext) -> MemoryStore:
    return MemoryStore(ctx.repository, ctx.project_id)


async def run_request(ctx: AppContext, request: str, **kwargs) -> RunOutcome:
    """동일 workspace의 모델 실행을 직렬화한다. 파일 적용 잠금과는 분리한다."""
    from talo.workspace.repo import WriteLock
    with WriteLock(paths.artifacts_dir(ctx.project_id) / (ctx.workspace_id + ".run.lock")):
        return await _run_request(ctx, request, **kwargs)
