import httpx
import pytest

from homehelper.core.config import Settings
from tests.conftest import make_settings
from tests.integration.conftest import REDIS_URL, database_url

pytestmark = pytest.mark.integration


@pytest.fixture
def settings() -> Settings:
    # Use the real services from the environment (docker compose locally, service containers in CI).
    return make_settings(database_url=database_url(), redis_url=REDIS_URL)


async def test_readyz_ok_with_running_services(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"postgres": "ok", "redis": "ok"}}
