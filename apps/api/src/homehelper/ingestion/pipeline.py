"""`homehelper ingest` (M1-04): manifest → parse (cached) → chunk → embed → new kb_version."""

import asyncio
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import openai
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import BaseNode, TextNode
from llama_index.embeddings.openai import OpenAIEmbedding
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from homehelper.core.config import Settings
from homehelper.core.logging import get_logger
from homehelper.db.models import KBVersion
from homehelper.ingestion.chunking import Chunk, ManualChunker
from homehelper.ingestion.manifest import ManualEntry, load_manifest
from homehelper.ingestion.parse import ManualParser, ParsedManual
from homehelper.knowledge.store import open_store, table_for
from homehelper.llm import ModelRegistry

log = get_logger(__name__)

# Bump when chunking or node layout changes, so the manifest hash reflects it.
PIPELINE_VERSION = "chunker-1"
KEEP_VERSIONS = 5
EMBED_BATCH = 100
EMBED_RETRIES = 8  # the OpenAI tokens-per-minute limit is hit on full rebuilds


@dataclass
class IngestResult:
    kb_version: str
    chunk_count: int
    manuals: int
    parsed_now: int


def manifest_hash(manifest_path: Path, embedding_model: str) -> str:
    digest = hashlib.sha256(manifest_path.read_bytes())
    digest.update(f"|{PIPELINE_VERSION}|{embedding_model}".encode())
    return digest.hexdigest()


def to_node(chunk: Chunk, embedding: list[float]) -> BaseNode:
    return TextNode(
        id_=chunk.chunk_id,
        text=chunk.text,
        embedding=embedding,
        metadata=chunk.metadata.model_dump(mode="json"),
    )


async def next_kb_version(sessions: async_sessionmaker, today: datetime) -> str:
    prefix = f"kb_{today:%Y%m%d}_"
    async with sessions() as session:
        existing = await session.scalars(
            select(KBVersion.version).where(KBVersion.version.like(f"{prefix}%"))
        )
        numbers = [int(v.rsplit("_", 1)[1]) for v in existing]
    return f"{prefix}{max(numbers, default=0) + 1:02d}"


def referenced_versions(releases_dir: Path) -> set[str]:
    """kb_versions mentioned by any release manifest (never deleted by retention)."""
    found: set[str] = set()
    for path in releases_dir.glob("*.yaml"):
        found.update(re.findall(r"\bkb_\d{8}_\d{2}\b", path.read_text()))
    return found


async def enforce_retention(engine: AsyncEngine, releases_dir: Path) -> list[str]:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        ready = list(
            await session.scalars(
                select(KBVersion.version)
                .where(KBVersion.status == "ready")
                .order_by(KBVersion.version.desc())
            )
        )
    keep = set(ready[:KEEP_VERSIONS]) | referenced_versions(releases_dir)
    dropped = [v for v in ready if v not in keep]
    async with engine.begin() as conn:
        for version in dropped:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table_for(version)}"'))
            await conn.execute(
                update(KBVersion).where(KBVersion.version == version).values(status="deleted")
            )
    return dropped


async def embed_chunks(
    embedder: BaseEmbedding, chunks: Sequence[Chunk], concurrency: int = 2
) -> list[list[float]]:
    batches = [chunks[i : i + EMBED_BATCH] for i in range(0, len(chunks), EMBED_BATCH)]
    semaphore = asyncio.Semaphore(concurrency)

    async def embed(batch: Sequence[Chunk]) -> list[list[float]]:
        async with semaphore:
            for attempt in range(EMBED_RETRIES):
                try:
                    return await embedder.aget_text_embedding_batch([c.text for c in batch])
                except openai.RateLimitError:
                    if attempt == EMBED_RETRIES - 1:
                        raise
                    await asyncio.sleep(min(60, 2 ** (attempt + 1)))
        raise AssertionError("unreachable")

    results = await asyncio.gather(*(embed(b) for b in batches))
    return [vector for batch in results for vector in batch]


async def ingest(
    settings: Settings,
    engine: AsyncEngine,
    *,
    parse_concurrency: int = 6,
    embedder: BaseEmbedding | None = None,
) -> IngestResult:
    manuals_dir = settings.manuals_dir
    manifest_path = manuals_dir / "manifest.yaml"
    entries = [e for e in load_manifest(manifest_path) if e.reviewed]
    if not entries:
        raise RuntimeError("no reviewed manifest entries; run `homehelper manifest draft` first")

    registry = ModelRegistry.load()
    embedding_model = registry.embedding.model.split("/", 1)[-1]
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    # 1. Parse (cached by PDF hash, so only new or changed manuals cost anything).
    parser = ManualParser(
        settings.llama_cloud_api_key.get_secret_value(), settings.data_dir / "parsed"
    )
    semaphore = asyncio.Semaphore(parse_concurrency)

    async def parse(entry: ManualEntry) -> tuple[ParsedManual, bool]:
        async with semaphore:
            return await parser.parse(entry, manuals_dir / "pdfs" / entry.file)

    parsed = await asyncio.gather(*(parse(e) for e in entries))
    parsed_now = sum(1 for _, cached in parsed if not cached)

    # 2. Chunk.
    chunker = ManualChunker()
    chunks = [
        c for entry, (pm, _) in zip(entries, parsed, strict=True) for c in chunker.chunk(entry, pm)
    ]
    log.info("chunked", manuals=len(entries), chunks=len(chunks))

    # 3. Register the version, then embed and write its table.
    version = await next_kb_version(sessions, datetime.now(UTC))
    async with sessions() as session:
        session.add(
            KBVersion(
                version=version,
                manifest_hash=manifest_hash(manifest_path, embedding_model),
                embedding_model=embedding_model,
                embedding_dim=registry.embedding.dimensions,
                chunk_count=0,
                status="building",
            )
        )
        await session.commit()

    store = open_store(settings.database_url, version, registry.embedding.dimensions, create=True)
    try:
        embedder = embedder or OpenAIEmbedding(
            model=embedding_model,
            api_key=settings.openai_api_key.get_secret_value(),
            embed_batch_size=EMBED_BATCH,
        )
        vectors = await embed_chunks(embedder, chunks)
        nodes = [to_node(c, v) for c, v in zip(chunks, vectors, strict=True)]
        for i in range(0, len(nodes), 500):
            await store.async_add(nodes[i : i + 500])
    except Exception:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table_for(version)}"'))
            await conn.execute(
                update(KBVersion).where(KBVersion.version == version).values(status="failed")
            )
        raise
    finally:
        await store.close()

    async with engine.begin() as conn:
        await conn.execute(
            update(KBVersion)
            .where(KBVersion.version == version)
            .values(status="ready", chunk_count=len(chunks))
        )
    dropped = await enforce_retention(engine, settings.releases_dir)
    log.info("ingested", kb_version=version, chunks=len(chunks), dropped_versions=dropped)
    return IngestResult(version, len(chunks), len(entries), parsed_now)
