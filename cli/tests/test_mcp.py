import asyncio
import json
import sys

import httpx

from talo.integrations.mcp import McpManager


def test_http_mcp_initialize_and_list_tools(monkeypatch):
    seen_session = False

    def handler(request):
        nonlocal seen_session
        payload = json.loads(request.content)
        if payload["method"] == "initialize":
            assert request.headers["authorization"] == "Bearer test-token"
            return httpx.Response(200, headers={"mcp-session-id": "ses_1"},
                                  json={"jsonrpc": "2.0", "id": payload["id"], "result": {}})
        if payload["method"] == "notifications/initialized":
            seen_session = request.headers.get("mcp-session-id") == "ses_1"
            return httpx.Response(202)
        assert seen_session
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"],
                                         "result": {"tools": [{"name": "search"}]}})

    monkeypatch.setenv("MCP_TOKEN", "test-token")
    manager = McpManager(http_transport=httpx.MockTransport(handler))
    connection = asyncio.run(manager.connect_http("test", "https://mcp.test/mcp", "MCP_TOKEN"))
    assert connection.status == "connected"
    assert connection.tools == [{"name": "search"}]


def test_stdio_mcp_initialize_and_list_tools():
    server = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    result = {"tools": [{"name": "read"}]} if request["method"] == "tools/list" else {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
"""

    async def run():
        manager = McpManager()
        connection = await manager.connect_stdio("test", sys.executable, ["-u", "-c", server])
        await manager.aclose()
        return connection

    connection = asyncio.run(run())
    assert connection.status == "connected"
    assert connection.tools == [{"name": "read"}]
