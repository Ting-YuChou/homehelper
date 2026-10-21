from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from homehelper import __version__
from homehelper.agent.protocol import AgentRuntime
from homehelper.agent.stub import StubAgent
from homehelper.api import health, meta
from homehelper.core.config import Settings, get_settings
from homehelper.core.logging import configure_logging, get_logger
from homehelper.core.middleware import TraceMiddleware
from homehelper.core.tracing import Tracer
from homehelper.db.engine import create_engine
from homehelper.db.redis import create_redis
from homehelper.mcp_servers.factory import build_mcp_servers

log = get_logger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    tracer: Tracer | None = None,
    agent: AgentRuntime | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    tracer = tracer or Tracer(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("startup", environment=settings.app_env, tracing=tracer.enabled)
        async with app.state.mcp.run():
            yield
        await app.state.redis.aclose()
        await app.state.db_engine.dispose()
        tracer.shutdown()

    app = FastAPI(title="HomeHelper API", version=__version__, lifespan=lifespan)
    # Clients connect lazily, so creating them here keeps the app usable without running lifespan.
    app.state.settings = settings
    app.state.tracer = tracer
    # The scripted stub until the journey agent lands (M3); tests and evals inject their own.
    app.state.agent = agent or StubAgent()
    app.state.db_engine = create_engine(settings.database_url)
    app.state.redis = create_redis(settings.redis_url)
    # MCP servers as sub-apps at /mcp/<server>/ (spec §12.1); their session managers run above.
    app.state.mcp = build_mcp_servers(settings, engine=app.state.db_engine)
    app.state.mcp.mount(app.router, auth_token=settings.mcp_auth_token.get_secret_value())

    app.add_middleware(TraceMiddleware, tracer=tracer)
    app.include_router(health.router)
    app.include_router(meta.router)
    return app
