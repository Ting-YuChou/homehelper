"""Uploads end to end (M6-01, spec §11.1): POST /v1/uploads, signed URLs, binding to messages."""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homehelper.core.config import Settings
from homehelper.db.models import Attachment
from homehelper.main import create_app
from tests.conftest import make_settings
from tests.integration.conftest import database_url, parse_sse, redis_test_url, write_demo_data
from tests.unit.media.samples import GPS_IFD, image_bytes, write_video

pytestmark = pytest.mark.integration


@pytest.fixture
def api_settings(tmp_path: Path) -> Settings:
    write_demo_data(tmp_path)
    return make_settings(
        database_url=database_url(),
        redis_url=redis_test_url(),
        data_dir=tmp_path,
        upload_rate_limit_per_hour=5,
    )


@pytest.fixture
async def api(
    api_settings: Settings, redis: Redis, migrated: None
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(api_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    await app.state.conversations.wait_idle()
    await app.state.redis.aclose()
    await app.state.db_engine.dispose()


async def _login(api: httpx.AsyncClient, user_id: str | None = "demo_alex") -> None:
    assert (await api.post("/v1/auth/demo-login", json={"user_id": user_id})).status_code == 200


async def _upload(
    api: httpx.AsyncClient, data: bytes, name: str = "photo.jpg", mime: str = "image/jpeg"
) -> httpx.Response:
    return await api.post("/v1/uploads", files={"file": (name, data, mime)})


async def _conversation(api: httpx.AsyncClient) -> str:
    response = await api.post("/v1/conversations", json={})
    assert response.status_code == 201
    return response.json()["id"]


async def _row(sessionmaker: async_sessionmaker[AsyncSession], attachment_id: str) -> Attachment:
    async with sessionmaker() as session:
        row = await session.get(Attachment, attachment_id)
    assert row is not None
    return row


async def test_upload_a_photo(
    api: httpx.AsyncClient,
    api_settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await _login(api)
    response = await _upload(api, image_bytes("JPEG", (80, 60), gps=True), name="IMG_0001.JPG")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "image"
    assert body["mime"] == "image/jpeg"
    assert (body["width"], body["height"]) == (80, 60)
    assert body["status"] == "ready"
    row = await _row(sessionmaker, body["id"])
    assert row.user_id == "demo_alex"
    assert row.conversation_id is None and row.message_id is None
    stored = api_settings.media_dir / row.storage_uri.removeprefix("local://")
    assert stored.exists() and "IMG_0001" not in stored.name
    from PIL import Image

    with Image.open(stored) as image:
        assert not image.getexif().get_ifd(GPS_IFD)


async def test_upload_a_video(api: httpx.AsyncClient, tmp_path: Path) -> None:
    await _login(api)
    clip = write_video(tmp_path / "clip.mp4", metadata={"location": "+37.7-122.4/"}).read_bytes()
    response = await _upload(api, clip, name="clip.mp4", mime="video/mp4")
    assert response.status_code == 201, response.text
    assert response.json()["kind"] == "video"
    assert response.json()["duration_s"] == pytest.approx(1.0, abs=0.2)


async def test_the_bytes_decide_the_type(api: httpx.AsyncClient) -> None:
    await _login(api)
    response = await _upload(api, b"MZ\x90\x00 not really a photo", name="photo.jpg")
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_type"
    png = await _upload(api, image_bytes("PNG"), name="clip.mp4", mime="video/mp4")
    assert png.status_code == 201
    assert png.json()["mime"] == "image/png"


async def test_too_large_is_413(api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("homehelper.media.validation.MAX_IMAGE_BYTES", 100)
    await _login(api)
    response = await _upload(api, image_bytes("PNG", (200, 200)))
    assert response.status_code == 413
    assert response.json()["code"] == "too_large"


async def test_too_long_video_is_422(
    api: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("homehelper.media.video.MAX_VIDEO_SECONDS", 0.5)
    await _login(api)
    clip = write_video(tmp_path / "clip.mp4").read_bytes()
    response = await _upload(api, clip, name="clip.mp4", mime="video/mp4")
    assert response.status_code == 422
    assert response.json()["code"] == "too_long"


async def test_a_request_without_a_file_is_422(api: httpx.AsyncClient) -> None:
    await _login(api)
    response = await api.post("/v1/uploads", data={"note": "no file"})
    assert response.status_code == 422


async def test_uploads_are_rate_limited(api: httpx.AsyncClient) -> None:
    await _login(api)
    for _ in range(5):
        assert (await _upload(api, image_bytes())).status_code == 201
    refused = await _upload(api, image_bytes())
    assert refused.status_code == 429
    assert "Retry-After" in refused.headers


async def test_signed_url_serves_the_file(api: httpx.AsyncClient) -> None:
    await _login(api)
    attachment = (await _upload(api, image_bytes("PNG"), mime="image/png")).json()
    signed = await api.get(f"/v1/attachments/{attachment['id']}")
    assert signed.status_code == 200
    body = signed.json()
    assert body["url"].startswith("http://test/v1/media/")
    api.cookies.clear()  # like an <img src>: the token alone grants access
    media = await api.get(body["url"])
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/png"
    assert media.headers["x-content-type-options"] == "nosniff"
    assert "private" in media.headers["cache-control"]
    assert media.content.startswith(b"\x89PNG")


async def test_signed_urls_expire(api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await _login(api)
    attachment = (await _upload(api, image_bytes())).json()
    url = (await api.get(f"/v1/attachments/{attachment['id']}")).json()["url"]
    later = time.time() + 901
    monkeypatch.setattr("itsdangerous.timed.time.time", lambda: later)
    assert (await api.get(url)).status_code == 404


async def test_bad_media_tokens_are_404(api: httpx.AsyncClient) -> None:
    assert (await api.get("/v1/media/not-a-token")).status_code == 404


async def test_other_users_cannot_see_an_attachment(api: httpx.AsyncClient) -> None:
    await _login(api, "demo_alex")
    attachment = (await _upload(api, image_bytes())).json()
    await _login(api, None)
    assert (await api.get(f"/v1/attachments/{attachment['id']}")).status_code == 404
    assert (await api.get("/v1/attachments/att_missing")).status_code == 404


async def test_send_binds_attachments_to_the_user_message(
    api: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login(api)
    attachment = (await _upload(api, image_bytes())).json()
    conversation_id = await _conversation(api)
    response = await api.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"text": "This is my washer", "attachments": [attachment["id"]]},
    )
    assert response.status_code == 200
    row = await _row(sessionmaker, attachment["id"])
    assert row.conversation_id == conversation_id
    assert row.message_id is not None
    detail = (await api.get(f"/v1/conversations/{conversation_id}")).json()
    user_message = next(m for m in detail["messages"] if m["role"] == "user")
    assert user_message["id"] == row.message_id
    assert user_message["attachments"] == [
        {"id": attachment["id"], "kind": "image", "mime": "image/jpeg"}
    ]
    assistant = next(m for m in detail["messages"] if m["role"] == "assistant")
    assert assistant["attachments"] == []


async def test_a_photo_alone_is_a_message(api: httpx.AsyncClient) -> None:
    await _login(api)
    attachment = (await _upload(api, image_bytes())).json()
    conversation_id = await _conversation(api)
    response = await api.post(
        f"/v1/conversations/{conversation_id}/messages", json={"attachments": [attachment["id"]]}
    )
    assert response.status_code == 200
    assert parse_sse(response.text)[-1][0] == "message.completed"


async def test_an_attachment_is_sent_once(api: httpx.AsyncClient) -> None:
    await _login(api)
    attachment = (await _upload(api, image_bytes())).json()
    conversation_id = await _conversation(api)
    body = {"text": "photo", "attachments": [attachment["id"]]}
    first = await api.post(f"/v1/conversations/{conversation_id}/messages", json=body)
    assert first.status_code == 200
    again = await api.post(f"/v1/conversations/{conversation_id}/messages", json=body)
    assert again.status_code == 422
    [(event, data)] = parse_sse(again.text)
    assert (event, data["code"]) == ("error", "invalid_attachment")


async def test_someone_elses_attachment_is_refused_and_nothing_is_written(
    api: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login(api, "demo_alex")
    attachment = (await _upload(api, image_bytes())).json()
    await _login(api, None)
    conversation_id = await _conversation(api)
    response = await api.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"text": "hi", "attachments": [attachment["id"]]},
    )
    assert response.status_code == 422
    assert parse_sse(response.text)[0][1]["code"] == "invalid_attachment"
    detail = (await api.get(f"/v1/conversations/{conversation_id}")).json()
    assert detail["messages"] == []
    row = await _row(sessionmaker, attachment["id"])
    assert row.conversation_id is None


async def test_one_video_per_message(api: httpx.AsyncClient, tmp_path: Path) -> None:
    await _login(api)
    clip = write_video(tmp_path / "clip.mp4").read_bytes()
    ids = [
        (await _upload(api, clip, name="clip.mp4", mime="video/mp4")).json()["id"] for _ in range(2)
    ]
    conversation_id = await _conversation(api)
    response = await api.post(
        f"/v1/conversations/{conversation_id}/messages", json={"attachments": ids}
    )
    assert response.status_code == 422
    assert "one video" in parse_sse(response.text)[0][1]["message"]


async def test_an_attachment_cannot_move_to_another_conversation(api: httpx.AsyncClient) -> None:
    await _login(api)
    attachment = (await _upload(api, image_bytes())).json()
    first, second = await _conversation(api), await _conversation(api)
    body = {"text": "a", "attachments": [attachment["id"]]}
    assert (await api.post(f"/v1/conversations/{first}/messages", json=body)).status_code == 200
    other = await api.post(f"/v1/conversations/{second}/messages", json=body)
    assert other.status_code == 422
