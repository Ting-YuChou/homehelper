import time

from homehelper.knowledge.schemas import CategoryId
from homehelper_evals.retrieval.dataset import load_cases
from homehelper_evals.retrieval.metrics import (
    CaseResult,
    best_threshold,
    chunk_recall_at_5,
    own_manual_share,
    summarize,
)
from homehelper_evals.retrieval.run import (
    CONDITIONS,
    PRODUCTION_TAU,
    RateLimitedReranker,
    wrong_category,
)


def result(
    case_id: str, docs: list[str], spans: list[tuple[str, int, int]] | None = None
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        condition="category",
        doc_id="a",
        category="dryer",
        retrieved_doc_ids=docs,
        retrieved_spans=spans or [],
        filter_level="category",
        top_score=0.5,
        sufficient=True,
    )


def test_summarize_recall_hit_and_mrr() -> None:
    summary = summarize([result("1", ["a", "b"]), result("2", ["b", "a"]), result("3", ["b"])])
    assert summary.n == 3
    assert summary.recall_at_5 == round(2 / 3, 4)
    assert summary.hit_at_1 == round(1 / 3, 4)
    assert summary.mrr_at_5 == round((1 + 0.5) / 3, 4)


def test_chunk_recall_uses_page_overlap_and_skips_unlabelled() -> None:
    results = [
        result("1", ["a"], [("a", 10, 11)]),  # page 11 is relevant
        result("2", ["a"], [("a", 3, 3)]),
        result("3", ["b"], [("b", 10, 10)]),  # right page, wrong manual
        result("4", ["a"], [("a", 1, 1)]),  # no label
    ]
    labels = {"1": {11}, "2": {9}, "3": {10}, "4": set()}
    assert chunk_recall_at_5(results, labels) == {"n": 3, "recall_at_5": round(1 / 3, 4)}


def test_best_threshold_separates_scores() -> None:
    best = best_threshold([0.8, 0.7, 0.6], [0.2, 0.3, 0.65])
    assert best["tau"] == 0.6
    assert best["recall"] == 1.0
    assert best["precision"] == 0.75


def test_cases_cover_dataset_with_manifest_labels() -> None:
    cases = load_cases()
    assert len(cases) > 900
    assert {c.split for c in cases} == {"dev", "test"}
    fridge = [c for c in cases if c.doc_id == "samsung-rf23db"]
    assert fridge and all(c.brand == "Samsung" for c in fridge)  # v1 labelled it LG


def test_wrong_category_is_always_different() -> None:
    assert all(wrong_category(c) != c for c in CategoryId)


async def test_rate_limited_reranker_spaces_calls() -> None:
    class Inner:
        async def rerank(
            self, query: str, documents: list[str], top_n: int
        ) -> list[tuple[int, float]]:
            return [(0, 1.0)]

    limited = RateLimitedReranker(Inner(), per_minute=600)  # 0.1 s apart
    started = time.monotonic()
    for _ in range(3):
        await limited.rerank("q", ["d"], 1)
    assert time.monotonic() - started >= 0.2
    assert limited.calls == 3


def test_own_manual_share_counts_chunks_not_cases() -> None:
    assert own_manual_share([result("1", ["a", "a", "b"]), result("2", ["b"])]) == 0.5
    assert own_manual_share([]) == 0


def test_model_condition_searches_with_the_manuals_model_number() -> None:
    case = next(c for c in load_cases() if c.doc_id == "lg-wm4000h-a")
    assert case.model_number == "WM4000H0A"  # WM4000H*A, the inner wildcard filled in
    query = CONDITIONS["model"](case)
    assert (query.model_number, query.brand, query.category) == (
        "WM4000H0A",
        "LG",
        CategoryId.WASHING_MACHINE,
    )
    assert "model" in PRODUCTION_TAU
