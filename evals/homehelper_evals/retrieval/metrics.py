from collections import defaultdict
from collections.abc import Sequence

from pydantic import BaseModel


class CaseResult(BaseModel):
    case_id: str
    condition: str
    doc_id: str
    category: str
    retrieved_doc_ids: list[str]  # doc_id of each returned chunk, best first
    retrieved_spans: list[tuple[str, int, int]] = []  # (doc_id, page_start, page_end) per chunk
    filter_level: str | None
    top_score: float | None
    sufficient: bool

    @property
    def rank(self) -> int | None:
        """1-based rank of the first chunk from the correct manual."""
        for i, doc_id in enumerate(self.retrieved_doc_ids, start=1):
            if doc_id == self.doc_id:
                return i
        return None


class Summary(BaseModel):
    n: int
    recall_at_5: float
    hit_at_1: float
    mrr_at_5: float
    sufficient_rate: float


def summarize(results: Sequence[CaseResult]) -> Summary:
    n = len(results)
    if n == 0:
        return Summary(n=0, recall_at_5=0, hit_at_1=0, mrr_at_5=0, sufficient_rate=0)
    ranks = [r.rank for r in results]
    return Summary(
        n=n,
        recall_at_5=round(sum(rank is not None and rank <= 5 for rank in ranks) / n, 4),
        hit_at_1=round(sum(rank == 1 for rank in ranks) / n, 4),
        mrr_at_5=round(sum(1 / rank for rank in ranks if rank and rank <= 5) / n, 4),
        sufficient_rate=round(sum(r.sufficient for r in results) / n, 4),
    )


def by_category(results: Sequence[CaseResult]) -> dict[str, Summary]:
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        groups[r.category].append(r)
    return {category: summarize(group) for category, group in sorted(groups.items())}


def chunk_recall_at_5(
    results: Sequence[CaseResult], relevant_pages: dict[str, set[int]]
) -> dict[str, float | int]:
    """Share of labelled cases whose top 5 includes a chunk on a relevant page of the right
    manual. Cases whose label has no relevant pages are skipped."""
    labelled = [r for r in results if relevant_pages.get(r.case_id)]
    hits = sum(
        any(
            doc_id == r.doc_id and any(start <= p <= end for p in relevant_pages[r.case_id])
            for doc_id, start, end in r.retrieved_spans[:5]
        )
        for r in labelled
    )
    return {"n": len(labelled), "recall_at_5": round(hits / max(1, len(labelled)), 4)}


def best_threshold(positives: Sequence[float], negatives: Sequence[float]) -> dict[str, float]:
    """Threshold on a score that best separates positives (should be sufficient) from negatives,
    by F1 on the positive class; ties go to the higher threshold (fewer false positives)."""
    best = {"tau": 0.0, "f1": 0.0, "precision": 0.0, "recall": 0.0}
    for tau in sorted({round(s, 4) for s in [*positives, *negatives]}):
        tp = sum(s >= tau for s in positives)
        fp = sum(s >= tau for s in negatives)
        fn = len(positives) - tp
        if tp == 0:
            continue
        precision, recall = tp / (tp + fp), tp / (tp + fn)
        f1 = 2 * precision * recall / (precision + recall)
        if f1 >= best["f1"]:
            best = {
                "tau": tau,
                "f1": round(f1, 4),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
            }
    return best
