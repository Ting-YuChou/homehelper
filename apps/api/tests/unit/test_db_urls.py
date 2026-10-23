"""One DATABASE_URL, three drivers (ADR-011): asyncpg (SQLAlchemy and LlamaIndex async),
psycopg 3 (the LangGraph checkpointer) and psycopg2 (LlamaIndex sync). Neon hands out
`postgresql://...?sslmode=require&channel_binding=require`, which asyncpg does not accept."""

import pytest

from homehelper.db.urls import asyncpg_url, psycopg2_url, psycopg_conninfo

LOCAL = "postgresql+asyncpg://homehelper:homehelper@localhost:5432/homehelper"
NEON = "postgresql://u:p%40ss@ep-x.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


def test_local_urls_are_unchanged_apart_from_the_driver() -> None:
    assert asyncpg_url(LOCAL) == LOCAL
    assert psycopg_conninfo(LOCAL) == "postgresql://homehelper:homehelper@localhost:5432/homehelper"
    assert psycopg2_url(LOCAL).startswith("postgresql+psycopg2://homehelper:homehelper@")


def test_neon_tls_options_are_spelled_per_driver() -> None:
    assert asyncpg_url(NEON) == (
        "postgresql+asyncpg://u:p%40ss@ep-x.us-west-2.aws.neon.tech/neondb?ssl=require"
    )
    assert psycopg_conninfo(NEON) == (
        "postgresql://u:p%40ss@ep-x.us-west-2.aws.neon.tech/neondb"
        "?channel_binding=require&sslmode=require"
    )
    assert psycopg2_url(NEON).endswith("/neondb?channel_binding=require&sslmode=require")


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_any_postgres_scheme_is_accepted(scheme: str) -> None:
    assert asyncpg_url(f"{scheme}://u:p@h/db").startswith("postgresql+asyncpg://")


def test_an_asyncpg_ssl_option_maps_back_to_sslmode() -> None:
    assert psycopg_conninfo("postgresql+asyncpg://u:p@h/db?ssl=require").endswith(
        "?sslmode=require"
    )


def test_other_databases_are_rejected() -> None:
    with pytest.raises(ValueError, match="not a Postgres URL"):
        asyncpg_url("mysql://u:p@h/db")
