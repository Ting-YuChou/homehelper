import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from homehelper.core.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)

CHECK_TIMEOUT_S = 2.0

CheckStatus = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: CheckStatus
    checks: dict[str, CheckStatus]


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readyz(request: Request, response: Response) -> ReadinessResponse:
    engine = request.app.state.db_engine
    redis = request.app.state.redis

    async def check_postgres() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def check_redis() -> None:
        await redis.ping()

    names = ["postgres", "redis"]
    results = await asyncio.gather(_run_check(check_postgres), _run_check(check_redis))
    checks = dict(zip(names, results, strict=True))
    ready = all(result == "ok" for result in results)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if ready else "error", checks=checks)


async def _run_check(check: Callable[[], Awaitable[None]]) -> CheckStatus:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            await check()
    except Exception as exc:
        log.warning("readiness_check_failed", check=check.__name__, error=repr(exc))
        return "error"
    return "ok"
