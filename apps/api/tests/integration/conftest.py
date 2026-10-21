"""Shared fixtures for tests against real Postgres and Redis (docker compose locally, service
containers in CI). Redis tests use database 15 and flush it, so they never touch dev data."""

import json
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homehelper.core.config import Settings
from homehelper.db.engine import create_engine, create_sessionmaker
from homehelper.db.redis import create_redis
from homehelper.main import create_app
from tests.conftest import make_settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
REDIS_TEST_DB = 15
# Read at import: the autouse fixture in tests/conftest.py removes these from the environment
# for every test, so reading them inside a test would silently fall back to the defaults.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://homehelper:homehelper@localhost:5432/homehelper"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def database_url() -> str:
    return DATABASE_URL


def redis_test_url() -> str:
    return f"{REDIS_URL.rsplit('/', 1)[0]}/{REDIS_TEST_DB}"


def alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = DATABASE_URL
    return config


@pytest.fixture(scope="session")
def migrated() -> Iterator[None]:
    # env.py runs its own event loop; a sync session fixture has none running.
    command.upgrade(alembic_config(), "head")
    yield


@pytest.fixture
async def sessionmaker(migrated: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url())
    yield create_sessionmaker(engine)
    await engine.dispose()


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    """(event name, data) pairs of an SSE body; comment lines (heartbeats) are skipped."""
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        if fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def write_demo_data(data_dir: Path) -> None:
    """A demo user and one manual with a tiny PDF, under a temporary data dir."""
    (data_dir / "mock").mkdir(parents=True)
    users = [{"id": "demo_alex", "display_name": "Alex", "persona": "First-time homeowner"}]
    (data_dir / "mock" / "users.json").write_text(json.dumps(users))
    pdfs = data_dir / "manuals" / "pdfs" / "dishwasher" / "Bosch"
    pdfs.mkdir(parents=True)
    (pdfs / "Bosch_800.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    manifest = [
        {
            "doc_id": "bosch-shx68t55",
            "file": "dishwasher/Bosch/Bosch_800.pdf",
            "category": "dishwasher",
            "brand": "Bosch",
            "title": "Bosch 800 Series Dishwasher",
            "pages": 64,
            "sha256": "0" * 64,
            "reviewed": True,
        },
        {
            "doc_id": "missing-pdf",
            "file": "dishwasher/Nope/missing.pdf",
            "category": "dishwasher",
            "brand": "Nope",
            "title": "Missing",
            "pages": 1,
            "sha256": "0" * 64,
        },
    ]
    (data_dir / "manuals" / "manifest.yaml").write_text(yaml.safe_dump(manifest))


@pytest.fixture
async def redis(migrated: None) -> AsyncIterator[Redis]:
    client = create_redis(redis_test_url())
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def api_settings(tmp_path: Path) -> Settings:
    write_demo_data(tmp_path)
    return make_settings(database_url=database_url(), redis_url=redis_test_url(), data_dir=tmp_path)


@pytest.fixture
async def api(
    api_settings: Settings, redis: Redis, migrated: None
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(api_settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await app.state.conversations.wait_idle()
    await app.state.redis.aclose()
    await app.state.db_engine.dispose()
