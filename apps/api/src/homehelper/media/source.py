"""Uploads as the agent sees them (spec §11): the user's own attachments, their bytes, and a cache
of what the models saw in them.

The cache (`attachments.analysis`) means a turn that is rolled back and retried does not pay for
the same analysis twice. Like the MCP tools writing the mock tables, the media component owns
this table; the agent itself still writes only its checkpointer.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homehelper.db.models import Attachment
from homehelper.media.storage import MediaStore
from homehelper.media.validation import MediaKind


@dataclass(frozen=True)
class LoadedMedia:
    attachment_id: str
    kind: MediaKind
    mime: str
    storage_uri: str
    analysis: dict[str, Any] | None = None


class MediaSource(Protocol):
    async def load(self, ids: Sequence[str], user_id: str | None) -> list[LoadedMedia]:
        """The ready attachments among `ids` that belong to `user_id`, in the order given."""
        ...

    async def read(self, media: LoadedMedia) -> bytes: ...

    async def save_analysis(self, attachment_id: str, analysis: dict[str, Any]) -> None: ...


class AttachmentMediaSource:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], store: MediaStore) -> None:
        self._sessionmaker = sessionmaker
        self._store = store

    async def load(self, ids: Sequence[str], user_id: str | None) -> list[LoadedMedia]:
        if not ids or user_id is None:
            return []
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(Attachment).where(
                        Attachment.id.in_(ids),
                        Attachment.user_id == user_id,
                        Attachment.status == "ready",
                    )
                )
            ).all()
        by_id = {row.id: row for row in rows}
        return [
            LoadedMedia(
                attachment_id=row.id,
                kind=row.kind,  # type: ignore[arg-type]
                mime=row.mime,
                storage_uri=row.storage_uri,
                analysis=row.analysis,
            )
            for row in (by_id[i] for i in ids if i in by_id)
        ]

    async def read(self, media: LoadedMedia) -> bytes:
        return await self._store.read(media.storage_uri)

    async def save_analysis(self, attachment_id: str, analysis: dict[str, Any]) -> None:
        async with self._sessionmaker.begin() as session:
            await session.execute(
                update(Attachment).where(Attachment.id == attachment_id).values(analysis=analysis)
            )
