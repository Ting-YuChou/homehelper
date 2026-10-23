import asyncio

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import alembic_config, database_url

pytestmark = pytest.mark.integration

APP_TABLES = (
    "users",
    "conversations",
    "messages",
    "attachments",
    "feedback",
    "annotations",
    "regression_cases",
    "eval_reports",
    "releases",
)


async def _regclasses(names: tuple[str, ...]) -> list[str | None]:
    engine = create_async_engine(database_url())
    async with engine.connect() as conn:
        found = [
            (await conn.execute(text(f"SELECT to_regclass('public.{name}')"))).scalar()
            for name in names
        ]
    await engine.dispose()
    return found


async def test_migrations_upgrade_to_head_and_create_kb_versions() -> None:
    # env.py runs its own event loop, so drive Alembic from a worker thread.
    await asyncio.to_thread(command.upgrade, alembic_config(), "head")
    engine = create_async_engine(database_url())
    async with engine.connect() as conn:
        tables = await conn.execute(text("SELECT to_regclass('public.kb_versions')"))
        extension = await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
        assert tables.scalar() == "kb_versions"
        assert extension.scalar() == 1
    await engine.dispose()


async def test_app_tables_migration_round_trips() -> None:
    config = alembic_config()
    await asyncio.to_thread(command.upgrade, config, "head")
    assert await _regclasses(APP_TABLES) == list(APP_TABLES)

    await asyncio.to_thread(command.downgrade, config, "09c3d5a63334-1")
    assert await _regclasses(APP_TABLES) == [None] * len(APP_TABLES)

    await asyncio.to_thread(command.upgrade, config, "head")
    # The models and the migrations agree (no pending autogenerate operations).
    await asyncio.to_thread(command.check, config)
