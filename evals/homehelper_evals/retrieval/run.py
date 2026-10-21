"""Run the retrieval evaluation against the current kb_version (spec §16.2, M1-07).

    uv run python -m homehelper_evals.retrieval.run                      # all cases, no rerank
    uv run python -m homehelper_evals.retrieval.run --split dev --rerank --limit 100

Recall metrics use τ = 0, so every search returns its first applicable filter level and the
numbers measure ranking alone. τ is then calibrated on the dev split: positives are dev queries
whose correct manual is in the top 5; negatives are the same queries searched under a wrong
category plus off-topic questions.
"""

import argparse
import asyncio
import json
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from homehelper.core.config import get_settings
from homehelper.core.logging import configure_logging
from homehelper.db.engine import create_engine
from homehelper.ingestion.manifest import load_manifest
from homehelper.knowledge.backends import (
    CohereReranker,
    OpenAIQueryEmbedder,
    PgSearchBackend,
    resolve_kb_version,
)
from homehelper.knowledge.retriever import KnowledgeRetriever, Reranker, RetrieverConfig
from homehelper.knowledge.schemas import CategoryId, RetrievalQuery
from homehelper.knowledge.store import open_store
from homehelper.llm import ModelRegistry
from homehelper_evals import REPORTS_DIR
from homehelper_evals.retrieval.dataset import RetrievalCase, load_cases
from homehelper_evals.retrieval.labels import LABELS_PATH
from homehelper_evals.retrieval.metrics import (
    CaseResult,
    best_threshold,
    by_category,
    chunk_recall_at_5,
    summarize,
)

CONDITIONS: dict[str, Callable[[RetrievalCase], RetrievalQuery]] = {
    "category": lambda c: RetrievalQuery(query_en=c.query, category=c.category),
    "brand_category": lambda c: RetrievalQuery(
        query_en=c.query, category=c.category, brand=c.brand
    ),
    "none": lambda c: RetrievalQuery(query_en=c.query),
}

OFF_TOPIC = [
    "What is the capital of France?",
    "Write a Python function that reverses a string.",
    "Who won the 2022 World Cup?",
    "How do I file my taxes online?",
    "Recommend a good sci-fi novel.",
    "What's the weather like in Tokyo tomorrow?",
    "How do I change the oil in my car?",
    "Explain quantum entanglement simply.",
    "What is a good recipe for banana bread?",
    "How do I reset my email password?",
    "My laptop battery drains quickly, what should I do?",
    "How do I fix a flat bicycle tire?",
    "What are the symptoms of the flu?",
    "Translate 'good morning' into Spanish.",
    "How do I unclog a bathroom sink?",
    "Which stocks should I buy this year?",
    "How do I train my dog to sit?",
    "My phone screen is cracked, can I fix it myself?",
    "How tall is Mount Everest?",
    "Tell me a joke about cats.",
]


class CachingEmbedder:
    def __init__(self, inner: OpenAIQueryEmbedder) -> None:
        self._inner = inner
        self._cache: dict[str, list[float]] = {}

    async def embed_query(self, text: str) -> list[float]:
        if text not in self._cache:
            self._cache[text] = await self._inner.embed_query(text)
        return self._cache[text]


class RateLimitedReranker:
    """Spaces calls to stay under a per-minute limit (Cohere trial keys allow 10/min)."""

    def __init__(self, inner: Reranker, per_minute: float) -> None:
        self._inner = inner
        self._interval = 60.0 / per_minute
        self._lock = asyncio.Lock()
        self._next = 0.0
        self.calls = 0

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        async with self._lock:
            wait = self._next - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._next = time.monotonic() + self._interval
        self.calls += 1
        return await self._inner.rerank(query, documents, top_n)


async def run_cases(
    retriever: KnowledgeRetriever,
    cases: Sequence[RetrievalCase],
    condition: str,
    make_query: Callable[[RetrievalCase], RetrievalQuery],
    concurrency: int,
) -> list[CaseResult]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: RetrievalCase) -> CaseResult:
        async with semaphore:
            result = await retriever.search(make_query(case))
        return CaseResult(
            case_id=case.case_id,
            condition=condition,
            doc_id=case.doc_id,
            category=case.category.value,
            retrieved_doc_ids=[c.metadata.doc_id for c in result.chunks],
            retrieved_spans=[
                (c.metadata.doc_id, c.metadata.page_start, c.metadata.page_end)
                for c in result.chunks
            ],
            filter_level=result.filter_level,
            top_score=result.top_score,
            sufficient=result.sufficient,
        )

    return list(await asyncio.gather(*(one(c) for c in cases)))


def wrong_category(category: CategoryId) -> CategoryId:
    members = list(CategoryId)
    return members[(members.index(category) + 5) % len(members)]


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging("WARNING")
    registry = ModelRegistry.load()
    engine = create_engine(settings.database_url)
    kb_version = await resolve_kb_version(engine, settings.kb_version)
    backend = PgSearchBackend(open_store(settings.database_url, kb_version, 1536))
    reranker: RateLimitedReranker | None = None
    if args.rerank:
        model = args.rerank_model or registry.rerank.model.split("/", 1)[-1]
        reranker = RateLimitedReranker(
            CohereReranker(model, settings.cohere_api_key.get_secret_value()), args.rerank_per_min
        )
    retriever = KnowledgeRetriever(
        backend,
        CachingEmbedder(
            OpenAIQueryEmbedder(
                registry.embedding.model.split("/", 1)[-1],
                settings.openai_api_key.get_secret_value(),
            )
        ),
        [m for m in load_manifest(settings.manuals_dir / "manifest.yaml") if m.reviewed],
        kb_version=kb_version,
        reranker=reranker,
        config=RetrieverConfig(tau=0.0, tau_without_rerank=0.0),  # measure ranking only
    )
    concurrency = 1 if args.rerank else args.concurrency

    cases = load_cases()
    if args.split != "all":
        cases = [c for c in cases if c.split == args.split]
    if args.limit:
        step = max(1, len(cases) // args.limit)  # deterministic spread across categories
        cases = cases[::step][: args.limit]
    conditions = args.conditions.split(",")
    started = time.monotonic()

    report: dict = {
        "kb_version": kb_version,
        "created_at": datetime.now(UTC).isoformat(),
        "split": args.split,
        "cases": len(cases),
        "rerank": reranker is not None and (args.rerank_model or registry.rerank.model),
        "conditions": {},
    }
    all_results: dict[str, list[CaseResult]] = {}
    for condition in conditions:
        results = await run_cases(retriever, cases, condition, CONDITIONS[condition], concurrency)
        all_results[condition] = results
        report["conditions"][condition] = {
            "summary": summarize(results).model_dump(),
            "by_category": {k: v.model_dump() for k, v in by_category(results).items()},
        }
        print(condition, summarize(results).model_dump())

    if "category" in all_results and LABELS_PATH.exists():
        labels = json.loads(LABELS_PATH.read_text())["labels"]
        relevant = {lab["case_id"]: set(lab["relevant_pages"]) for lab in labels}
        report["chunk_level"] = {
            "labels": "LLM-assisted (judge model), spot-checked; see retrieval/labels.py",
            **chunk_recall_at_5(all_results["category"], relevant),
        }
        print("chunk-level", report["chunk_level"])

    if args.calibrate:
        dev = [c for c in cases if c.split == "dev"]
        base = {r.case_id: r for r in all_results.get("category", [])}
        positives = [
            base[c.case_id].top_score or 0.0
            for c in dev
            if c.case_id in base and (base[c.case_id].rank or 99) <= 5
        ]
        wrong = await run_cases(
            retriever,
            dev,
            "wrong_category",
            lambda c: RetrievalQuery(query_en=c.query, category=wrong_category(c.category)),
            concurrency,
        )
        off_topic = [
            (await retriever.search(RetrievalQuery(query_en=q))).top_score or 0.0 for q in OFF_TOPIC
        ]
        negatives = [r.top_score or 0.0 for r in wrong] + off_topic
        report["calibration"] = {
            "score": "rerank relevance" if reranker else "dense cosine similarity",
            "positives": len(positives),
            "negatives": len(negatives),
            "best": best_threshold(positives, negatives),
            "positive_mean": round(sum(positives) / max(1, len(positives)), 4),
            "negative_mean": round(sum(negatives) / max(1, len(negatives)), 4),
        }
        print("calibration", report["calibration"])

    report["rerank_calls"] = reranker.calls if reranker else 0
    report["elapsed_s"] = round(time.monotonic() - started, 1)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    label = "rerank" if reranker else "norerank"
    path = REPORTS_DIR / f"retrieval_{kb_version}_{args.split}_{label}_{stamp}.json"
    path.write_text(json.dumps(report, indent=1))
    print(f"report: {path}")
    await backend.close()
    await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all")
    parser.add_argument("--conditions", default="category,brand_category,none")
    parser.add_argument("--limit", type=int, default=0, help="evenly sample this many cases")
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--rerank-model", default=None)
    parser.add_argument("--rerank-per-min", type=float, default=9.0)
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--concurrency", type=int, default=8)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
