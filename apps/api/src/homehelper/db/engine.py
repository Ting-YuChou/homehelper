from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from homehelper.db.urls import asyncpg_url


def create_engine(database_url: str) -> AsyncEngine:
    # Connections are opened lazily on first use.
    return create_async_engine(asyncpg_url(database_url), pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # Rows stay readable after commit; handlers return them right away.
    return async_sessionmaker(engine, expire_on_commit=False)
