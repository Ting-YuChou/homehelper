"""`knowledge.search` (spec §10.4, M1-05).

For each filter level (model → brand + category → category → all, skipping levels the query
can't use): dense top-k + full-text top-k, fused with reciprocal rank fusion (plus an error-code
full-text pass when an error code is known), reranked, then judged sufficient or not. The first
sufficient level wins; if none is, the web fallback (if any) is tried.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from homehelper.core.logging import get_logger
from homehelper.ingestion.manifest import ManualEntry
from homehelper.knowledge.model_numbers import error_code_variants, matches_any
from homehelper.knowledge.schemas import (
    ChunkMetadata,
    FilterLevel,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
    WebFinding,
)

log = get_logger(__name__)

# Metadata equality / membership constraints, e.g. {"category": "dryer", "doc_id": ["a", "b"]}.
Filters = dict[str, str | list[str]]


class RetrieverConfig(BaseModel):
    dense_k: int = 20
    sparse_k: int = 20
    error_code_k: int = 10
    rrf_k: int = 60
    error_code_weight: float = 2.0
    rerank_candidates: int = 25
    # Sufficiency thresholds (calibrated on the dev split in M1-07): on the rerank relevance
    # score, and on dense cosine similarity when reranking is unavailable.
    tau: float = 0.58  # M1-07: F1-optimal on 100 dev queries with rerank-v5.0-fast (P 0.92, R 1.0)
    tau_without_rerank: float = 0.50  # M1-07: F1-optimal 0.496 on dev (P 0.91, R 0.78)


@dataclass
class Candidate:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    score: float  # backend-specific: cosine similarity or ts_rank


@dataclass
class _Scored:
    candidate: Candidate
    fused: float = 0.0
    dense_similarity: float | None = None
    rerank: float | None = None
    sources: set[str] = field(default_factory=set)


class SearchBackend(Protocol):
    async def dense(self, embedding: list[float], k: int, filters: Filters) -> list[Candidate]: ...

    async def sparse(self, text: str, k: int, filters: Filters) -> list[Candidate]: ...


class QueryEmbedder(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        """(index into documents, relevance in [0, 1]) best first."""
        ...


class WebFallback(Protocol):
    async def search(self, query: RetrievalQuery) -> list[WebFinding]: ...


class ResultCache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ex: int) -> Any: ...


def rrf(ranked_lists: Sequence[tuple[float, Sequence[Candidate]]], k: int) -> list[_Scored]:
    """Weighted reciprocal rank fusion over (weight, ranked candidates) lists."""
    scored: dict[str, _Scored] = {}
    for list_index, (weight, candidates) in enumerate(ranked_lists):
        for rank, candidate in enumerate(candidates, start=1):
            entry = scored.setdefault(candidate.chunk_id, _Scored(candidate))
            entry.fused += weight / (k + rank)
            entry.sources.add(str(list_index))
    return sorted(scored.values(), key=lambda s: s.fused, reverse=True)


class KnowledgeRetriever:
    def __init__(
        self,
        backend: SearchBackend,
        embedder: QueryEmbedder,
        manuals: Sequence[ManualEntry],
        *,
        kb_version: str,
        reranker: Reranker | None = None,
        web: WebFallback | None = None,
        cache: ResultCache | None = None,
        config: RetrieverConfig | None = None,
        cache_ttl_s: int = 3600,
    ) -> None:
        self._backend = backend
        self._embedder = embedder
        self._manuals = list(manuals)
        self._brands = {m.brand.lower(): m.brand for m in self._manuals}
        self._kb_version = kb_version
        self._reranker = reranker
        self._web = web
        self._cache = cache
        self._config = config or RetrieverConfig()
        self._cache_ttl_s = cache_ttl_s

    @property
    def kb_version(self) -> str:
        return self._kb_version

    def filter_levels(self, query: RetrievalQuery) -> list[tuple[FilterLevel, Filters]]:
        levels: list[tuple[FilterLevel, Filters]] = []
        category = query.category.value if query.category else None
        if query.model_number:
            doc_ids = [
                m.doc_id
                for m in self._manuals
                if matches_any(query.model_number, m.model_patterns)
                and (category is None or m.category.value == category)
            ]
            if doc_ids:
                levels.append(("model", {"doc_id": doc_ids}))
        brand = self._brands.get((query.brand or "").strip().lower())
        if brand and category:
            levels.append(("brand_category", {"brand": brand, "category": category}))
        if category:
            # Never relax past the user's appliance category: other categories' manuals would
            # only produce confidently wrong answers (spec §10.4 ④).
            levels.append(("category", {"category": category}))
        else:
            if brand:
                levels.append(("brand_category", {"brand": brand}))
            levels.append(("all", {}))
        return levels

    async def search(self, query: RetrievalQuery) -> RetrievalResult:
        cache_key = self._cache_key(query)
        if self._cache is not None:
            cached = await self._cache.get(cache_key)
            if cached:
                return RetrievalResult.model_validate_json(cached)

        embedding = await self._embedder.embed_query(query.query_en)
        best: RetrievalResult | None = None
        for level, filters in self.filter_levels(query):
            result = await self._search_level(query, embedding, level, filters)
            log.info(
                "retrieval_level",
                level=level,
                top_score=result.top_score,
                sufficient=result.sufficient,
                candidates=len(result.chunks),
            )
            if best is None or (result.top_score or 0) > (best.top_score or 0):
                best = result
            if result.sufficient:
                best = result
                break

        result = best or RetrievalResult(query=query, source="none", kb_version=self._kb_version)
        if not result.sufficient and self._web is not None:
            findings = await self._web.search(query)
            if findings:
                result = RetrievalResult(
                    query=query,
                    source="web",
                    web_findings=findings,
                    kb_version=self._kb_version,
                    sufficient=True,
                )
        if self._cache is not None:
            await self._cache.set(cache_key, result.model_dump_json(), ex=self._cache_ttl_s)
        return result

    async def _search_level(
        self, query: RetrievalQuery, embedding: list[float], level: FilterLevel, filters: Filters
    ) -> RetrievalResult:
        config = self._config
        dense = await self._backend.dense(embedding, config.dense_k, filters)
        sparse = await self._backend.sparse(query.query_en, config.sparse_k, filters)
        lists: list[tuple[float, Sequence[Candidate]]] = [(1.0, dense), (1.0, sparse)]
        if query.error_code:
            codes = " ".join(error_code_variants(query.error_code))
            error_hits = await self._backend.sparse(
                codes, config.error_code_k, {**filters, "chunk_type": "error_code"}
            )
            lists.append((config.error_code_weight, error_hits))

        fused = rrf(lists, config.rrf_k)
        similarity = {c.chunk_id: c.score for c in dense}
        for item in fused:
            item.dense_similarity = similarity.get(item.candidate.chunk_id)
        if not fused:
            return RetrievalResult(
                query=query, source="none", filter_level=level, kb_version=self._kb_version
            )

        top = await self._rerank(query.query_en, fused[: config.rerank_candidates], query.top_k)
        if top[0].rerank is not None:
            top_score = top[0].rerank
            above = top_score >= config.tau
        else:
            top_score = max((t.dense_similarity or 0.0) for t in top)
            above = top_score >= config.tau_without_rerank
        chunks = [self._to_chunk(item) for item in top]
        in_category = query.category is None or any(
            c.metadata.category == query.category for c in chunks
        )
        return RetrievalResult(
            query=query,
            source="manual",
            chunks=chunks,
            filter_level=level,
            top_score=round(top_score, 4),
            sufficient=above and in_category,
            kb_version=self._kb_version,
        )

    async def _rerank(self, query: str, items: list[_Scored], top_n: int) -> list[_Scored]:
        if self._reranker is not None:
            try:
                ranked = await self._reranker.rerank(
                    query, [i.candidate.text for i in items], top_n
                )
            except Exception as exc:  # degrade to fused order (spec §9.1 rerank fallback)
                log.warning("rerank_failed", error=repr(exc))
            else:
                out = []
                for index, score in ranked:
                    items[index].rerank = score
                    out.append(items[index])
                if out:
                    return out
        return items[:top_n]

    @staticmethod
    def _to_chunk(item: _Scored) -> RetrievedChunk:
        score = item.rerank if item.rerank is not None else item.fused
        return RetrievedChunk(
            chunk_id=item.candidate.chunk_id,
            text=item.candidate.text,
            score=round(score, 4),
            metadata=ChunkMetadata.model_validate(item.candidate.metadata),
        )

    def _cache_key(self, query: RetrievalQuery) -> str:
        digest = hashlib.sha256(query.model_dump_json().encode()).hexdigest()[:32]
        return f"cache:retrieval:{self._kb_version}:{digest}"
