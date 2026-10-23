import json
import shutil
from pathlib import Path

import httpx
import pytest

from homehelper.api.deps import SessionSigner
from homehelper.core.config import Settings
from tests.conftest import make_settings

MOCK_DATA = Path(__file__).resolve().parents[4] / "data" / "mock"


def test_session_cookie_round_trips_and_rejects_tampering() -> None:
    signer = SessionSigner(make_settings())
    token = signer.dumps("demo_alex")
    assert signer.loads(token) == "demo_alex"
    assert signer.loads(token[:-2] + "xx") is None
    assert SessionSigner(make_settings(session_secret="other")).loads(token) is None


def test_changing_the_access_code_ends_every_session() -> None:
    signer = SessionSigner(make_settings(demo_access_code="tulip-42"))
    token = signer.dumps("demo_alex")
    assert signer.loads(token) == "demo_alex"
    assert SessionSigner(make_settings(demo_access_code="other")).loads(token) is None
    assert SessionSigner(make_settings()).loads(token) is None


def test_access_code_check() -> None:
    signer = SessionSigner(make_settings(demo_access_code="tulip-42"))
    assert signer.access_code_required
    assert signer.access_code_matches("tulip-42")
    assert signer.access_code_matches(" tulip-42 ")
    assert not signer.access_code_matches("tulip-43")
    assert not signer.access_code_matches("")
    assert not signer.access_code_matches(None)
    assert SessionSigner(make_settings(demo_access_code="tulip-42\n")).access_code_matches(
        "tulip-42"
    )
    open_signer = SessionSigner(make_settings())
    assert not open_signer.access_code_required
    assert open_signer.access_code_matches(None)


def test_production_needs_a_session_secret() -> None:
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        SessionSigner(make_settings(app_env="production"))
    assert SessionSigner(make_settings(app_env="production", session_secret="s3")).secure


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/conversations"),
        ("POST", "/v1/conversations"),
        ("GET", "/v1/auth/me"),
        ("GET", "/v1/me/appliances"),
        ("POST", "/v1/uploads"),
    ],
)
async def test_routes_need_a_session(client: httpx.AsyncClient, method: str, path: str) -> None:
    response = await client.request(method, path, json={})
    assert response.status_code == 401


async def test_media_route_needs_a_valid_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/media/forged.token.value")).status_code == 404


async def test_forged_cookie_is_rejected(client: httpx.AsyncClient) -> None:
    client.cookies.set("hh_session", "not-a-signed-value")
    assert (await client.get("/v1/conversations")).status_code == 401


async def test_writes_from_foreign_origins_are_refused(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/auth/demo-login", json={}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


async def test_admin_routes_need_the_admin_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/admin/evals")).status_code == 401


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # The MCP servers load the whole mock data set at startup, so start from the real one.
    shutil.copytree(MOCK_DATA, tmp_path / "mock")
    users = json.loads((tmp_path / "mock" / "users.json").read_text())
    users[0]["notes"] = "First-time homeowner"
    users[1]["notes"] = None
    (tmp_path / "mock" / "users.json").write_text(json.dumps(users[:2]))
    return make_settings(data_dir=tmp_path, admin_token="admin-secret")


async def test_demo_users_come_from_the_mock_data(client: httpx.AsyncClient) -> None:
    users = (await client.get("/v1/auth/demo-users")).json()
    assert [(u["id"], u["description"]) for u in users] == [
        ("demo_alex", "First-time homeowner"),
        ("demo_jordan", None),
    ]
    assert all(u["display_name"] for u in users)


async def test_admin_routes_accept_the_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/admin/session", headers={"X-Admin-Token": "admin-secret"})
    assert response.status_code == 204
