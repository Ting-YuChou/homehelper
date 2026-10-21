import os
from collections.abc import AsyncIterator

import httpx
import pytest

from homehelper.core.config import Settings
from homehelper.main import create_app


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("RUN_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="integration test; set RUN_INTEGRATION=1")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def make_settings(**overrides: object) -> Settings:
    # _env_file=None: tests never read the developer's .env (and never send traces).
    values: dict[str, object] = {"app_env": "test", "langfuse_public_key": "", **overrides}
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.redis.aclose()
    await app.state.db_engine.dispose()
