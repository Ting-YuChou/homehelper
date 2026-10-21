"""Build the MCP servers from settings and mount them into the API (spec §12.1).

Each server is a streamable-HTTP ASGI sub-app at `/mcp/<server>/`. Starlette does not run the
lifespan of mounted sub-apps, so the host app must enter `McpServers.run()` in its own lifespan:
that starts every server's session manager (once per server instance).
"""

import hmac
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import Router
from starlette.types import ASGIApp, Receive, Scope, Send

from homehelper.core.config import Settings
from homehelper.mcp_servers.common import Clock, utc_now
from homehelper.mcp_servers.mock_data import MockData, load_mock_data
from homehelper.mcp_servers.stores import (
    InMemoryProfileStore,
    PostgresProfileStore,
    ProfileStore,
)
from homehelper.mcp_servers.user_profile import build_user_profile_server

MOUNT_PREFIX = "/mcp"


@dataclass
class McpOverrides:
    """Dependencies injected by tests and evals; anything left None is built from settings."""

    data: MockData | None = None
    profile_store: ProfileStore | None = None
    clock: Clock | None = None


class _RequireBearer:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            given = Headers(scope=scope).get("authorization", "").encode()
            if not hmac.compare_digest(given, self._expected):
                response = JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


class McpServers:
    def __init__(self, servers: dict[str, FastMCP]) -> None:
        self.servers = servers
        self._mounted: list[FastMCP] = []

    def __getitem__(self, name: str) -> FastMCP:
        return self.servers[name]

    def mount(self, router: Router, *, prefix: str = MOUNT_PREFIX, auth_token: str = "") -> None:
        for name, server in self.servers.items():
            app: ASGIApp = server.streamable_http_app()
            router.mount(f"{prefix}/{name}", _RequireBearer(app, auth_token) if auth_token else app)
            self._mounted.append(server)

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """Run the session managers of the mounted servers for the host app's lifetime."""
        async with AsyncExitStack() as stack:
            for server in self._mounted:
                await stack.enter_async_context(server.session_manager.run())
            yield


def build_mcp_servers(
    settings: Settings, *, engine: AsyncEngine, overrides: McpOverrides | None = None
) -> McpServers:
    o = overrides or McpOverrides()
    mock = settings.mcp_mode == "mock"
    data = o.data or load_mock_data(settings.mock_dir)
    clock = o.clock or utc_now
    profiles = o.profile_store or (
        InMemoryProfileStore(data) if mock else PostgresProfileStore(engine)
    )
    return McpServers(
        {
            "user_profile": build_user_profile_server(data, profiles, clock=clock),
        }
    )
