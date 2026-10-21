"""Shared FastMCP setup for the HomeHelper servers."""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from homehelper.mcp_servers.registry import META_KEY, TOOL_SPECS, ToolAccess

Mode = Literal["real", "mock"]
Clock = Callable[[], datetime]

_STOPWORDS = frozenset({"a", "an", "and", "the", "is", "my", "of", "on", "in", "to", "it", "with"})


def words(text: str) -> set[str]:
    """Lowercase content words, for the mock servers' keyword matching."""
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1} - _STOPWORDS


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_server(name: str, instructions: str) -> FastMCP:
    """A server meant to be mounted in the API (`/mcp/<name>/`) or run standalone.

    Stateless JSON responses: every request stands alone, so any Cloud Run instance can serve
    it and no session affinity is needed. Host/Origin checks are off because the API in front
    owns that; `serve` turns them back on for the standalone localhost server.
    """
    return FastMCP(
        name,
        instructions=instructions,
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


def mcp_tool[F: Callable[..., object]](
    server: FastMCP, *, title: str, open_world: bool = False, destructive: bool = False
) -> Callable[[F], F]:
    """Register a tool whose access level comes from the registry (KeyError if it is missing)."""

    def decorator(fn: F) -> F:
        spec = TOOL_SPECS[f"{server.name}.{getattr(fn, '__name__', '')}"]
        write = spec.access is ToolAccess.WRITE
        annotations = ToolAnnotations(
            title=title,
            readOnlyHint=not write,
            destructiveHint=destructive if write else None,
            idempotentHint=False if write else None,
            openWorldHint=open_world,
        )
        meta = {META_KEY: {"access": spec.access.value, "llm_callable": spec.llm_callable}}
        server.tool(title=title, annotations=annotations, meta=meta)(fn)
        return fn

    return decorator
