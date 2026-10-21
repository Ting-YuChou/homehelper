from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    # Connections are opened lazily on first use.
    return create_async_engine(database_url, pool_pre_ping=True)
