"""Shared fixtures for tests against real Postgres and Redis (docker compose locally, service
containers in CI). Redis tests use database 15 and flush it, so they never touch dev data."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homehelper.db.engine import create_engine, create_sessionmaker

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
REDIS_TEST_DB = 15


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://homehelper:homehelper@localhost:5432/homehelper"
    )


def redis_test_url() -> str:
    base = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return f"{base.rsplit('/', 1)[0]}/{REDIS_TEST_DB}"


@pytest.fixture(scope="session")
def migrated() -> Iterator[None]:
    # env.py runs its own event loop; a sync session fixture has none running.
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    yield


@pytest.fixture
async def sessionmaker(migrated: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url())
    yield create_sessionmaker(engine)
    await engine.dispose()
