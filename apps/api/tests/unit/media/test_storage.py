import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from homehelper.media.signing import MediaSigner
from homehelper.media.storage import (
    GcsMediaStore,
    LocalMediaStore,
    build_media_store,
    new_key,
)
from tests.conftest import make_settings


def _source(tmp_path: Path, data: bytes = b"\xff\xd8\xffpixels") -> Path:
    path = tmp_path / "upload.bin"
    path.write_bytes(data)
    return path


def test_keys_are_random_uuids_with_the_extension() -> None:
    first, second = new_key("jpg"), new_key("jpg")
    assert first != second
    assert first.endswith(".jpg") and len(first) == 32 + 4


async def test_local_store_round_trip(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "media", MediaSigner("secret", ttl_s=60))
    key = new_key("jpg")
    uri = await store.put(key, _source(tmp_path), "image/jpeg")
    assert uri == f"local://{key}"
    assert await store.read(uri) == b"\xff\xd8\xffpixels"
    assert store.path(uri) == tmp_path / "media" / key
    await store.delete(uri)
    assert not (tmp_path / "media" / key).exists()


@pytest.mark.parametrize(
    "uri",
    [
        "local://../secrets.env",
        "local:///etc/passwd",
        "local://a/b.jpg",
        "gs://bucket/x.jpg",
        "local://x.exe",
    ],
)
async def test_local_store_rejects_keys_it_did_not_make(tmp_path: Path, uri: str) -> None:
    store = LocalMediaStore(tmp_path, MediaSigner("secret", ttl_s=60))
    with pytest.raises(ValueError):
        await store.read(uri)


async def test_local_signed_url_points_at_the_media_route(tmp_path: Path) -> None:
    signer = MediaSigner("secret", ttl_s=900)
    store = LocalMediaStore(tmp_path, signer)
    uri = await store.put(new_key("png"), _source(tmp_path), "image/png")
    signed = await store.signed_url(
        uri, attachment_id="att_1", base_url="http://api.test/v1/media/"
    )
    assert signed.url.startswith("http://api.test/v1/media/")
    assert signer.loads(signed.url.rsplit("/", 1)[1]) == "att_1"
    assert signed.expires_at - datetime.now(UTC) <= timedelta(seconds=900)


def test_media_tokens_round_trip_and_reject_tampering() -> None:
    signer = MediaSigner("secret", ttl_s=60)
    token = signer.dumps("att_1")
    assert signer.loads(token) == "att_1"
    assert signer.loads(token[:-2] + "xx") is None
    assert MediaSigner("other", ttl_s=60).loads(token) is None
    assert signer.loads("garbage") is None


def test_media_tokens_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    signer = MediaSigner("secret", ttl_s=60)
    token = signer.dumps("att_1")
    later = time.time() + 61
    monkeypatch.setattr("itsdangerous.timed.time.time", lambda: later)
    assert signer.loads(token) is None


def test_media_tokens_differ_from_session_cookies() -> None:
    from homehelper.api.deps import SessionSigner

    session = SessionSigner(make_settings(session_secret="s"))
    assert MediaSigner("s", ttl_s=60).loads(session.dumps("att_1")) is None


class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket, self.name = bucket, name

    def upload_from_filename(self, filename: str, content_type: str) -> None:
        self.bucket.objects[self.name] = (Path(filename).read_bytes(), content_type)

    def download_as_bytes(self) -> bytes:
        return self.bucket.objects[self.name][0]

    def delete(self) -> None:
        del self.bucket.objects[self.name]

    def generate_signed_url(self, **kwargs: Any) -> str:
        self.bucket.signed.append(kwargs)
        return f"https://storage.googleapis.com/{self.bucket.name}/{self.name}?X-Goog-Signature=abc"


class FakeBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.signed: list[dict[str, Any]] = []

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


async def test_gcs_store_uploads_and_signs_v4_urls(tmp_path: Path) -> None:
    bucket = FakeBucket("hh-media")
    store = GcsMediaStore(bucket, ttl_s=900)  # type: ignore[arg-type]
    key = new_key("mp4")
    uri = await store.put(key, _source(tmp_path, b"video"), "video/mp4")
    assert uri == f"gs://hh-media/{key}"
    assert bucket.objects[key] == (b"video", "video/mp4")
    assert await store.read(uri) == b"video"
    signed = await store.signed_url(uri, attachment_id="att_1", base_url="unused")
    assert "X-Goog-Signature" in signed.url
    assert bucket.signed[0]["version"] == "v4"
    assert bucket.signed[0]["method"] == "GET"
    assert bucket.signed[0]["expiration"] == timedelta(seconds=900)
    with pytest.raises(ValueError):
        await store.read("gs://other-bucket/" + key)


def test_build_media_store_picks_the_backend(tmp_path: Path) -> None:
    signer = MediaSigner("secret", ttl_s=60)
    local = build_media_store(make_settings(data_dir=tmp_path), signer)
    assert isinstance(local, LocalMediaStore)
    assert local.root == tmp_path / "media" / "uploads"
    with pytest.raises(RuntimeError, match="GCS_MEDIA_BUCKET"):
        build_media_store(make_settings(media_backend="gcs"), signer)
