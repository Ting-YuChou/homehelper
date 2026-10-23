"""The admin session cookie (spec §18.1, M7-01): the admin token is exchanged for a signed
httpOnly cookie, so the web app never holds the token itself."""

import time

import httpx
import pytest

from homehelper.api.deps import AdminSigner
from homehelper.core.config import Settings
from tests.conftest import make_settings

ADMIN = "admin-secret"


def test_admin_cookie_round_trips_and_rejects_tampering() -> None:
    signer = AdminSigner(make_settings(admin_token=ADMIN))
    token = signer.dumps()
    assert signer.valid(token)
    assert not signer.valid(token[:-2] + "xx")
    assert not signer.valid("not-a-token")
    # A session cookie is not an admin cookie, even with the same secret.
    from homehelper.api.deps import SessionSigner

    assert not signer.valid(SessionSigner(make_settings(admin_token=ADMIN)).dumps("demo_alex"))


def test_the_cookie_does_not_reveal_a_plain_hash_of_the_token() -> None:
    import base64
    import hashlib

    token = AdminSigner(make_settings(admin_token=ADMIN)).dumps()
    payload = base64.urlsafe_b64decode(token.split(".")[0] + "==").decode()
    assert hashlib.sha256(ADMIN.encode()).hexdigest()[:32] not in payload


def test_rotating_the_admin_token_ends_existing_admin_sessions() -> None:
    token = AdminSigner(make_settings(admin_token=ADMIN)).dumps()
    assert not AdminSigner(make_settings(admin_token="rotated")).valid(token)


def test_no_admin_token_means_no_admin_sessions() -> None:
    signer = AdminSigner(make_settings())
    assert not signer.valid(AdminSigner(make_settings(admin_token=ADMIN)).dumps())
    with pytest.raises(ValueError, match="ADMIN_TOKEN"):
        signer.dumps()


def test_admin_cookie_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    signer = AdminSigner(make_settings(admin_token=ADMIN))
    token = signer.dumps()
    later = time.time() + signer.max_age_s + 5
    monkeypatch.setattr(time, "time", lambda: later)
    assert not signer.valid(token)


def test_token_check_is_exact() -> None:
    signer = AdminSigner(make_settings(admin_token=ADMIN))
    assert signer.token_matches(ADMIN)
    assert not signer.token_matches(ADMIN + " ")
    assert not signer.token_matches("é")  # non-ASCII input is a mismatch, not a crash
    assert not signer.token_matches("")
    assert not AdminSigner(make_settings()).token_matches("")


@pytest.fixture
def settings() -> Settings:
    return make_settings(admin_token=ADMIN)


async def test_admin_session_check_accepts_the_header_or_the_cookie(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.get("/v1/admin/session")).status_code == 401
    ok = await client.get("/v1/admin/session", headers={"X-Admin-Token": ADMIN})
    assert ok.status_code == 204
    client.cookies.set("hh_admin", AdminSigner(make_settings(admin_token=ADMIN)).dumps())
    assert (await client.get("/v1/admin/session")).status_code == 204
    client.cookies.set("hh_admin", "forged")
    assert (await client.get("/v1/admin/session")).status_code == 401


async def test_admin_logout_clears_the_cookie(client: httpx.AsyncClient) -> None:
    response = await client.delete("/v1/admin/session")
    assert response.status_code == 204
    assert response.headers["set-cookie"].startswith('hh_admin=""')
