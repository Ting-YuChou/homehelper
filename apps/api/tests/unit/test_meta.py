import httpx
import pytest

from homehelper.core.config import Settings
from homehelper.main import create_app
from tests.conftest import make_settings


@pytest.fixture
def settings() -> Settings:
    return make_settings(release_id="main-abc1234", git_sha="abc1234")


async def test_meta_names_the_release_and_commit(client: httpx.AsyncClient) -> None:
    """The deploy smoke test checks `git_sha` against the commit it just built."""
    body = (await client.get("/v1/meta")).json()
    assert body["release_id"] == "main-abc1234"
    assert body["git_sha"] == "abc1234"
    assert body["environment"] == "test"
    assert body["access_code_required"] is False


async def test_meta_says_when_signing_in_needs_the_access_code() -> None:
    app = create_app(make_settings(demo_access_code="tulip-42"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/v1/meta")).json()["access_code_required"] is True
    await app.state.redis.aclose()
    await app.state.db_engine.dispose()
