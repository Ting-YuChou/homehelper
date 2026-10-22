"""The startup upsert of the `releases` row (spec §17.3) against real Postgres."""

from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homehelper.db.models import Release
from homehelper.releases.manifest import Gates, ReleaseManifest
from homehelper.releases.runtime import upsert_release

pytestmark = pytest.mark.integration

RELEASE_ID = "r-integration-test"


async def test_upsert_release_inserts_then_updates(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    engine = sessionmaker.kw["bind"]
    manifest = ReleaseManifest(
        id=RELEASE_ID,
        git_sha="abc1234",
        kb_version="kb_20261030_01",
        models={"nlu": "anthropic/claude-haiku-5-5"},
        gates=Gates(resolution_rate_min=0.5),
    )
    path = Path("releases") / f"{RELEASE_ID}.yaml"
    try:
        await upsert_release(engine, manifest, path)
        await upsert_release(engine, manifest.model_copy(update={"git_sha": "def5678"}), path)
        async with sessionmaker() as session:
            row = await session.scalar(select(Release).where(Release.id == RELEASE_ID))
        assert row is not None
        assert (row.git_sha, row.kb_version) == ("def5678", "kb_20261030_01")
        assert row.models == {"nlu": "anthropic/claude-haiku-5-5"}
        assert row.eval_report_uri == str(path)
    finally:
        async with sessionmaker.begin() as session:
            await session.execute(delete(Release).where(Release.id == RELEASE_ID))
