"""Where uploads live (spec §11.1): a local volume in development, a private GCS bucket in
production. Readers get a short-lived signed URL, never a public one.

Objects are named `<uuid4 hex>.<ext>`; the stores only accept keys of that shape, so a stored
URI can never point outside the media directory or bucket.
"""

import asyncio
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from homehelper.core.config import Settings
from homehelper.media.signing import MediaSigner

if TYPE_CHECKING:
    from google.cloud.storage import Bucket

KEY_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp|mp4|mov|webm)$")


def new_key(ext: str) -> str:
    return f"{uuid.uuid4().hex}.{ext}"


def _key(uri: str, prefix: str) -> str:
    key = uri.removeprefix(prefix) if uri.startswith(prefix) else ""
    if not KEY_RE.fullmatch(key):
        raise ValueError(f"not a media object of this store: {uri!r}")
    return key


@dataclass(frozen=True)
class SignedUrl:
    url: str
    expires_at: datetime


class MediaStore(Protocol):
    async def put(self, key: str, source: Path, mime: str) -> str:
        """Store `source` under `key`; returns the storage URI kept in `attachments`."""
        ...

    async def read(self, uri: str) -> bytes: ...

    async def delete(self, uri: str) -> None: ...

    async def signed_url(self, uri: str, *, attachment_id: str, base_url: str) -> SignedUrl:
        """A URL that reads the object until it expires. `base_url` is the API's media route."""
        ...


class LocalMediaStore:
    def __init__(self, root: Path, signer: MediaSigner) -> None:
        self.root = root
        self.signer = signer

    def path(self, uri: str) -> Path:
        return self.root / _key(uri, "local://")

    async def put(self, key: str, source: Path, mime: str) -> str:
        uri = f"local://{key}"
        target = self.path(uri)
        await asyncio.to_thread(self._copy, source, target)
        return uri

    @staticmethod
    def _copy(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)  # streams; a whole video never sits in memory

    async def read(self, uri: str) -> bytes:
        return await asyncio.to_thread(self.path(uri).read_bytes)

    async def delete(self, uri: str) -> None:
        await asyncio.to_thread(self.path(uri).unlink, missing_ok=True)

    async def signed_url(self, uri: str, *, attachment_id: str, base_url: str) -> SignedUrl:
        self.path(uri)  # validates the URI
        token = self.signer.dumps(attachment_id)
        expires_at = datetime.now(UTC) + timedelta(seconds=self.signer.ttl_s)
        return SignedUrl(f"{base_url.rstrip('/')}/{token}", expires_at)


class GcsMediaStore:
    """Private bucket objects, read through V4 signed URLs.

    On Cloud Run the default credentials can't sign locally; `iam_signing` then supplies the
    service account's email and an access token so signing goes through the IAM `signBlob` API
    (needs `roles/iam.serviceAccountTokenCreator` on itself, set up in M8).
    """

    def __init__(
        self,
        bucket: "Bucket",
        *,
        ttl_s: int,
        iam_signing: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self.bucket = bucket
        self.ttl_s = ttl_s
        self._iam_signing = iam_signing

    def _blob_name(self, uri: str) -> str:
        return _key(uri, f"gs://{self.bucket.name}/")

    async def put(self, key: str, source: Path, mime: str) -> str:
        uri = f"gs://{self.bucket.name}/{key}"
        blob = self.bucket.blob(self._blob_name(uri))
        await asyncio.to_thread(blob.upload_from_filename, str(source), content_type=mime)
        return uri

    async def read(self, uri: str) -> bytes:
        return await asyncio.to_thread(self.bucket.blob(self._blob_name(uri)).download_as_bytes)

    async def delete(self, uri: str) -> None:
        await asyncio.to_thread(self.bucket.blob(self._blob_name(uri)).delete)

    async def signed_url(self, uri: str, *, attachment_id: str, base_url: str) -> SignedUrl:
        blob = self.bucket.blob(self._blob_name(uri))
        expiration = timedelta(seconds=self.ttl_s)
        signing = await asyncio.to_thread(self._iam_signing) if self._iam_signing else {}
        sign = partial(
            blob.generate_signed_url,
            version="v4",
            method="GET",
            expiration=expiration,
            service_account_email=signing.get("service_account_email"),
            access_token=signing.get("access_token"),
        )
        url = await asyncio.to_thread(sign)
        return SignedUrl(url, datetime.now(UTC) + expiration)


def build_media_store(settings: Settings, signer: MediaSigner) -> MediaStore:
    if settings.media_backend == "local":
        return LocalMediaStore(settings.media_dir, signer)
    if not settings.gcs_media_bucket:
        raise RuntimeError("MEDIA_BACKEND=gcs needs GCS_MEDIA_BUCKET")
    import google.auth
    from google.auth.credentials import Signing
    from google.auth.transport.requests import Request
    from google.cloud import storage

    credentials, project = google.auth.default()
    client = storage.Client(credentials=credentials, project=project)

    def iam_signing() -> dict[str, str]:
        credentials.refresh(Request())
        return {
            "service_account_email": credentials.service_account_email,
            "access_token": credentials.token,
        }

    return GcsMediaStore(
        client.bucket(settings.gcs_media_bucket),
        ttl_s=settings.media_url_ttl_s,
        iam_signing=None if isinstance(credentials, Signing) else iam_signing,
    )
