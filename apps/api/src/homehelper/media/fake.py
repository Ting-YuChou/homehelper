"""In-memory `MediaSource` for tests and evals (spec P6)."""

from collections.abc import Sequence
from typing import Any

from homehelper.media.source import LoadedMedia
from homehelper.media.validation import MediaKind


class FakeMediaSource:
    def __init__(self, owner: str | None = None) -> None:
        self.owner = owner
        self._items: dict[str, tuple[LoadedMedia, bytes, str | None]] = {}
        self.saved: dict[str, dict[str, Any]] = {}

    def add(
        self,
        attachment_id: str,
        kind: MediaKind,
        mime: str,
        data: bytes,
        *,
        owner: str | None = None,
    ) -> None:
        media = LoadedMedia(attachment_id, kind, mime, f"fake://{attachment_id}")
        self._items[attachment_id] = (media, data, owner or self.owner)

    async def load(self, ids: Sequence[str], user_id: str | None) -> list[LoadedMedia]:
        loaded = []
        for attachment_id in ids:
            item = self._items.get(attachment_id)
            if item is None or user_id is None or item[2] not in (None, user_id):
                continue
            media = item[0]
            analysis = self.saved.get(attachment_id)
            loaded.append(
                LoadedMedia(
                    media.attachment_id, media.kind, media.mime, media.storage_uri, analysis
                )
            )
        return loaded

    async def read(self, media: LoadedMedia) -> bytes:
        return self._items[media.attachment_id][1]

    async def save_analysis(self, attachment_id: str, analysis: dict[str, Any]) -> None:
        self.saved[attachment_id] = analysis
