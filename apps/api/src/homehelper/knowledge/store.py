"""Frozen knowledge-base snapshots in Postgres + pgvector (spec §10.3).

Each `kb_version` (e.g. `kb_20261021_01`) is its own LlamaIndex `PGVectorStore` table
(`data_kb_20261021_01`), written once by ingestion and never modified afterwards.
"""

import re

from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.vector_stores.postgres.base import PGType

from homehelper.db.urls import asyncpg_url, psycopg2_url

KB_VERSION = re.compile(r"^kb_\d{8}_\d{2}$")

HNSW = {
    "hnsw_m": 16,
    "hnsw_ef_construction": 64,
    "hnsw_ef_search": 100,
    "hnsw_dist_method": "vector_cosine_ops",
}
# Metadata keys the retriever filters on; indexed so filters stay cheap.
INDEXED_METADATA: set[tuple[str, PGType]] = {
    ("doc_id", "text"),
    ("category", "text"),
    ("chunk_type", "text"),
}


def table_for(kb_version: str) -> str:
    """Physical table name (LlamaIndex prefixes `data_`)."""
    return f"data_{kb_version}"


def open_store(
    database_url: str, kb_version: str, embed_dim: int, *, create: bool = False
) -> PGVectorStore:
    if not KB_VERSION.fullmatch(kb_version):
        raise ValueError(f"invalid kb_version: {kb_version!r}")
    return PGVectorStore.from_params(
        # LlamaIndex creates tables over a sync connection.
        connection_string=psycopg2_url(database_url),
        async_connection_string=asyncpg_url(database_url),
        table_name=kb_version,
        embed_dim=embed_dim,
        hybrid_search=True,
        text_search_config="english",
        use_jsonb=True,
        hnsw_kwargs=HNSW,
        indexed_metadata_keys=INDEXED_METADATA,
        perform_setup=create,
    )
