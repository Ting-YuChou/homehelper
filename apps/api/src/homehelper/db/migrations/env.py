import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from homehelper.core.config import get_settings
from homehelper.db.models import Base
from homehelper.mcp_servers import models as _mcp_models  # noqa: F401  (registers mock_* tables)

target_metadata = Base.metadata


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    # KB snapshot tables are owned by ingestion, not by migrations.
    return not (type_ == "table" and name is not None and name.startswith("data_kb_"))


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations() -> None:
    # Tests pass the database explicitly; otherwise it comes from the settings (env / .env).
    url = context.config.attributes.get("database_url") or get_settings().database_url
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported; run against a database")
asyncio.run(run_migrations())
