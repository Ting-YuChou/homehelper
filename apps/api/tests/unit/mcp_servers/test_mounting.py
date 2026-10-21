"""The servers mounted in the API answer MCP over streamable HTTP (spec §12.1)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from homehelper.core.config import Settings
from homehelper.main import create_app
from homehelper.mcp_servers.registry import TOOLS
from tests.conftest import make_settings


@asynccontextmanager
async def running(settings: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app


@asynccontextmanager
async def mcp_session(
    app: FastAPI, server: str, headers: dict[str, str] | None = None
) -> AsyncIterator[ClientSession]:
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers
    )
    async with (
        http,
        streamable_http_client(f"http://test/mcp/{server}/", http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


async def test_every_server_is_mounted_and_lists_its_registered_tools() -> None:
    async with running(make_settings(mcp_mode="mock")) as app:
        for server in app.state.mcp.servers:
            async with mcp_session(app, server) as session:
                listed = {t.name for t in (await session.list_tools()).tools}
            assert listed == {t.name for t in TOOLS if t.server == server}


async def test_mounted_tool_call_round_trips() -> None:
    async with (
        running(make_settings(mcp_mode="mock")) as app,
        mcp_session(app, "user_profile") as session,
    ):
        result = await session.call_tool("get_profile", {"user_id": "demo_alex"})
    assert not result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["display_name"] == "Alex Kim"


async def test_auth_token_is_required_when_configured() -> None:
    settings = make_settings(mcp_mode="mock", mcp_auth_token="s3cret")
    async with running(settings) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            denied = await http.post("/mcp/user_profile/", json={})
        assert denied.status_code == 401
        auth = {"Authorization": "Bearer s3cret"}
        async with mcp_session(app, "user_profile", headers=auth) as session:
            assert (await session.list_tools()).tools
