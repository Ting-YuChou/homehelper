"""Postgres checkpointer for the journey agent (spec §14.1): LangGraph's own tables, kept apart
from the application tables in the `langgraph` schema and created by `setup()`, not Alembic."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from homehelper.agent.graph import checkpoint_serde
from homehelper.db.urls import psycopg_conninfo

SCHEMA = "langgraph"


@asynccontextmanager
async def postgres_checkpointer(
    database_url: str, *, max_size: int = 10
) -> AsyncIterator[AsyncPostgresSaver]:
    url = psycopg_conninfo(database_url)
    async with AsyncConnectionPool(
        url,
        max_size=max_size,
        open=False,
        kwargs={
            # What AsyncPostgresSaver expects of its connections.
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": f"-c search_path={SCHEMA}",
        },
    ) as pool:
        async with pool.connection() as conn:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        saver = AsyncPostgresSaver(pool, serde=checkpoint_serde())  # type: ignore[arg-type]
        await saver.setup()
        yield saver
