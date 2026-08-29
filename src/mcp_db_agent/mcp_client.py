"""Client side of the protocol boundary.

Wraps a FastMCP client so the agent can discover and invoke tools without
knowing anything about SQLite. Two transports are supported:

  stdio   launches server.py as a separate OS process and speaks MCP over its
          stdin/stdout pipes. This is the real deployment shape -- the server
          could just as well be on another machine.
  memory  connects the client directly to the in-process server object. Same
          MCP messages, no subprocess, so tests run in milliseconds.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from .config import settings


@dataclass(frozen=True)
class ToolSpec:
    """A tool as advertised by the MCP server."""

    name: str
    description: str
    input_schema: dict


def _build_transport(kind: str):
    if kind == "memory":
        from .server import mcp  # imported lazily: only the in-process mode needs it
        return mcp
    return StdioTransport(
        command=sys.executable,
        args=["-m", "mcp_db_agent.server"],
        # Keep the subprocess quiet so its logs do not mix into the CLI output.
        env={**os.environ, "FASTMCP_LOG_LEVEL": "ERROR",
             "FASTMCP_SHOW_SERVER_BANNER": "false"},
    )


class MCPToolbox:
    """Async context manager owning one MCP session.

    Usage:
        async with MCPToolbox() as toolbox:
            specs = toolbox.tools
            result = await toolbox.call("list_tables", {})
    """

    def __init__(self, transport: str | None = None):
        self._kind = (transport or settings.mcp_transport).lower()
        self._client: Client | None = None
        self.tools: list = []

    async def __aenter__(self) -> "MCPToolbox":
        self._client = Client(_build_transport(self._kind))
        await self._client.__aenter__()
        self.tools = [
            ToolSpec(t.name, (t.description or "").strip(), t.inputSchema or {})
            for t in await self._client.list_tools()
        ]
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc)
            self._client = None

    async def call(self, name: str, arguments: dict) -> Any:
        """Invoke a tool and return its deserialised result.

        raise_on_error is off so that a tool-level failure comes back as data the
        agent can read and react to, rather than killing the loop.
        """
        if self._client is None:
            raise RuntimeError("MCPToolbox used outside its async context.")
        result = await self._client.call_tool(name, arguments, raise_on_error=False)
        if result.is_error:
            return {"error": str(result.data)}
        return result.data

    async def read_schema_resource(self) -> Any:
        """Read the schema:://university MCP resource (protocol demo)."""
        if self._client is None:
            raise RuntimeError("MCPToolbox used outside its async context.")
        contents = await self._client.read_resource("schema://university")
        return contents[0].text if contents else None

    @property
    def transport_kind(self) -> str:
        return self._kind
