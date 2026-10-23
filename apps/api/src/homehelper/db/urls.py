"""Per-driver spellings of `DATABASE_URL` (ADR-011).

The same database is reached through asyncpg (SQLAlchemy, LlamaIndex async), psycopg 3 (the
LangGraph checkpointer) and psycopg2 (LlamaIndex sync). libpq-style drivers take `sslmode`;
asyncpg takes `ssl` and rejects libpq-only options such as Neon's `channel_binding`.
"""

from sqlalchemy.engine import URL, make_url

_SCHEMES = {"postgres", "postgresql"}
_LIBPQ_ONLY = {"channel_binding"}


def _parse(database_url: str) -> URL:
    url = make_url(database_url)
    if url.drivername.split("+", 1)[0] not in _SCHEMES:
        raise ValueError(f"not a Postgres URL: {url.drivername}://...")
    return url


def _render(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def asyncpg_url(database_url: str) -> str:
    url = _parse(database_url)
    query = {k: v for k, v in url.query.items() if k not in _LIBPQ_ONLY}
    if "sslmode" in query:
        query["ssl"] = query.pop("sslmode")
    return _render(url.set(drivername="postgresql+asyncpg", query=query))


def _libpq(database_url: str, drivername: str) -> str:
    url = _parse(database_url)
    query = dict(url.query)
    if "ssl" in query:
        query["sslmode"] = query.pop("ssl")
    return _render(url.set(drivername=drivername, query=dict(sorted(query.items()))))


def psycopg_conninfo(database_url: str) -> str:
    """A libpq URI for psycopg 3."""
    return _libpq(database_url, "postgresql")


def psycopg2_url(database_url: str) -> str:
    """A SQLAlchemy URL for the psycopg2 driver."""
    return _libpq(database_url, "postgresql+psycopg2")
