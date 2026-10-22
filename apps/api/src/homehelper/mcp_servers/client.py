"""In-process calls to the MCP servers, through the real protocol over in-memory streams.

The API's own routes (e.g. `/v1/me/appliances`) use this instead of HTTP to `/mcp/<server>/`:
arguments and output schemas are still validated by the server, but nothing leaves the process.
A session is opened and closed in the same task (anyio cancel scopes must not cross tasks), so
use `async with servers.client(name) as client:` inside the request, never in a fixture.
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import TypeAdapter


class McpToolError(Exception):
    """A tool call failed: the tool raised `ToolError`, rejected its arguments, or returned no
    structured result."""

    def __init__(self, server: str, tool: str, message: str) -> None:
        super().__init__(f"{server}.{tool}: {message}")
        self.server = server
        self.tool = tool
        self.message = message


def unwrap_structured(structured: dict[str, Any]) -> Any:
    """FastMCP wraps non-object return values (lists, scalars) as `{"result": ...}`. None of our
    record schemas has `result` as its only field, so a lone `result` key is always the wrapper."""
    return structured["result"] if set(structured) == {"result"} else structured


class McpClient:
    """One open client session to one server."""

    def __init__(self, server: str, session: ClientSession) -> None:
        self.server = server
        self._session = session

    async def call(self, tool: str, arguments: Mapping[str, Any] | None = None) -> Any:
        """Call a tool and return its structured result as plain JSON data (unwrapped)."""
        result = await self._session.call_tool(tool, dict(arguments or {}))
        if result.isError:
            text = " ".join(getattr(c, "text", "") for c in result.content).strip()
            raise McpToolError(self.server, tool, text or "tool error")
        if result.structuredContent is None:
            raise McpToolError(self.server, tool, "no structured result")
        return unwrap_structured(result.structuredContent)

    async def call_as[T](
        self, result_type: type[T], tool: str, arguments: Mapping[str, Any] | None = None
    ) -> T:
        """`call`, validated into `result_type` (e.g. `list[Appliance]`)."""
        return TypeAdapter(result_type).validate_python(await self.call(tool, arguments))


@asynccontextmanager
async def connect(name: str, server: FastMCP) -> AsyncIterator[McpClient]:
    try:
        async with create_connected_server_and_client_session(server) as session:
            yield McpClient(name, session)
    except BaseExceptionGroup as group:
        # The session's task groups wrap whatever the body raised; callers should see the
        # `McpToolError` (or their own exception) itself, not an exception group.
        error: BaseException = group
        while isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
            error = error.exceptions[0]
        if error is group:
            raise
        raise error from None
