import os

import httpx
import pytest

from homehelper.core.config import Settings
from tests.conftest import make_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def settings() -> Settings:
    # Use the real services from the environment (docker compose locally, service containers in CI).
    return make_settings(
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql+asyncpg://homehelper:homehelper@localhost:5432/homehelper"
        ),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    )


async def test_readyz_ok_with_running_services(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"postgres": "ok", "redis": "ok"}}
