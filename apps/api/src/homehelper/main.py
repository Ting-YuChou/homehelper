from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from homehelper import __version__
from homehelper.api import health, meta
from homehelper.core.config import Settings, get_settings
from homehelper.core.logging import configure_logging, get_logger
from homehelper.core.middleware import TraceMiddleware
from homehelper.core.tracing import Tracer
from homehelper.db.engine import create_engine
from homehelper.db.redis import create_redis

log = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    tracer = Tracer(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("startup", environment=settings.app_env, tracing=tracer.enabled)
        yield
        await app.state.redis.aclose()
        await app.state.db_engine.dispose()
        tracer.shutdown()

    app = FastAPI(title="HomeHelper API", version=__version__, lifespan=lifespan)
    # Clients connect lazily, so creating them here keeps the app usable without running lifespan.
    app.state.settings = settings
    app.state.tracer = tracer
    app.state.db_engine = create_engine(settings.database_url)
    app.state.redis = create_redis(settings.redis_url)

    app.add_middleware(TraceMiddleware, tracer=tracer, router=app.router)
    app.include_router(health.router)
    app.include_router(meta.router)
    return app
