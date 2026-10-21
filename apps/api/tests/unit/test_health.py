import re

import httpx
import pytest

from homehelper.core.config import Settings
from tests.conftest import make_settings

HEX32 = re.compile(r"^[0-9a-f]{32}$")


async def test_healthz_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_response_carries_generated_trace_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert HEX32.fullmatch(response.headers["x-request-id"])


async def test_valid_incoming_trace_id_is_reused(client: httpx.AsyncClient) -> None:
    trace_id = "0123456789abcdef0123456789abcdef"
    response = await client.get("/healthz", headers={"X-Request-ID": trace_id})
    assert response.headers["x-request-id"] == trace_id


async def test_invalid_incoming_trace_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz", headers={"X-Request-ID": "evil\nlog-line"})
    trace_id = response.headers["x-request-id"]
    assert HEX32.fullmatch(trace_id)


@pytest.fixture
def settings() -> Settings:
    # Nothing listens on port 1, so both readiness checks fail fast.
    return make_settings(
        database_url="postgresql+asyncpg://u:p@127.0.0.1:1/db",
        redis_url="redis://127.0.0.1:1/0",
    )


async def test_readyz_reports_unavailable_dependencies(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "checks": {"postgres": "error", "redis": "error"},
    }
