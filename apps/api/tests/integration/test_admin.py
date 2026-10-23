"""The admin review API (spec §13.2, §17.2, M7-01) with the StubAgent, Postgres and Redis."""

from pathlib import Path
from typing import Any

import httpx
import pytest

from homehelper.core.config import Settings
from tests.conftest import make_settings
from tests.integration.conftest import database_url, parse_sse, redis_test_url, write_demo_data
from tests.unit.media.samples import image_bytes

pytestmark = pytest.mark.integration

ADMIN = "admin-secret"
HEADERS = {"X-Admin-Token": ADMIN}


@pytest.fixture
def api_settings(tmp_path: Path) -> Settings:
    write_demo_data(tmp_path)
    return make_settings(
        database_url=database_url(),
        redis_url=redis_test_url(),
        data_dir=tmp_path,
        admin_token=ADMIN,
        release_id="r-admin-test",
        langfuse_base_url="https://lf.example",
        langfuse_project_id="proj1",
    )


async def _conversation(api: httpx.AsyncClient, *texts: str, user: str | None = "demo_alex") -> str:
    """A conversation with one turn per text; returns its id."""
    assert (await api.post("/v1/auth/demo-login", json={"user_id": user})).status_code == 200
    conversation_id = (await api.post("/v1/conversations", json={})).json()["id"]
    for text in texts:
        response = await api.post(
            f"/v1/conversations/{conversation_id}/messages", json={"text": text}
        )
        assert response.status_code == 200
        parse_sse(response.text)
    return conversation_id


async def _assistant_ids(api: httpx.AsyncClient, conversation_id: str) -> list[str]:
    detail = (await api.get(f"/v1/admin/conversations/{conversation_id}", headers=HEADERS)).json()
    return [m["id"] for m in detail["messages"] if m["role"] == "assistant"]


async def _list(api: httpx.AsyncClient, **params: Any) -> dict[str, Any]:
    response = await api.get("/v1/admin/conversations", params=params, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


async def test_admin_login_exchanges_the_token_for_a_cookie(api: httpx.AsyncClient) -> None:
    assert (await api.post("/v1/admin/session", json={"token": "wrong"})).status_code == 401
    response = await api.post("/v1/admin/session", json={"token": ADMIN})
    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("hh_admin=")
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert (await api.get("/v1/admin/conversations")).status_code == 200  # cookie only
    assert (await api.delete("/v1/admin/session")).status_code == 204
    assert (await api.get("/v1/admin/conversations")).status_code == 401


async def test_admin_login_is_rate_limited(api: httpx.AsyncClient) -> None:
    statuses = [
        (await api.post("/v1/admin/session", json={"token": "guess"})).status_code
        for _ in range(11)
    ]
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


async def test_admin_writes_from_foreign_origins_are_refused(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/v1/admin/session", json={"token": ADMIN}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


async def test_review_list_filters_and_counts(api: httpx.AsyncClient) -> None:
    fixed = await _conversation(api, "My dishwasher won't start", "Hi")
    chat = await _conversation(api, "Hi", user=None)
    [first, second] = await _assistant_ids(api, fixed)
    await api.post("/v1/auth/demo-login", json={"user_id": "demo_alex"})
    await api.post(f"/v1/messages/{first}/feedback", json={"rating": "down", "reason": "Vague"})
    await api.post(f"/v1/messages/{second}/feedback", json={"rating": "up"})

    rows = {r["id"]: r for r in (await _list(api, release_id="r-admin-test"))["items"]}
    assert {fixed, chat} <= rows.keys()
    row = rows[fixed]
    assert (row["user_id"], row["user_is_demo"]) == ("demo_alex", True)
    assert (row["message_count"], row["up_count"], row["down_count"]) == (4, 1, 1)
    assert row["annotation_count"] == 0
    assert row["release_id"] == "r-admin-test"
    assert rows[chat]["user_is_demo"] is False

    down = {r["id"] for r in (await _list(api, feedback="down"))["items"]}
    assert fixed in down and chat not in down
    assert (await _list(api, release_id="no-such-release"))["items"] == []

    await api.post(
        "/v1/admin/annotations",
        json={"message_id": first, "verdict": "correct"},
        headers=HEADERS,
    )
    annotated = {r["id"] for r in (await _list(api, annotated="true"))["items"]}
    unannotated = {r["id"] for r in (await _list(api, annotated="false"))["items"]}
    assert fixed in annotated and fixed not in unannotated and chat in unannotated


async def test_review_list_pages_with_a_cursor_and_samples(api: httpx.AsyncClient) -> None:
    ids = [await _conversation(api, "Hi") for _ in range(3)]
    page = await _list(api, limit=2, release_id="r-admin-test")
    assert len(page["items"]) == 2 and page["next_before"]
    rest = await _list(api, limit=2, release_id="r-admin-test", before=page["next_before"])
    seen = [r["id"] for r in page["items"] + rest["items"]]
    assert len(seen) == len(set(seen))
    assert set(ids) <= set(seen) | {r["id"] for r in (await _list(api, limit=100))["items"]}

    sample = await _list(api, sample=2)
    assert len(sample["items"]) == 2 and sample["next_before"] is None
    bad = await api.get("/v1/admin/conversations", params={"before": "junk"}, headers=HEADERS)
    assert bad.status_code == 422


async def test_deleted_conversations_are_not_reviewed(api: httpx.AsyncClient) -> None:
    conversation_id = await _conversation(api, "Hi")
    await api.delete(f"/v1/conversations/{conversation_id}")
    assert conversation_id not in {r["id"] for r in (await _list(api, limit=100))["items"]}
    detail = await api.get(f"/v1/admin/conversations/{conversation_id}", headers=HEADERS)
    assert detail.status_code == 404


async def test_review_detail_shows_trace_cost_and_feedback(api: httpx.AsyncClient) -> None:
    conversation_id = await _conversation(api, "My dishwasher won't start")
    [assistant] = await _assistant_ids(api, conversation_id)
    await api.post(f"/v1/messages/{assistant}/feedback", json={"rating": "down", "reason": "Long"})
    await api.post("/v1/auth/logout")  # admin access needs no user session

    detail = (await api.get(f"/v1/admin/conversations/{conversation_id}", headers=HEADERS)).json()
    assert detail["user_id"] == "demo_alex"
    user_message, reply = detail["messages"]
    assert user_message["content"] == "My dishwasher won't start"
    assert reply["cards"][0]["type"] == "step"
    assert reply["feedback"] == "down" and reply["feedback_reason"] == "Long"
    assert reply["latency_ms"] is not None
    assert reply["annotations"] == []
    if reply["trace_id"]:
        assert reply["trace_url"] == f"https://lf.example/project/proj1/traces/{reply['trace_id']}"


async def test_annotations_are_validated_edited_and_deleted(api: httpx.AsyncClient) -> None:
    conversation_id = await _conversation(api, "My dishwasher won't start")
    [assistant] = await _assistant_ids(api, conversation_id)
    detail = (await api.get(f"/v1/admin/conversations/{conversation_id}", headers=HEADERS)).json()
    user_message_id = detail["messages"][0]["id"]

    async def annotate(**body: Any) -> httpx.Response:
        return await api.post("/v1/admin/annotations", json=body, headers=HEADERS)

    assert (await annotate(message_id=assistant, verdict="incorrect")).status_code == 422
    assert (
        await annotate(message_id=assistant, verdict="correct", issue_types=["tone"])
    ).status_code == 422
    assert (
        await annotate(message_id=assistant, verdict="incorrect", issue_types=["rude"])
    ).status_code == 422
    assert (
        await annotate(message_id=user_message_id, verdict="incorrect", issue_types=["tone"])
    ).status_code == 404
    assert (
        await annotate(message_id="msg_nope", verdict="incorrect", issue_types=["tone"])
    ).status_code == 404

    created = await annotate(
        message_id=assistant,
        verdict="incorrect",
        issue_types=["too_many_steps_at_once", "tone"],
        expected_response="One step at a time.",
    )
    assert created.status_code == 201, created.text
    annotation = created.json()
    assert annotation["issue_types"] == ["too_many_steps_at_once", "tone"]
    assert annotation["exported_case_id"] is None

    updated = await api.put(
        f"/v1/admin/annotations/{annotation['id']}",
        json={"verdict": "incorrect", "issue_types": ["tone"], "notes": "Curt"},
        headers=HEADERS,
    )
    assert updated.status_code == 200
    assert (updated.json()["issue_types"], updated.json()["notes"]) == (["tone"], "Curt")
    assert updated.json()["expected_response"] is None  # PUT replaces the whole annotation

    detail = (await api.get(f"/v1/admin/conversations/{conversation_id}", headers=HEADERS)).json()
    assert [a["id"] for a in detail["messages"][1]["annotations"]] == [annotation["id"]]

    deleted = await api.delete(f"/v1/admin/annotations/{annotation['id']}", headers=HEADERS)
    assert deleted.status_code == 204
    missing = await api.delete(f"/v1/admin/annotations/{annotation['id']}", headers=HEADERS)
    assert missing.status_code == 404


async def test_admin_lists_manuals(api: httpx.AsyncClient) -> None:
    manuals = (await api.get("/v1/admin/manuals", headers=HEADERS)).json()
    assert {"doc_id": "bosch-shx68t55", "title": "Bosch 800 Series Dishwasher"}.items() <= (
        manuals[0].items()
    )
    assert {m["doc_id"] for m in manuals} == {"bosch-shx68t55", "missing-pdf"}


async def test_admin_attachment_url_needs_admin(api: httpx.AsyncClient) -> None:
    assert (await api.get("/v1/admin/attachments/att_nope", headers=HEADERS)).status_code == 404
    assert (await api.get("/v1/admin/attachments/att_nope")).status_code == 401


async def test_admin_sees_other_users_attachments(api: httpx.AsyncClient) -> None:
    await api.post("/v1/auth/demo-login", json={"user_id": "demo_alex"})
    upload = await api.post(
        "/v1/uploads", files={"file": ("photo.jpg", image_bytes(), "image/jpeg")}
    )
    attachment_id = upload.json()["id"]
    conversation_id = (await api.post("/v1/conversations", json={})).json()["id"]
    sent = await api.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"text": "Here", "attachments": [attachment_id]},
    )
    assert sent.status_code == 200
    await api.post("/v1/auth/demo-login", json={"user_id": None})  # someone else

    detail = (await api.get(f"/v1/admin/conversations/{conversation_id}", headers=HEADERS)).json()
    [attachment] = detail["messages"][0]["attachments"]
    assert (attachment["id"], attachment["kind"]) == (attachment_id, "image")
    assert "analysis" in attachment
    signed = await api.get(f"/v1/admin/attachments/{attachment_id}", headers=HEADERS)
    assert signed.status_code == 200
    assert (await api.get(signed.json()["url"])).status_code == 200
