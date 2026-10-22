"""The agent's MCP client (spec §12.1, M5-07, ADR-008).

Tools are called through an in-memory MCP session on the API's own servers, so every call goes
through the real protocol and the servers' input and output schemas. Each call opens and closes
its own session in the calling task (the servers are stateless).

Two entry points keep the access rules in one place:
- `llm_tools` / `call_llm`: what the responder may call. Only read tools that are both in the
  step's `tools_allowed` and LLM-callable in `mcp_servers.registry` are offered or run. The LLM
  never sees or fills `user_id`; it is bound from the conversation.
- `call_action`: journey step actions, run by code. The only way to reach write tools.

Failures (tool errors, timeouts, transport errors) come back as `ToolOutcome(ok=False)`; they
never raise into the graph.
"""

import copy
from collections.abc import Iterable
from typing import Any, Protocol

import anyio
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, Tool
from pydantic import BaseModel

from homehelper.core.logging import get_logger
from homehelper.llm import ToolSpec
from homehelper.mcp_servers.factory import McpServers
from homehelper.mcp_servers.registry import TOOL_SPECS, is_llm_callable

log = get_logger(__name__)

TOOL_TIMEOUT_S = 10.0
USER_ARG = "user_id"
MCP_PREFIX = "mcp:"
# Provider function names allow only letters, digits, `_` and `-`.
LLM_NAME_SEP = "__"


class ToolOutcome(BaseModel):
    tool: str  # qualified name, e.g. "service_booking.book"
    arguments: dict[str, Any]  # as called, without `user_id`
    ok: bool
    data: Any = None
    error: str | None = None
    # A write already done for this issue in an earlier, failed turn: not called again.
    replayed: bool = False


class Toolbox(Protocol):
    async def llm_tools(self, allowed: Iterable[str], *, user_id: str | None) -> list[ToolSpec]:
        """The tools to offer the LLM at a step."""
        ...

    async def call_llm(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        allowed: Iterable[str],
        user_id: str | None,
    ) -> ToolOutcome:
        """Run a tool the LLM asked for by its `llm_tools` name."""
        ...

    async def call_action(
        self, tool: str, arguments: dict[str, Any], *, user_id: str | None
    ) -> ToolOutcome:
        """Run a step action's tool (read or write), called by code only."""
        ...


def qualified(tool: str) -> str:
    """`mcp:server.tool` (journey YAML) → `server.tool`."""
    return tool.removeprefix(MCP_PREFIX)


def llm_name(tool: str) -> str:
    return qualified(tool).replace(".", LLM_NAME_SEP, 1)


def from_llm_name(name: str) -> str:
    return name.replace(LLM_NAME_SEP, ".", 1)


def without_user(arguments: dict[str, Any]) -> dict[str, Any]:
    """Arguments as recorded in traces and `ToolCall`s: never with `user_id`."""
    return {k: v for k, v in arguments.items() if k != USER_ARG}


def _text(result: CallToolResult) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content).strip()


def _data(result: CallToolResult) -> Any:
    structured = result.structuredContent
    if structured is None:
        return _text(result)
    # FastMCP wraps non-object return values (lists, scalars) as {"result": ...}.
    return structured["result"] if set(structured) == {"result"} else structured


def _takes_user(tool: Tool) -> bool:
    return USER_ARG in tool.inputSchema.get("properties", {})


def _llm_schema(tool: Tool) -> dict[str, Any]:
    schema = copy.deepcopy(tool.inputSchema)
    schema.get("properties", {}).pop(USER_ARG, None)
    if USER_ARG in schema.get("required", []):
        schema["required"] = [name for name in schema["required"] if name != USER_ARG]
    return schema


class McpToolbox:
    def __init__(self, servers: McpServers, *, timeout_s: float = TOOL_TIMEOUT_S) -> None:
        self._servers = servers
        self._timeout_s = timeout_s
        self._listing: dict[str, Tool] | None = None

    async def _tools(self) -> dict[str, Tool]:
        """The servers' tool listing, cached once it succeeds; empty (and retried on the next
        call) when listing fails, so an outage never raises into the graph."""
        if self._listing is None:
            listing: dict[str, Tool] = {}
            try:
                with anyio.fail_after(self._timeout_s):
                    for server_name, server in self._servers.servers.items():
                        async with create_connected_server_and_client_session(server) as session:
                            for tool in (await session.list_tools()).tools:
                                listing[f"{server_name}.{tool.name}"] = tool
            except Exception as exc:
                log.warning("tool_listing_failed", error=repr(exc))
                return {}
            self._listing = listing
        return self._listing

    async def llm_tools(self, allowed: Iterable[str], *, user_id: str | None) -> list[ToolSpec]:
        tools = await self._tools()
        specs = []
        for name in dict.fromkeys(qualified(t) for t in allowed):
            tool = tools.get(name)
            if tool is None or not is_llm_callable(name):
                log.warning("tool_not_offered", tool=name, reason="not an LLM-callable tool")
                continue
            if _takes_user(tool) and user_id is None:
                continue  # needs a signed-in user
            specs.append(
                ToolSpec(
                    name=llm_name(name),
                    description=tool.description or tool.title or name,
                    parameters=_llm_schema(tool),
                )
            )
        return specs

    async def call_llm(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        allowed: Iterable[str],
        user_id: str | None,
    ) -> ToolOutcome:
        tool = from_llm_name(name)
        offered = {qualified(t) for t in allowed}
        if tool not in offered or not is_llm_callable(tool):
            log.warning("tool_refused", tool=tool, reason="not offered to the LLM at this step")
            return ToolOutcome(
                tool=tool,
                arguments=without_user(arguments),
                ok=False,
                error="this tool is not available",
            )
        return await self._call(tool, arguments, user_id)

    async def call_action(
        self, tool: str, arguments: dict[str, Any], *, user_id: str | None
    ) -> ToolOutcome:
        return await self._call(qualified(tool), arguments, user_id)

    async def _call(self, tool: str, arguments: dict[str, Any], user_id: str | None) -> ToolOutcome:
        shown = without_user(arguments)
        listed = (await self._tools()).get(tool)
        if listed is None or tool not in TOOL_SPECS:
            return ToolOutcome(tool=tool, arguments=shown, ok=False, error="unknown tool")
        call_args = dict(shown)
        if _takes_user(listed):
            if user_id is None:
                return ToolOutcome(tool=tool, arguments=shown, ok=False, error="no signed-in user")
            call_args[USER_ARG] = user_id  # bound by code, whatever the caller sent
        server_name, tool_name = tool.split(".", 1)
        try:
            with anyio.fail_after(self._timeout_s):
                server = self._servers[server_name]
                async with create_connected_server_and_client_session(server) as session:
                    result = await session.call_tool(tool_name, call_args)
        except Exception as exc:
            log.warning("tool_call_failed", tool=tool, error=repr(exc))
            return ToolOutcome(tool=tool, arguments=shown, ok=False, error=type(exc).__name__)
        if result.isError:
            log.info("tool_error", tool=tool, error=_text(result))
            return ToolOutcome(tool=tool, arguments=shown, ok=False, error=_text(result))
        return ToolOutcome(tool=tool, arguments=shown, ok=True, data=_data(result))
