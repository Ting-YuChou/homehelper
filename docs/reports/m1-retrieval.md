# M1 retrieval evaluation

- **KB:** `kb_20261021_03` holds 94 manuals and 12,785 chunks. It was built with the LlamaParse `cost_effective` tier, page-aware chunking, and `text-embedding-3-small`.
- **Date:** 2026-10-21
- **Spec:** §10.4, §16.2

To reproduce, run `uv run python -m homehelper_evals.retrieval.run --calibrate`. Add `--rerank` to include the reranker. JSON reports go to `evals/reports/`.

## Setup

- **Cases:** 976 (scenario, manual) pairs from `data/scenarios/home_helper_dataset.jsonl`, split into 194 dev and 782 test. The split groups cases by scenario text (`data/scenarios/splits.json`).
- **Query:** the scenario text.
- **Label:** the manual the scenario was written from. v1 file names map to manifest `doc_id`s through `aliases`.
- **Filter conditions:**
  - **category:** the agent knows the appliance type.
  - **brand + category:** the user also names the brand. Brands come from the manifest, so v1 label mistakes such as the "LG" fridge that is really a Samsung don't leak in.
  - **none:** no filter.
- **Model-number filtering is not evaluated.** It would trivially select the right manual.
- **Metrics:** manual-level Recall@5, Hit@1, and MRR@5. A hit means a top-5 chunk comes from the labelled manual. Recall runs use τ = 0, so only ranking is measured.

## Results without rerank (all 976 cases)

| Condition | Recall@5 | Hit@1 | MRR@5 |
|---|---|---|---|
| category | 0.808 | 0.421 | 0.564 |
| brand + category | **0.953** | 0.637 | 0.760 |
| none | 0.688 | 0.362 | 0.480 |

Per-category Recall@5 with the category filter ranges from 0.73 (microwave: 10 Samsung, LG, and Panasonic manuals with near-identical content) to 0.90 (water purifier).

**Chunk-level Recall@5:** 0.648, with the category filter on 91 test cases. The relevance labels were LLM-assisted. For 100 test cases, Sonnet marked which chunks of the correct manual contain the reference solution, and the labels were stored as (doc_id, page) pairs. 10 were spot-checked by hand, and roughly 8–9 of 10 looked right. Treat this number as approximate.

## Rerank (Cohere `rerank-v5.0-fast`, same 100 dev cases, category filter)

| | Recall@5 | Hit@1 | MRR@5 |
|---|---|---|---|
| Hybrid (dense + full-text, RRF) | 0.79 | 0.38 | 0.529 |
| + rerank | **0.90** | **0.41** | **0.590** |

Only 100 cases were reranked because the current Cohere key is a trial key (10 calls/min, 1,000/month). Rerun on the full test split once the key is upgraded.

## Sufficiency threshold τ (spec §10.4 ④)

τ is calibrated on dev.
- **Positives:** cases whose correct manual is in the top 5.
- **Negatives:** the same queries searched under a wrong category, plus 20 off-topic questions.
- **Choice:** the F1-optimal threshold.

| Score | τ | F1 | Precision | Recall | Positive / negative mean |
|---|---|---|---|---|---|
| Dense cosine similarity (rerank unavailable) | **0.50** | 0.84 (all dev) | 0.91 | 0.78 | 0.57 / 0.37 |
| Rerank relevance | **0.58** | 0.96 (100 dev) | 0.92 | 1.00 | 0.80 / 0.17 |

These are the defaults in `RetrieverConfig` (`tau`, `tau_without_rerank`). Rerank separates "the manual covers this" from "it doesn't" far more cleanly, which is what the web fallback decision depends on.

## Takeaways

- Knowing the brand matters most (Recall@5 0.81 → 0.95), so the agent should ask for or infer the brand early. The model number narrows things further, because the filter cascade starts at the matching manual.
- Rerank is worth keeping. Without it, sufficiency is noticeably less reliable.
- Next levers, if needed:
  - Merge very small chunks. The median is about 100 tokens.
  - Use NLU's rewritten `search_query_en` instead of the raw scenario text.
  - Add a per-category look at microwaves.

## Known limitations

- Scenario queries were generated from the manuals themselves, so they are easier than real user messages.
- Model-number retrieval, error-code boosting, and the web fallback are covered by unit and integration tests and a live smoke test, not by this benchmark.
- Retrieval eval runs locally. The PDFs and parsed text are not in CI, so wiring it into CI waits for the hosted KB in M8.
