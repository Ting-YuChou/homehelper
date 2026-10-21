import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


async def test_migrations_upgrade_to_head_and_create_kb_versions() -> None:
    # env.py runs its own event loop, so drive Alembic from a worker thread.
    await asyncio.to_thread(command.upgrade, Config(str(ALEMBIC_INI)), "head")
    engine = create_async_engine(
        os.environ.get(
            "DATABASE_URL", "postgresql+asyncpg://homehelper:homehelper@localhost:5432/homehelper"
        )
    )
    async with engine.connect() as conn:
        tables = await conn.execute(text("SELECT to_regclass('public.kb_versions')"))
        extension = await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
        assert tables.scalar() == "kb_versions"
        assert extension.scalar() == 1
    await engine.dispose()
