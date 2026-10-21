"""The REST API end to end (spec §13.2) with the StubAgent, Postgres and Redis."""

import httpx
import pytest

from homehelper.core.config import Settings
from tests.integration.conftest import parse_sse

pytestmark = pytest.mark.integration


async def _login(api: httpx.AsyncClient, user_id: str | None = None) -> dict[str, object]:
    response = await api.post("/v1/auth/demo-login", json={"user_id": user_id})
    assert response.status_code == 200
    return response.json()


async def _send(
    api: httpx.AsyncClient, conversation_id: str, body: dict[str, object]
) -> list[tuple[str, dict[str, object]]]:
    response = await api.post(f"/v1/conversations/{conversation_id}/messages", json=body)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    return parse_sse(response.text)


async def test_demo_login_sets_a_session_cookie(api: httpx.AsyncClient) -> None:
    response = await api.post("/v1/auth/demo-login", json={"user_id": "demo_alex"})
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("hh_session=")
    assert "httponly" in cookie and "samesite=lax" in cookie
    user = response.json()
    assert (user["id"], user["is_demo"]) == ("demo_alex", True)
    assert (await api.get("/v1/auth/me")).json() == user
    assert (await api.post("/v1/auth/demo-login", json={"user_id": "nobody"})).status_code == 404


async def test_guest_login_creates_an_anonymous_user(api: httpx.AsyncClient) -> None:
    user = await _login(api)
    assert str(user["id"]).startswith("guest_")
    assert user["is_demo"] is False
    assert await _login(api) == user  # a guest with a valid cookie stays the same user
    assert (await api.post("/v1/auth/logout")).status_code == 204
    assert (await api.get("/v1/auth/me")).status_code == 401


async def test_troubleshooting_flow_step_card_to_fixed(api: httpx.AsyncClient) -> None:
    await _login(api, "demo_alex")
    created = (await api.post("/v1/conversations", json={})).json()
    assert created["release_id"] == "dev"
    conversation_id = created["id"]

    events = await _send(api, conversation_id, {"text": "My dishwasher won't start"})
    names = [name for name, _ in events]
    assert names == ["status", "message.delta", "card", "message.completed"]
    card = events[2][1]["card"]
    assert isinstance(card, dict) and card["type"] == "step" and card["index"] == 1

    events = await _send(
        api, conversation_id, {"action": {"type": "step_result", "value": "fixed"}}
    )
    assert events[-1][0] == "message.completed"

    detail = (await api.get(f"/v1/conversations/{conversation_id}")).json()
    assert detail["outcome"] == "resolved"
    assert detail["active_journey"] == "troubleshoot"
    assert detail["title"] == "My dishwasher won't start"
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert detail["messages"][1]["cards"][0]["type"] == "step"
    assert detail["messages"][1]["citations"][0]["page"] == 12
    assert detail["messages"][2]["action"] == {"type": "step_result", "value": "fixed"}

    listed = (await api.get("/v1/conversations")).json()
    assert listed[0]["id"] == conversation_id


async def test_feedback_is_written_and_replaced(api: httpx.AsyncClient) -> None:
    await _login(api, "demo_alex")
    conversation_id = (await api.post("/v1/conversations", json={})).json()["id"]
    events = await _send(api, conversation_id, {"text": "Hi"})
    message_id = events[-1][1]["message_id"]

    up = await api.post(f"/v1/messages/{message_id}/feedback", json={"rating": "up"})
    assert up.json() == {"message_id": message_id, "rating": "up", "reason": None}
    down = await api.post(
        f"/v1/messages/{message_id}/feedback", json={"rating": "down", "reason": "Too vague"}
    )
    assert down.json()["rating"] == "down"

    detail = (await api.get(f"/v1/conversations/{conversation_id}")).json()
    user_message, assistant = detail["messages"]
    assert assistant["feedback"] == "down"
    assert user_message["feedback"] is None
    no_feedback_on_user_messages = await api.post(
        f"/v1/messages/{user_message['id']}/feedback", json={"rating": "up"}
    )
    assert no_feedback_on_user_messages.status_code == 404


async def test_conversations_are_private_and_soft_deleted(api: httpx.AsyncClient) -> None:
    await _login(api, "demo_alex")
    conversation_id = (await api.post("/v1/conversations", json={})).json()["id"]
    events = await _send(api, conversation_id, {"text": "Hi"})
    message_id = events[-1][1]["message_id"]

    await _login(api)  # someone else
    assert (await api.get(f"/v1/conversations/{conversation_id}")).status_code == 404
    feedback = await api.post(f"/v1/messages/{message_id}/feedback", json={"rating": "up"})
    assert feedback.status_code == 404
    sent = await api.post(f"/v1/conversations/{conversation_id}/messages", json={"text": "x"})
    assert sent.status_code == 404

    await _login(api, "demo_alex")
    assert (await api.delete(f"/v1/conversations/{conversation_id}")).status_code == 204
    assert (await api.get(f"/v1/conversations/{conversation_id}")).status_code == 404
    listed = (await api.get("/v1/conversations")).json()
    assert conversation_id not in [c["id"] for c in listed]


async def test_empty_messages_are_rejected(api: httpx.AsyncClient) -> None:
    await _login(api)
    conversation_id = (await api.post("/v1/conversations", json={})).json()["id"]
    response = await api.post(f"/v1/conversations/{conversation_id}/messages", json={})
    assert response.status_code == 422


async def test_manual_metadata_and_pdf(api: httpx.AsyncClient) -> None:
    await _login(api)
    manual = (await api.get("/v1/manuals/bosch-shx68t55")).json()
    assert manual["title"] == "Bosch 800 Series Dishwasher"
    assert manual["url"] == "http://test/v1/manuals/bosch-shx68t55/file"

    pdf = await api.get("/v1/manuals/bosch-shx68t55/file")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith("inline")
    assert pdf.content.startswith(b"%PDF")

    assert (await api.get("/v1/manuals/unknown")).status_code == 404
    assert (await api.get("/v1/manuals/missing-pdf/file")).status_code == 404


async def test_my_appliances_is_empty_until_the_profile_server_lands(
    api: httpx.AsyncClient,
) -> None:
    await _login(api, "demo_alex")
    assert (await api.get("/v1/me/appliances")).json() == []


async def test_demo_logins_are_rate_limited_per_ip(
    api: httpx.AsyncClient, api_settings: Settings
) -> None:
    for _ in range(api_settings.login_rate_limit_per_hour):
        await _login(api)
    refused = await api.post("/v1/auth/demo-login", json={"user_id": None})
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) > 0
