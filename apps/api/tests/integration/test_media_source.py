"""The agent's view of uploads (M6-02): `AttachmentMediaSource` over the attachments table."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homehelper.conversations import repository
from homehelper.db.models import Attachment
from homehelper.media.signing import MediaSigner
from homehelper.media.source import AttachmentMediaSource
from homehelper.media.storage import LocalMediaStore, new_key

pytestmark = pytest.mark.integration


async def _attachment(
    sessionmaker: async_sessionmaker[AsyncSession],
    store: LocalMediaStore,
    tmp_path: Path,
    owner: str,
) -> str:
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"\xff\xd8\xffphoto")
    uri = await store.put(new_key("jpg"), source, "image/jpeg")
    async with sessionmaker.begin() as session:
        await repository.upsert_user(session, owner, owner, is_demo=True)
        row = await repository.add_attachment(
            session,
            Attachment(
                id=repository.new_id("att"),
                user_id=owner,
                kind="image",
                storage_uri=uri,
                mime="image/jpeg",
                size=8,
                status="ready",
            ),
        )
        return row.id


async def test_loads_only_the_users_attachments_and_caches_analyses(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    store = LocalMediaStore(tmp_path / "media", MediaSigner("s", ttl_s=60))
    mine = await _attachment(sessionmaker, store, tmp_path, "demo_media_a")
    theirs = await _attachment(sessionmaker, store, tmp_path, "demo_media_b")
    source = AttachmentMediaSource(sessionmaker, store)

    loaded = await source.load([mine, theirs, "att_missing"], "demo_media_a")
    assert [m.attachment_id for m in loaded] == [mine]
    assert (loaded[0].kind, loaded[0].mime, loaded[0].analysis) == ("image", "image/jpeg", None)
    assert await source.read(loaded[0]) == b"\xff\xd8\xffphoto"
    assert await source.load([mine], None) == []

    await source.save_analysis(mine, {"vision": {"brand": "LG"}})
    [again] = await source.load([mine], "demo_media_a")
    assert again.analysis == {"vision": {"brand": "LG"}}
