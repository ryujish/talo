"""CLI 서브프로세스 브릿지 어댑터.

로컬에 설치된 코딩 에이전트 CLI(Codex 등)를 하위 프로세스로 실행해
기존 로그인 세션(OAuth)을 그대로 사용한다. API 키를 꺼내거나 별도
발급받을 필요 없이 `codex exec`의 스트리밍 출력을 on_delta로 전달한다.

ConnectionConfig 필드 활용:
  command      실행 파일 이름 (예: "codex")
  cwd          작업 루트 (비어 있으면 현재 작업 디렉터리)
  model_id     CLI에 전달할 모델 (선택)
"""
from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any

from talo.providers.base import DeltaCallback, ModelAdapter, ModelResponse
from talo.schemas import ContentBlock, ContentBlockType, Message, Role

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][AB0-9]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class CliSubprocessAdapter(ModelAdapter):
    """codex exec 같은 비대화형 CLI 실행을 공통 메시지로 변환한다."""

    protocol = "cli_subprocess"

    def __init__(self, connection: Any, credentials: dict[str, str] | None = None):
        super().__init__(connection, credentials)
        self._proc: asyncio.subprocess.Process | None = None

    @property
    def command(self) -> str:
        return getattr(self.connection, "command", "") or "codex"

    @property
    def cwd(self) -> str:
        return getattr(self.connection, "cwd", "") or ""

    # -- 계약 ---------------------------------------------------------------
    async def validate(self) -> tuple[bool, str]:
        exe = shutil.which(self.command)
        if exe is None:
            return False, f"{self.command} 실행 파일을 찾지 못함 — 설치 후 다시 시도하세요"
        auth_file = Path.home() / ".codex" / "auth.json"
        if self.command == "codex" and not auth_file.exists():
            return False, "Codex 로그인 세션이 없음 — `codex login` 실행 후 다시 시도하세요"
        if self.command == "opencode" and not (Path.home() / ".local/share/opencode/auth.json").exists():
            return False, "OpenCode 로그인 세션이 없음 — `opencode auth login` 실행 후 다시 시도하세요"
        return True, f"{self.command} CLI 사용 가능 (OAuth 세션)"

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                       model: str | None = None, on_delta: DeltaCallback | None = None) -> ModelResponse:
        import json

        prompt = self._build_prompt(messages)
        model_id = model or self.connection.model_id or ""

        if self.command == "opencode":
            cmd = [self.command, "run"]
        elif self.command == "agy":
            cmd = [self.command, "--dangerously-skip-permissions"]
        else:
            cmd = [self.command, "exec", "--color", "never", "--skip-git-repo-check", "--ephemeral"]
            cmd.append("--json")
        if model_id:
            cmd += ["--model" if self.command == "agy" else "-m", model_id]
        cwd = self.cwd or None
        if cwd and self.command != "agy":
            cmd += ["--dir" if self.command == "opencode" else "-C", cwd]
        if self.command == "agy":
            cmd += ["--print", prompt]
        else:
            cmd.append(prompt)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        self._proc = proc

        chunks: list[str] = []
        stderr_task = asyncio.create_task(self._read_stream(proc.stderr))
        try:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                if not raw:
                    continue
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                if line.startswith("{") and self.command == "codex":
                    try:
                        ev = json.loads(line)
                        if ev.get("type") == "item.completed":
                            item = ev.get("item", {})
                            if item.get("type") == "agent_message":
                                text_item = item.get("text", "")
                                if text_item:
                                    chunks.append(text_item)
                                    if on_delta is not None:
                                        await on_delta(text_item)
                    except json.JSONDecodeError:
                        pass
                else:
                    clean = _strip_ansi(line)
                    if (not clean.startswith("Reading additional input")
                            and not clean.startswith("OpenAI Codex")
                            and not clean.startswith("tokens used")):
                        chunks.append(clean)
                        if on_delta is not None:
                            await on_delta(clean + "\n")
            await proc.wait()
            stderr_text = await stderr_task
        except BaseException:
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
            raise
        finally:
            self._proc = None

        text = "\n".join(chunks).strip()
        if proc.returncode not in (0, None):
            raise RuntimeError(stderr_text[-500:] or text[-500:]
                               or f"{self.command} exec 실패 (exit {proc.returncode})")

        if not text:
            text = "CLI 실행이 완료됐지만 출력이 없습니다."

        message = Message(
            role=Role.ASSISTANT,
            content_blocks=[ContentBlock(type=ContentBlockType.TEXT, text=text)],
            connection_id=self.connection.connection_id,
            model_id=model_id or self.connection.model_id,
        )
        return ModelResponse(message=message, finish_reason="stop",
                             raw={"bridge": "cli_subprocess", "command": self.command,
                                  "exit_code": proc.returncode})

    def cancel(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()

    async def aclose(self) -> None:
        if self._proc is not None:
            if self._proc.returncode is None:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=3)
                except (asyncio.TimeoutError, ProcessLookupError):
                    self._proc.kill()
            self._proc = None

    # -- 내부 ---------------------------------------------------------------
    @staticmethod
    async def _read_stream(stream: Any) -> str:
        if stream is None:
            return ""
        chunks: list[str] = []
        async for raw in stream:
            chunks.append(_strip_ansi(raw.decode("utf-8", "replace")))
        return "".join(chunks).strip()

    @staticmethod
    def _build_prompt(messages: list[dict[str, Any]]) -> str:
        """OpenAI 형식 메시지를 단일 프롬프트로 접는다."""
        parts: list[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content if isinstance(c, dict) and c.get("text")
                )
            content = str(content or "").strip()
            if not content:
                continue
            if role == "system":
                parts.append(f"<system>\n{content}\n</system>")
            elif role == "assistant":
                parts.append(f"<assistant>\n{content}\n</assistant>")
            else:
                parts.append(content)
        prompt = "\n\n".join(parts).strip()
        return prompt or " "
