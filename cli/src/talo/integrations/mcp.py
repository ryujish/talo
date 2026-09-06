"""작은 MCP 클라이언트: Streamable HTTP/SSE와 stdio의 도구 목록을 연결한다."""
from __future__ import annotations

import asyncio
import json
import os
import shlex
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class McpConnection:
    connection_id: str
    kind: str
    target: str
    status: str = "registered"
    tools: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        return {"connection_id": self.connection_id, "kind": self.kind, "target": self.target,
                "status": self.status, "tools": len(self.tools), "error": self.error}


class McpManager:
    def __init__(self, *, http_transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._connections: dict[str, McpConnection] = {}
        self._processes: list[asyncio.subprocess.Process] = []
        self._http_transport = http_transport
        self._request_id = 0

    async def connect_http(self, connection_id: str, url: str,
                           token_env: str | None = None) -> McpConnection:
        conn = McpConnection(connection_id, "http", url)
        self._connections[connection_id] = conn
        headers = {"Accept": "application/json, text/event-stream"}
        token = os.environ.get(token_env or "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(timeout=30, transport=self._http_transport) as client:
                init_response, _init = await self._http_request(client, url, headers, "initialize", {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "talo", "version": "0.1.0"},
                })
                session = init_response.headers.get("mcp-session-id")
                if session:
                    headers["Mcp-Session-Id"] = session
                await client.post(url, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
                _response, tools = await self._http_request(client, url, headers, "tools/list", {})
                conn.tools = tools.get("result", {}).get("tools", [])
                conn.status = "connected"
        except Exception as exc:  # noqa: BLE001
            conn.status, conn.error = "failed", str(exc)
        return conn

    async def connect_stdio(self, connection_id: str, command: str,
                            args: list[str] | None = None) -> McpConnection:
        target = " ".join([shlex.quote(command), *(shlex.quote(arg) for arg in args or [])])
        conn = McpConnection(connection_id, "stdio", target)
        self._connections[connection_id] = conn
        try:
            proc = await asyncio.create_subprocess_exec(
                command, *(args or []), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            self._processes.append(proc)
            await self._stdio_request(proc, "initialize", {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "talo", "version": "0.1.0"},
            })
            await self._stdio_notify(proc, "notifications/initialized")
            result = await self._stdio_request(proc, "tools/list", {})
            conn.tools = result.get("tools", [])
            conn.status = "connected"
        except Exception as exc:  # noqa: BLE001
            conn.status, conn.error = "failed", str(exc)
        return conn

    async def _http_request(self, client: httpx.AsyncClient, url: str,
                            headers: dict[str, str], method: str, params: dict[str, Any]
                            ) -> tuple[httpx.Response, dict[str, Any]]:
        self._request_id += 1
        response = await client.post(url, headers=headers, json={
            "jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params,
        })
        response.raise_for_status()
        payload = _response_json(response)
        if "error" in payload:
            raise RuntimeError(str(payload["error"]))
        return response, payload

    async def _stdio_request(self, proc: asyncio.subprocess.Process,
                             method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        await self._stdio_write(proc, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        assert proc.stdout is not None
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            if not line:
                raise RuntimeError("MCP stdio 서버가 응답 없이 종료했습니다")
            payload = json.loads(line)
            if payload.get("id") != request_id:
                continue
            if "error" in payload:
                raise RuntimeError(str(payload["error"]))
            return payload.get("result", {})

    async def _stdio_notify(self, proc: asyncio.subprocess.Process, method: str) -> None:
        await self._stdio_write(proc, {"jsonrpc": "2.0", "method": method})

    @staticmethod
    async def _stdio_write(proc: asyncio.subprocess.Process, payload: dict[str, Any]) -> None:
        if proc.stdin is None:
            raise RuntimeError("MCP stdio 입력 스트림이 없습니다")
        proc.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        await proc.stdin.drain()

    def list(self) -> list[dict[str, Any]]:
        return [connection.summary() for connection in self._connections.values()]

    def get(self, connection_id: str) -> McpConnection | None:
        return self._connections.get(connection_id)

    async def aclose(self) -> None:
        for proc in self._processes:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 3)
                except asyncio.TimeoutError:
                    proc.kill()
        self._processes.clear()


def _response_json(response: httpx.Response) -> dict[str, Any]:
    if "text/event-stream" not in response.headers.get("content-type", ""):
        return response.json()
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise RuntimeError("MCP SSE 응답에 data 이벤트가 없습니다")
