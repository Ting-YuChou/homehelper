"""Production adapters for the retriever's protocols: pgvector search, OpenAI query embeddings,
Cohere rerank, and the factory that wires them together."""

import re

import cohere
from llama_index.core.vector_stores.types import (
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
    VectorStoreQuery,
    VectorStoreQueryMode,
)
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from homehelper.core.config import Settings
from homehelper.db.models import KBVersion
from homehelper.ingestion.manifest import load_manifest
from homehelper.knowledge.retriever import (
    Candidate,
    Filters,
    KnowledgeRetriever,
    ResultCache,
    RetrieverConfig,
    WebFallback,
)
from homehelper.knowledge.store import open_store
from homehelper.llm import ModelRegistry

# PGVectorStore interpolates filter values into SQL text. Values come from the manifest and enums,
# never raw user input, but refuse anything outside this set so injection is impossible.
_SAFE_FILTER_VALUE = re.compile(r"^[A-Za-z0-9 ._+\-]{1,100}$")


def to_metadata_filters(filters: Filters) -> MetadataFilters | None:
    if not filters:
        return None
    for key, value in filters.items():
        for item in value if isinstance(value, list) else [value]:
            if not _SAFE_FILTER_VALUE.fullmatch(item):
                raise ValueError(f"unsafe filter value for {key!r}: {item!r}")
    return MetadataFilters(
        filters=[
            MetadataFilter(key=key, value=value, operator=FilterOperator.IN)
            if isinstance(value, list)
            else MetadataFilter(key=key, value=value, operator=FilterOperator.EQ)
            for key, value in filters.items()
        ]
    )


class PgSearchBackend:
    def __init__(self, store: PGVectorStore) -> None:
        self._store = store

    async def dense(self, embedding: list[float], k: int, filters: Filters) -> list[Candidate]:
        return await self._query(
            VectorStoreQuery(
                query_embedding=embedding,
                similarity_top_k=k,
                filters=to_metadata_filters(filters),
                mode=VectorStoreQueryMode.DEFAULT,
            )
        )

    async def sparse(self, text: str, k: int, filters: Filters) -> list[Candidate]:
        return await self._query(
            VectorStoreQuery(
                query_str=text,
                similarity_top_k=k,
                sparse_top_k=k,
                filters=to_metadata_filters(filters),
                mode=VectorStoreQueryMode.SPARSE,
            )
        )

    async def _query(self, query: VectorStoreQuery) -> list[Candidate]:
        result = await self._store.aquery(query)
        nodes = result.nodes or []
        scores = result.similarities or [0.0] * len(nodes)
        return [
            Candidate(
                chunk_id=node.node_id,
                text=node.get_content(),
                metadata=dict(node.metadata),
                score=float(score),
            )
            for node, score in zip(nodes, scores, strict=True)
        ]

    async def close(self) -> None:
        await self._store.close()


class OpenAIQueryEmbedder:
    def __init__(self, model: str, api_key: str) -> None:
        self._embedding = OpenAIEmbedding(model=model, api_key=api_key)

    async def embed_query(self, text: str) -> list[float]:
        return await self._embedding.aget_query_embedding(text)


class CohereReranker:
    def __init__(self, model: str, api_key: str) -> None:
        self._client = cohere.AsyncClientV2(api_key=api_key)
        self._model = model

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        response = await self._client.rerank(
            model=self._model, query=query, documents=documents, top_n=top_n
        )
        return [(r.index, float(r.relevance_score)) for r in response.results]


async def resolve_kb_version(engine: AsyncEngine, configured: str | None) -> str:
    sessions = async_sessionmaker(engine)
    async with sessions() as session:
        stmt = select(KBVersion.version).where(KBVersion.status == "ready")
        if configured:
            stmt = stmt.where(KBVersion.version == configured)
        version = await session.scalar(stmt.order_by(KBVersion.version.desc()).limit(1))
    if version is None:
        raise RuntimeError(f"no ready kb_version (configured: {configured!r}); run `make ingest`")
    return version


async def build_retriever(
    settings: Settings,
    engine: AsyncEngine,
    *,
    cache: ResultCache | None = None,
    web: WebFallback | None = None,
    config: RetrieverConfig | None = None,
    registry: ModelRegistry | None = None,
) -> tuple[KnowledgeRetriever, PgSearchBackend]:
    """Returns the retriever and its backend (close the backend on shutdown)."""
    registry = registry or ModelRegistry.load()
    kb_version = await resolve_kb_version(engine, settings.kb_version)
    backend = PgSearchBackend(
        open_store(settings.database_url, kb_version, registry.embedding.dimensions)
    )
    cohere_key = settings.cohere_api_key.get_secret_value()
    reranker = (
        CohereReranker(registry.rerank.model.split("/", 1)[-1], cohere_key) if cohere_key else None
    )
    manuals = [m for m in load_manifest(settings.manuals_dir / "manifest.yaml") if m.reviewed]
    retriever = KnowledgeRetriever(
        backend,
        OpenAIQueryEmbedder(
            registry.embedding.model.split("/", 1)[-1], settings.openai_api_key.get_secret_value()
        ),
        manuals,
        kb_version=kb_version,
        reranker=reranker,
        web=web,
        cache=cache,
        config=config,
    )
    return retriever, backend
