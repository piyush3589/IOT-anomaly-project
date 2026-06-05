"""
MCP Client — used by the LangGraph agent to call tools on the MCP server.

Wraps the official MCP Python client into simple async methods
so the agent nodes can call sensor tools cleanly.
"""

import json
import asyncio
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class IoTMCPClient:
    """Manages a persistent MCP session to the IoT sensor server."""

    def __init__(self):
        self._session: ClientSession | None = None
        self._server_params = StdioServerParameters(
            command="python",
            args=["mcp_server/server.py"],
        )

    async def __aenter__(self):
        self._cm = stdio_client(self._server_params)
        self._read, self._write = await self._cm.__aenter__()
        self._session = ClientSession(self._read, self._write)
        await self._session.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.__aexit__(*args)
        await self._cm.__aexit__(*args)

    async def call(self, tool_name: str, args: dict[str, Any] = {}) -> Any:
        """Call an MCP tool and return parsed JSON result."""
        result = await self._session.call_tool(tool_name, args)
        text = result.content[0].text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    async def list_sensors(self) -> dict:
        return await self.call("list_sensors")

    async def get_reading(self, sensor_id: str) -> dict:
        return await self.call("get_reading", {"sensor_id": sensor_id})

    async def get_history(self, sensor_id: str, n: int = 10) -> list:
        return await self.call("get_history", {"sensor_id": sensor_id, "n": n})


# ── Convenience: run MCP tool in sync context (used by LangGraph nodes) ─────

def run_mcp_tool(tool_name: str, args: dict = {}) -> Any:
    """
    Blocking helper — spins up a fresh MCP client, calls one tool, returns result.
    Use this inside synchronous LangGraph nodes.
    """
    async def _run():
        async with IoTMCPClient() as client:
            return await client.call(tool_name, args)

    return asyncio.run(_run())
