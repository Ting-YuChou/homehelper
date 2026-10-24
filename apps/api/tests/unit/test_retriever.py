from typing import Any

import pytest

from homehelper.ingestion.manifest import ManualEntry
from homehelper.knowledge.backends import to_metadata_filters
from homehelper.knowledge.retriever import (
    Candidate,
    Filters,
    KnowledgeRetriever,
    RetrieverConfig,
    rrf,
)
from homehelper.knowledge.schemas import CategoryId, RetrievalQuery, WebFinding

MANUALS = [
    ManualEntry(
        doc_id=f"{brand.lower()}-{cat.value}",
        file=f"{cat.value}/{brand}/x.pdf",
        category=cat,
        brand=brand,
        title="Manual",
        model_patterns=patterns,
        pages=1,
        sha256="0" * 64,
        reviewed=True,
    )
    for brand, cat, patterns in [
        ("LG", CategoryId.WASHING_MACHINE, ["WM3400*"]),
        ("Samsung", CategoryId.WASHING_MACHINE, ["WF45*"]),
        ("LG", CategoryId.DRYER, ["DLE3400*"]),
    ]
]


def cand(chunk_id: str, category: str = "washing_machine", score: float = 0.5) -> Candidate:
    doc_id = chunk_id.split(":")[0]
    return Candidate(
        chunk_id=chunk_id,
        text=f"text of {chunk_id}",
        metadata={
            "doc_id": doc_id,
            "category": category,
            "brand": "LG",
            "page_start": 3,
            "page_end": 3,
            "chunk_type": "general",
        },
        score=score,
    )


class FakeBackend:
    def __init__(self, by_level: dict[str, tuple[list[Candidate], list[Candidate]]]) -> None:
        self.by_level = by_level
        self.calls: list[tuple[str, Filters]] = []

    def _key(self, filters: Filters) -> str:
        if "chunk_type" in filters:
            return "error_code"
        if "doc_id" in filters:
            return "model"
        if "brand" in filters:
            return "brand"
        return "category" if "category" in filters else "all"

    async def dense(self, embedding: list[float], k: int, filters: Filters) -> list[Candidate]:
        self.calls.append(("dense", filters))
        return self.by_level.get(self._key(filters), ([], []))[0][:k]

    async def sparse(self, text: str, k: int, filters: Filters) -> list[Candidate]:
        self.calls.append(("sparse", filters))
        return self.by_level.get(self._key(filters), ([], []))[1][:k]


class FakeEmbedder:
    async def embed_query(self, text: str) -> list[float]:
        return [0.0]


class FakeReranker:
    def __init__(self, scores: dict[str, float] | Exception) -> None:
        self.scores = scores

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        if isinstance(self.scores, Exception):
            raise self.scores
        ranked = sorted(
            (
                (i, self.scores.get(d.removeprefix("text of "), 0.0))
                for i, d in enumerate(documents)
            ),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return ranked[:top_n]


class FakeWeb:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: RetrievalQuery) -> list[WebFinding]:
        self.calls += 1
        return [WebFinding(claim="Check the drain hose.", url="https://www.ifixit.com/x")]


class DictCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, ex: int) -> Any:
        self.data[key] = value


def retriever(backend: FakeBackend, **kwargs: Any) -> KnowledgeRetriever:
    return KnowledgeRetriever(
        backend, FakeEmbedder(), MANUALS, kb_version="kb_20261021_01", **kwargs
    )


def test_filter_levels_follow_spec_order_and_never_leave_the_category() -> None:
    r = retriever(FakeBackend({}))
    q = RetrievalQuery(
        query_en="x", category=CategoryId.WASHING_MACHINE, brand="lg", model_number="wm-3400cw"
    )
    assert r.filter_levels(q) == [
        ("model", {"doc_id": ["lg-washing_machine"]}),
        ("brand_category", {"brand": "LG", "category": "washing_machine"}),
        ("category", {"category": "washing_machine"}),
    ]
    # Unknown brand and a model from another category are skipped; no category -> "all".
    assert r.filter_levels(RetrievalQuery(query_en="x", brand="Acme", model_number="DLE3400")) == [
        ("model", {"doc_id": ["lg-dryer"]}),
        ("all", {}),
    ]


def test_rrf_rewards_agreement_and_weights() -> None:
    a, b, c = cand("a:p1:0"), cand("b:p1:0"), cand("c:p1:0")
    fused = rrf([(1.0, [a, b]), (1.0, [b, c]), (2.0, [c])], k=60)
    assert [f.candidate.chunk_id for f in fused] == ["c:p1:0", "b:p1:0", "a:p1:0"]


async def test_stops_at_first_sufficient_level_with_rerank_scores() -> None:
    backend = FakeBackend({"model": ([cand("lg-washing_machine:p1:0")], [])})
    r = retriever(backend, reranker=FakeReranker({"lg-washing_machine:p1:0": 0.9}))
    q = RetrievalQuery(
        query_en="won't drain", category=CategoryId.WASHING_MACHINE, model_number="WM3400"
    )
    result = await r.search(q)
    assert (result.filter_level, result.sufficient, result.top_score) == ("model", True, 0.9)
    assert result.source == "manual"
    assert result.chunks[0].score == 0.9
    assert all("doc_id" in f for _, f in backend.calls)


async def test_relaxes_when_a_level_is_insufficient_and_keeps_the_best() -> None:
    backend = FakeBackend(
        {
            "brand": ([cand("b:p1:0")], []),
            "category": ([cand("c:p1:0")], [cand("c:p2:0")]),
        }
    )
    reranker = FakeReranker({"b:p1:0": 0.1, "c:p1:0": 0.2, "c:p2:0": 0.25})
    r = retriever(backend, reranker=reranker, config=RetrieverConfig(tau=0.5))
    result = await r.search(
        RetrievalQuery(query_en="x", category=CategoryId.WASHING_MACHINE, brand="LG")
    )
    assert not result.sufficient
    assert result.filter_level == "category"  # the higher-scoring of the insufficient levels
    assert result.top_score == 0.25


async def test_the_identified_models_manual_is_kept_below_tau() -> None:
    """A low-scoring excerpt from the user's own manual beats a high-scoring one from another
    model's manual (ADR-012); the web fallback adds to it instead of replacing it."""
    web = FakeWeb()
    backend = FakeBackend(
        {
            "model": ([cand("lg-washing_machine:p9:0")], []),
            "category": ([cand("samsung-washing_machine:p1:0")], []),
        }
    )
    reranker = FakeReranker({"lg-washing_machine:p9:0": 0.3, "samsung-washing_machine:p1:0": 0.9})
    r = retriever(backend, reranker=reranker, web=web, config=RetrieverConfig(tau=0.5))
    result = await r.search(
        RetrievalQuery(query_en="x", category=CategoryId.WASHING_MACHINE, model_number="WM3400")
    )
    assert (result.filter_level, result.sufficient, result.top_score) == ("model", False, 0.3)
    assert result.source == "manual"
    assert [c.chunk_id for c in result.chunks] == ["lg-washing_machine:p9:0"]
    assert web.calls == 1 and len(result.web_findings) == 1  # e.g. for a how-to answer
    assert all("doc_id" in f for _, f in backend.calls)


async def test_a_model_number_whose_manual_has_no_chunks_still_relaxes() -> None:
    backend = FakeBackend({"category": ([cand("samsung-washing_machine:p1:0")], [])})
    reranker = FakeReranker({"samsung-washing_machine:p1:0": 0.9})
    r = retriever(backend, reranker=reranker, config=RetrieverConfig(tau=0.5))
    result = await r.search(
        RetrievalQuery(query_en="x", category=CategoryId.WASHING_MACHINE, model_number="WM3400")
    )
    assert (result.filter_level, result.sufficient) == ("category", True)


async def test_error_code_pass_is_boosted() -> None:
    backend = FakeBackend(
        {
            "category": ([cand("a:p1:0"), cand("b:p1:0")], [cand("a:p1:0")]),
            "error_code": ([], [cand("b:p1:0")]),
        }
    )
    r = retriever(backend)  # no reranker: fused order decides
    result = await r.search(
        RetrievalQuery(query_en="OE", category=CategoryId.WASHING_MACHINE, error_code="oe")
    )
    assert result.chunks[0].chunk_id == "b:p1:0"
    assert ("sparse", {"category": "washing_machine", "chunk_type": "error_code"}) in backend.calls


async def test_rerank_failure_degrades_to_dense_similarity_threshold() -> None:
    backend = FakeBackend({"category": ([cand("a:p1:0", score=0.62)], [])})
    r = retriever(backend, reranker=FakeReranker(RuntimeError("cohere down")))
    result = await r.search(RetrievalQuery(query_en="x", category=CategoryId.WASHING_MACHINE))
    assert result.sufficient
    assert result.top_score == 0.62


async def test_off_category_chunks_are_never_sufficient() -> None:
    backend = FakeBackend({"category": ([cand("d:p1:0", category="dryer")], [])})
    r = retriever(backend, reranker=FakeReranker({"d:p1:0": 0.99}))
    result = await r.search(RetrievalQuery(query_en="x", category=CategoryId.WASHING_MACHINE))
    assert not result.sufficient


async def test_web_fallback_only_when_manuals_are_insufficient() -> None:
    web = FakeWeb()
    empty = retriever(FakeBackend({}), web=web)
    result = await empty.search(RetrievalQuery(query_en="x", category=CategoryId.WASHING_MACHINE))
    assert (result.source, result.sufficient, web.calls) == ("web", True, 1)
    assert result.web_findings[0].url.startswith("https://www.ifixit.com")

    good = retriever(
        FakeBackend({"category": ([cand("a:p1:0")], [])}),
        web=web,
        reranker=FakeReranker({"a:p1:0": 0.8}),
    )
    await good.search(RetrievalQuery(query_en="x", category=CategoryId.WASHING_MACHINE))
    assert web.calls == 1


async def test_with_web_swaps_only_the_web_fallback() -> None:
    backend = FakeBackend({})
    base = retriever(backend)
    web = FakeWeb()
    result = await base.with_web(web).search(
        RetrievalQuery(query_en="x", category=CategoryId.WASHING_MACHINE)
    )
    assert (result.source, web.calls) == ("web", 1)
    result = await base.search(RetrievalQuery(query_en="x", category=CategoryId.WASHING_MACHINE))
    assert result.source == "none"  # the original keeps no web fallback


async def test_results_are_cached_per_kb_version() -> None:
    backend = FakeBackend({"category": ([cand("a:p1:0")], [])})
    cache = DictCache()
    r = retriever(backend, cache=cache)
    q = RetrievalQuery(query_en="x", category=CategoryId.WASHING_MACHINE)
    first = await r.search(q)
    calls = len(backend.calls)
    assert await r.search(q) == first
    assert len(backend.calls) == calls
    assert all(key.startswith("cache:retrieval:kb_20261021_01:") for key in cache.data)


def test_filters_reject_unsafe_values() -> None:
    assert to_metadata_filters({}) is None
    assert to_metadata_filters({"brand": "Black+Decker", "doc_id": ["a-b", "c.d"]}) is not None
    with pytest.raises(ValueError, match="unsafe filter value"):
        to_metadata_filters({"brand": "x' OR '1'='1"})


# --- without a model number (ADR-013) -------------------------------------------------------

LG_WASHERS = [
    ManualEntry(
        doc_id=f"lg-wm{n}",
        file=f"washing_machine/LG/wm{n}.pdf",
        category=CategoryId.WASHING_MACHINE,
        brand="LG",
        title="Manual",
        model_patterns=[f"WM{n}*"],
        pages=1,
        sha256="0" * 64,
        reviewed=True,
    )
    for n in (1000, 2000, 3000)
]


def test_candidate_manuals_come_before_brand_and_category() -> None:
    r = KnowledgeRetriever(FakeBackend({}), FakeEmbedder(), LG_WASHERS, kb_version="kb_test")
    query = RetrievalQuery(
        query_en="no drain",
        category=CategoryId.WASHING_MACHINE,
        brand="LG",
        doc_ids=["lg-wm1000", "lg-wm3000", "lg-dryer"],
    )
    levels = r.filter_levels(query)
    assert levels[0] == ("candidates", {"doc_id": ["lg-wm1000", "lg-wm3000"]})
    assert [level for level, _ in levels[1:]] == ["brand_category", "category"]
    # A model number that names a manual wins over the candidates.
    with_model = query.model_copy(update={"model_number": "WM2000HA"})
    assert r.filter_levels(with_model)[0] == ("model", {"doc_id": ["lg-wm2000"]})


async def test_candidate_manuals_are_kept_like_the_model_numbers_manual() -> None:
    backend = FakeBackend({"model": ([cand("lg-wm1000:1")], [])})
    r = KnowledgeRetriever(
        backend,
        FakeEmbedder(),
        LG_WASHERS,
        kb_version="kb_test",
        reranker=FakeReranker({"lg-wm1000:1": 0.2}),
        web=(web := FakeWeb()),
    )
    one = RetrievalQuery(
        query_en="no drain", category=CategoryId.WASHING_MACHINE, doc_ids=["lg-wm1000"]
    )
    result = await r.search(one)
    assert (result.filter_level, result.source, len(result.chunks)) == ("candidates", "manual", 1)
    assert web.calls == 1 and result.web_findings  # added to the manual, not replacing it
    # With two left the search stays with them too: other brands' manuals are no better.
    several = one.model_copy(update={"doc_ids": ["lg-wm1000", "lg-wm2000"]})
    kept = await r.search(several)
    assert (kept.filter_level, kept.source, web.calls) == ("candidates", "manual", 2)


async def test_per_doc_caps_the_chunks_from_each_manual() -> None:
    chunks = [cand(f"lg-wm1000:{i}") for i in range(4)] + [cand("lg-wm2000:1"), cand("lg-wm3000:1")]
    scores = {c.chunk_id: 0.9 - i / 100 for i, c in enumerate(chunks)}
    r = KnowledgeRetriever(
        FakeBackend({"model": (chunks, [])}),
        FakeEmbedder(),
        LG_WASHERS,
        kb_version="kb_test",
        reranker=FakeReranker(scores),
    )
    query = RetrievalQuery(
        query_en="no drain",
        category=CategoryId.WASHING_MACHINE,
        doc_ids=["lg-wm1000", "lg-wm2000", "lg-wm3000"],
        per_doc=2,
        top_k=8,
    )
    result = await r.search(query)
    assert [c.chunk_id for c in result.chunks] == [
        "lg-wm1000:0",
        "lg-wm1000:1",
        "lg-wm2000:1",
        "lg-wm3000:1",
    ]


@pytest.mark.parametrize(
    ("mode", "score", "chunks", "findings", "source"),
    [
        ("replace", 0.2, 0, 1, "web"),  # the baseline: web replaces an insufficient result
        ("add_when_insufficient", 0.2, 1, 1, "manual"),
        ("add_when_insufficient", 0.9, 1, 0, "manual"),  # sufficient: no search
        ("always_add", 0.9, 1, 1, "manual"),
    ],
)
async def test_web_mode_decides_what_web_findings_do(
    mode: str, score: float, chunks: int, findings: int, source: str
) -> None:
    r = retriever(
        FakeBackend({"category": ([cand("lg-washing_machine:1")], [])}),
        reranker=FakeReranker({"lg-washing_machine:1": score}),
        web=FakeWeb(),
    )
    query = RetrievalQuery(
        query_en="no drain",
        category=CategoryId.WASHING_MACHINE,
        web=mode,  # type: ignore[arg-type]
    )
    result = await r.search(query)
    assert (len(result.chunks), len(result.web_findings), result.source) == (
        chunks,
        findings,
        source,
    )
