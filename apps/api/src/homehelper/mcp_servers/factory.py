"""Build the MCP servers from settings and mount them into the API (spec §12.1).

Each server is a streamable-HTTP ASGI sub-app at `/mcp/<server>/`. Starlette does not run the
lifespan of mounted sub-apps, so the host app must enter `McpServers.run()` in its own lifespan:
that starts every server's session manager (once per server instance).
"""

import hmac
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import Router
from starlette.types import ASGIApp, Receive, Scope, Send

from homehelper.core.config import Settings
from homehelper.knowledge.web import TavilySearchClient, WebSearchClient, Whitelist
from homehelper.mcp_servers.client import McpClient, connect
from homehelper.mcp_servers.common import Clock, utc_now
from homehelper.mcp_servers.mock_data import MockData, load_mock_data
from homehelper.mcp_servers.parts_catalog import build_parts_catalog_server
from homehelper.mcp_servers.service_booking import build_service_booking_server
from homehelper.mcp_servers.stores import (
    BookingStore,
    InMemoryBookingStore,
    InMemoryProfileStore,
    PostgresBookingStore,
    PostgresProfileStore,
    ProfileStore,
)
from homehelper.mcp_servers.tutorials import (
    MockVideoSearch,
    VideoSearch,
    YouTubeVideoSearch,
    build_tutorials_server,
)
from homehelper.mcp_servers.user_profile import build_user_profile_server
from homehelper.mcp_servers.web_search import (
    StaticSearchClient,
    UnconfiguredSearchClient,
    build_web_search_server,
)

MOUNT_PREFIX = "/mcp"


@dataclass
class McpOverrides:
    """Dependencies injected by tests and evals; anything left None is built from settings."""

    data: MockData | None = None
    profile_store: ProfileStore | None = None
    booking_store: BookingStore | None = None
    video_search: VideoSearch | None = None
    # e.g. `StaticSearchClient(case_hits, require_match=False)` for injection evals
    web_search_client: WebSearchClient | None = None
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
    async def client(self, name: str) -> AsyncIterator[McpClient]:
        """An in-memory client session to one server (see `mcp_servers.client`). It needs no
        running session manager, so it also works outside the app lifespan."""
        async with connect(name, self.servers[name]) as client:
            yield client

    async def call(self, server: str, tool: str, arguments: Mapping[str, Any] | None = None) -> Any:
        """One tool call in its own session; raises `McpToolError` when the tool fails."""
        async with self.client(server) as client:
            return await client.call(tool, arguments)

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """Run the session managers of the mounted servers for the host app's lifetime."""
        async with AsyncExitStack() as stack:
            for server in self._mounted:
                await stack.enter_async_context(server.session_manager.run())
            yield


def video_search_for(settings: Settings, data: MockData) -> VideoSearch:
    """YouTube in real mode when a key is set; otherwise the mock videos (spec §12.1)."""
    key = settings.youtube_api_key.get_secret_value()
    if settings.mcp_mode == "real" and key:
        return YouTubeVideoSearch(key)
    return MockVideoSearch(data.videos)


def web_search_client_for(settings: Settings, data: MockData) -> WebSearchClient:
    """Tavily in real mode (no results without a key); canned `web_results.json` in mock mode."""
    if settings.mcp_mode == "mock":
        return StaticSearchClient(data.web_results)
    key = settings.tavily_api_key.get_secret_value()
    return TavilySearchClient(key) if key else UnconfiguredSearchClient()


def build_mcp_servers(
    settings: Settings, *, engine: AsyncEngine | None = None, overrides: McpOverrides | None = None
) -> McpServers:
    """`engine` is needed only for the Postgres stores of real mode (mock mode and evals run
    without a database)."""
    o = overrides or McpOverrides()
    mock = settings.mcp_mode == "mock"

    def require_engine() -> AsyncEngine:
        if engine is None:
            raise ValueError("MCP_MODE=real needs a database engine for its stores")
        return engine

    data = o.data or load_mock_data(settings.mock_dir)
    clock = o.clock or utc_now
    profiles = o.profile_store or (
        InMemoryProfileStore(data) if mock else PostgresProfileStore(require_engine())
    )
    bookings = o.booking_store or (
        InMemoryBookingStore() if mock else PostgresBookingStore(require_engine())
    )
    videos = o.video_search or video_search_for(settings, data)
    web = o.web_search_client or web_search_client_for(settings, data)
    return McpServers(
        {
            "user_profile": build_user_profile_server(data, profiles, clock=clock),
            "parts_catalog": build_parts_catalog_server(data.parts),
            "tutorials": build_tutorials_server(videos),
            "service_booking": build_service_booking_server(data, bookings, profiles, clock=clock),
            "web_search": build_web_search_server(web, Whitelist.load(settings.web_whitelist_path)),
        }
    )
