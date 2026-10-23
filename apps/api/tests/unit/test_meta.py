import httpx
import pytest

from homehelper.core.config import Settings
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
