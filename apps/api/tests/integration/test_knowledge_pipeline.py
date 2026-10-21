import asyncio
import json
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from llama_index.core.embeddings import MockEmbedding
from sqlalchemy import delete, text

from homehelper.db.engine import create_engine
from homehelper.db.models import KBVersion
from homehelper.ingestion.manifest import ManualEntry, save_manifest
from homehelper.ingestion.parse import ParsedManual, ParsedPage, cache_path
from homehelper.ingestion.pipeline import ingest
from homehelper.knowledge.backends import PgSearchBackend
from homehelper.knowledge.retriever import KnowledgeRetriever
from homehelper.knowledge.schemas import CategoryId, RetrievalQuery
from homehelper.knowledge.store import open_store, table_for
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://homehelper:homehelper@localhost:5432/homehelper"
)
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
DIM = 1536


class ConstantEmbedder:
    async def embed_query(self, text: str) -> list[float]:
        return [0.5] * DIM


async def test_ingest_then_retrieve_against_postgres(tmp_path: Path) -> None:
    await asyncio.to_thread(command.upgrade, Config(str(ALEMBIC_INI)), "head")
    entry = ManualEntry(
        doc_id="acme-wm100",
        file="washing_machine/Acme/wm100.pdf",
        category=CategoryId.WASHING_MACHINE,
        brand="Acme",
        title="Acme WM100 Washer",
        model_patterns=["WM100*"],
        pages=2,
        sha256="ab" * 32,
        reviewed=True,
    )
    (tmp_path / "manuals").mkdir()
    save_manifest(tmp_path / "manuals" / "manifest.yaml", [entry])
    parsed = ParsedManual(
        doc_id=entry.doc_id,
        sha256=entry.sha256,
        tier="cost_effective",
        pages=[
            ParsedPage(
                page=1,
                markdown="# Installation\n\nLevel the washer on a firm floor before first use.",
            ),
            ParsedPage(
                page=2,
                markdown=(
                    "# Troubleshooting\n\n| Problem | Solution |\n| --- | --- |\n"
                    "| Water does not drain | Clean the drain pump filter and check the hose. |"
                ),
            ),
        ],
    )
    cache = cache_path(tmp_path / "parsed", entry.sha256, "cost_effective")
    cache.parent.mkdir()
    cache.write_text(json.dumps(parsed.model_dump()))

    settings = make_settings(
        data_dir=tmp_path, releases_dir=tmp_path / "releases", database_url=DATABASE_URL
    )
    engine = create_engine(DATABASE_URL)
    result = await ingest(settings, engine, embedder=MockEmbedding(embed_dim=DIM), retention=False)
    try:
        assert result.chunk_count == 2 and result.parsed_now == 0
        backend = PgSearchBackend(open_store(DATABASE_URL, result.kb_version, DIM))
        retriever = KnowledgeRetriever(
            backend, ConstantEmbedder(), [entry], kb_version=result.kb_version
        )
        found = await retriever.search(
            RetrievalQuery(
                query_en="water does not drain",
                category=CategoryId.WASHING_MACHINE,
                model_number="WM100-X",
            )
        )
        await backend.close()
        assert found.filter_level == "model"
        assert found.chunks[0].metadata.doc_id == "acme-wm100"
        assert found.chunks[0].metadata.page_start == 2
        assert found.chunks[0].metadata.chunk_type == "troubleshooting_table"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table_for(result.kb_version)}"'))
            await conn.execute(delete(KBVersion).where(KBVersion.version == result.kb_version))
        await engine.dispose()
