# ADR-012: Keep the manual the model number identified

- **Status:** Accepted
- **Date:** 2026-10-24
- **Spec:** §10.4

## Context

The retriever tries filter levels in order: model number → brand + category → category → all
(spec §10.4). The first level whose best rerank score reaches τ (0.58) wins. If none reaches
it, the best-scoring level is returned, or the web fallback.

A model number names exactly one manual: the user's. When that manual is worded differently
from the user's description, its best chunk can score below τ, though it is still the right
manual. The retriever then relaxed to brand + category. There, another model's manual could
score higher, and its steps reached the plan, sometimes with that model's buttons, menu names
or part locations.

Replaying the failed trials of journey-go-v5 (`full`, 100 cases × 4, users who gave the model)
offline showed how much this cost:
- With relaxing, the step the simulated user needs to resolve the problem was retrieved in
  35.7% of the failed trials. Keeping the model's manual raised that to 78.6%.
- Over all trials, the share went from 71.8% to 87.2%.
- Two alternatives did worse: merging both levels (82.1%) and retrieving more chunks (k = 8,
  74.4%).

## Decision

The model level is sufficient whenever it finds any chunks. Once the model number has picked
the user's manual, the search no longer relaxes past it, and the web fallback no longer
replaces it. A model number that matches no manual, or whose manual returns no chunks, still
relaxes as before.

## Consequences

- **Retrieval eval:** the new `model` condition searches at the production τ, with the model
  number a user would give. The 80 labelled test cases whose manual has model patterns:

  | | Relaxing (before) | Keeping the manual |
  |---|---|---|
  | Searches that relaxed | 7 (3 to brand + category, 4 to category) | 0 |
  | Chunk-level Recall@5 | 0.888 | 0.950 |
  | Retrieved chunks from the user's manual | 92.3% | 99.5% |

  Command: `python -m homehelper_evals.retrieval.run --split test --rerank --labelled
  --conditions model`.
- **Weak results:** a weak match in the user's own manual now goes to the planner. The planner
  already returns no items when the excerpts don't address the problem, which leads to
  `plan_unavailable` and a handoff. Before, a relaxed search would have put another model's
  steps in front of the user.
- **No web fallback for these searches.** It never helped here anyway: web findings replaced
  the chunks, and the planner can't use findings (`plan_unavailable`).
- **Baseline unaffected.** The baseline never filters by model, so its numbers don't change.

## Alternatives considered

- **A lower τ for the model level.** This only moves the cut-off. However low it is, a worse
  match in the user's manual still gets swapped for a better-scoring match in another
  model's manual, which is the wrong answer.
- **Merging the model level with brand + category.** This kept other models' chunks beside the
  user's (82.1% in the replay), and the planner had no way to tell which model each came from.
