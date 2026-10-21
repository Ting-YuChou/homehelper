from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from homehelper.mcp_servers.mock_data import MockData, load_mock_data

REPO = Path(__file__).resolve().parents[5]
# Tuesday; the demo data's warranty dates are relative to this day.
NOW = datetime(2026, 10, 20, 17, 0, tzinfo=UTC)


def fixed_clock() -> datetime:
    return NOW


@pytest.fixture
def data() -> MockData:
    return load_mock_data(REPO / "data" / "mock")


class ToolClient:
    """In-memory MCP client: calls go through the real protocol, arguments and output schemas."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def call(self, tool: str, **arguments: Any) -> Any:
        result = await self.session.call_tool(tool, arguments)
        assert not result.isError, result.content
        structured = result.structuredContent
        assert structured is not None
        # FastMCP wraps non-object return values (lists, scalars) as {"result": ...}.
        return structured["result"] if set(structured) == {"result"} else structured

    async def error(self, tool: str, **arguments: Any) -> str:
        result = await self.session.call_tool(tool, arguments)
        assert result.isError
        return " ".join(getattr(c, "text", "") for c in result.content)


@asynccontextmanager
async def connect(server: FastMCP) -> AsyncIterator[ToolClient]:
    async with create_connected_server_and_client_session(server) as session:
        yield ToolClient(session)
