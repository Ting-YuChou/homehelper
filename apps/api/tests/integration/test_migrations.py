import asyncio
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import ALEMBIC_INI, alembic_config, database_url

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


async def _regclasses(names: tuple[str, ...], url: str) -> list[str | None]:
    engine = create_async_engine(url)
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


@pytest.fixture
async def scratch_database() -> AsyncIterator[str]:
    """A throwaway database: the round trip drops the app tables, and the integration database
    is the dev database, whose annotations and exported cases must survive a test run."""
    name = f"{make_url(database_url()).database}_migrations"
    url = make_url(database_url()).set(database=name).render_as_string(hide_password=False)
    admin = create_async_engine(database_url(), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    yield url
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    await admin.dispose()


async def test_app_tables_migration_round_trips(scratch_database: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = scratch_database
    await asyncio.to_thread(command.upgrade, config, "head")
    assert await _regclasses(APP_TABLES, scratch_database) == list(APP_TABLES)

    await asyncio.to_thread(command.downgrade, config, "09c3d5a63334-1")
    assert await _regclasses(APP_TABLES, scratch_database) == [None] * len(APP_TABLES)

    await asyncio.to_thread(command.upgrade, config, "head")
    # The models and the migrations agree (no pending autogenerate operations).
    await asyncio.to_thread(command.check, config)
