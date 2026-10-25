# ADR-013: Troubleshooting without a model number

- **Status:** Accepted
- **Date:** 2026-10-24
- **Spec:** §7.2, §7.4, §7.6, §10.4, §10.6, §11.2, §16.3
- **Builds on:** [ADR-012](012-keep-the-model-numbers-manual.md)

## Context

Users often don't know their appliance's model number. Up to now the agent never asked for it.
`troubleshoot.yaml` declared `ask_policy: once`, but nothing read it. The agent searched by
brand and category, and the eval's simulated users nearly always gave the model, so the scores
didn't show the gap.

A new eval suite, `no_model`, replays 55 of `full`'s cases without the model number. Each case
runs twice: once the user never finds the number, once they find it when asked. Its first run
showed what goes wrong:

- **One brand, several manuals.** 19 of the 51 brand-and-category groups have more than one
  manual (62 of the 94 manuals). Brand plus category can't tell them apart, so a plan mixes
  steps from different models, presented as if they were the user's.
- **No plan, so a handoff.** When the manual's score fell below τ, web findings replaced the
  chunks. The planner reads only chunks, so it returned `plan_unavailable`, and the agent
  handed off. This happened in 23 of 220 no-model trials.
- **A model number given mid-conversation changed nothing.** It was stored, but the plan kept
  the old steps.
- **"I don't know" could be stored as the model number,** because NLU text was taken as is.

## Decision

1. **The brand's manuals, told apart by what the user sees.**
   - `data/manuals/features.yaml` lists, per category:
     - where the model sticker usually is;
     - the visible traits that tell the brand's manuals apart (front or top loading, French
       door or side by side, Convection buttons or not, ...).
   - It also gives each manual's values, only where the manual states them. Not stated means
     unknown, not no.
   - `knowledge.features.ManualIndex` computes the candidate manuals and narrows them. A trait
     that would rule out every candidate is ignored: the user may be wrong, but the manuals
     can't all be.
2. **How identification maps to a search.** `act` computes it with pure functions
   (`engine/identify.py`) and stores it as the issue's `plan_basis`:
   - **`model`:** the model number's manual (ADR-012).
   - **`identified`:** one manual left, either after narrowing or because the brand has only
     one.
   - **`generic`:** several manuals left. The search is limited to them, takes at most 2 chunks
     from each, and always adds web findings. The planner is told to prefer steps several
     manuals share and to avoid one model's details. Every step is labeled `general`, and the
     step card shows "General step".
   - **Pinning:** the `candidates` filter level never relaxes past these manuals, the same rule
     as the model level.
3. **One request for the model number.**
   - **Where:** the first reply of a general plan, or a handoff for having no plan.
   - **What:** a fixed sentence appended after the responder's message: where the sticker
     usually is, and that a photo works too. When a trait tells the candidates apart, its
     question comes first ("Does it load from the front or the top?"). If the user gave a
     model number the library lacks, it asks only that question. The responder is told not to
     ask itself.
   - **Never after a hazard,** so it can't send the user behind a leaking or smoking
     appliance.
   - **Once:** `model_asked` records it per appliance category for the whole conversation.
     A reply the supervisor blocked doesn't count as asked.
   - **No waiting:** the agent doesn't wait for an answer. The first general step is already
     there.
4. **A better identification midway re-runs `diagnose`.**
   - In `guide`, the predicate `identification_changed` compares the slots with `plan_basis`.
     It is pure, so the engine still reads only state.
   - **What triggers it:** a model number (typed, or from a photo at ≥ 0.7 confidence), a trait,
     a badge, or a brand given or corrected (the brand is part of `plan_basis`).
   - **What re-runs:** the warranty check, the search and the plan. The warranty check keeps
     G-WARR-01 warnings on the new plan. If the new details point to the same manuals, nothing
     re-runs. "The same manuals" includes a model number that names the one manual already
     used. The plan stays, and the reply says why.
   - **A model number with no manual in the library:** it is said once, on the turn it is
     given.
   - **`merge_plan`:**
     - Steps already tried stay first, with their results. They keep counting toward G-LOOP-01,
       so the cap can't be reset by giving a model number.
     - The planner sees the tried steps, so it doesn't repeat them.
     - The rest of the plan is replaced, including a step that was shown but not answered.
     - New items are numbered after the highest id the plan used, so a card never shows a
       reused id. (The web app keys step progress by id.)
     - An empty new plan keeps the current one.
   - **Back from a handoff:** a handoff that came only from `plan_unavailable` may go back to
     `diagnose` the same way. These keep the handoff:
     - any hazard in the conversation;
     - failed steps;
     - a request for a technician.

     A guardrail that holds at the step it would enter (a hazard or a technician request while
     already at the handoff) is recorded too, so that the reason for the handoff stays current.
   - **The last step failing:** when the last step fails in the same turn as a new detail,
     `diagnose` hands off with `plan_exhausted`.
5. **Where the details come from.**
   - **Typed text:** NLU fills `trait_<name>` and `badge` slots. `understand` drops values the
     category doesn't have.
   - **Text typed together with a step button:** it is read for the model number, traits and
     badge only, not the brand, which may be about another appliance. The button decides the
     step's result, and an NLU failure keeps the button press.
   - **Photos:** the vision model reports `features`, `badges` and their own
     `features_confidence`. The existing confidence is about the nameplate, and a clear photo
     of the front shows no nameplate. Below 0.7, traits from a photo are not used.
   - **`looks_like_model()`:** a value needs at least three letters or digits, one of them a
     digit, and no phrase like "don't know", before it becomes the model number.
6. **Web findings can be plan steps.**
   - **Search modes:** `RetrievalQuery.web` decides what findings do. `replace` is the
     baseline's existing behaviour. `add_when_insufficient` and `always_add` keep the
     manual's chunks.
   - **What the planner sees:** findings get stable ids (`web-<hash>`), so the planner can cite
     them.
   - **Rules for a step only a web page supports:**
     - its risk is at least medium (§10.6 ③, which code didn't enforce before);
     - a step that opens the appliance is dropped;
     - the responder says the step comes from an unofficial page.
   - **Showing the source:** step cards carry `web_sources` (domain, title, URL), and the UI
     labels them "Unofficial source". Only http(s) URLs pass the whitelist. `Citation` is unchanged, so stored messages, graders and
     the manual chip keep working.
   - **Checking the reply:** the supervisor's grounding check now sees the findings too.
7. **Videos while the model is unknown.** `diagnose` runs `tutorials.search_videos`, using the
   existing `_video_args`, only for a `generic` basis. It shows one card, presented as a general
   video.

## Consequences

- **Baseline unchanged.** The baseline keeps `web="replace"` and never gets candidates, so its
  numbers don't depend on this change.
- **The appearance results are an upper bound.** The simulated user describes the appliance
  from the same `features.yaml` the agent narrows with, so a labelling error can't show up as a
  failure.
- **Photos in the eval are simulated.** Their analysis is computed from the case. Whether the
  vision model reads traits correctly from a real photo isn't measured; there are no licensed
  exterior photos yet.
- **Web results in the eval are a snapshot,** one search per case with a fixed query, so runs
  are reproducible. The agent's better web query (brand, appearance, symptom) therefore has no
  effect in the eval.
- **Some groups can't be told apart** (Samsung's five microwaves, LG's five front-load
  washers). They only ever get general steps.
- **Data to maintain.** Each new manual in a brand that already has one needs `features.yaml`
  values, reviewed like model patterns.
- **New state, carried by paused issues:** `PlanBasis`, `PlanItem.general`,
  `AgentState.model_asked`.
- **Contracts:** additive fields on `StepCard`, `WebFinding`, `RetrievalQuery` and
  `VisionResult`. The OpenAPI schema is regenerated.

## Alternatives considered

- **Ask the distinguishing question before the first step.** Rejected: the user asked to start
  troubleshooting right away. The question goes with the first general step, and the answer
  re-runs `diagnose`.
- **Drop steps the planner marks as fitting only one model.** Rejected: it can empty the plan,
  which turns into a handoff. Instead every step is labeled general, and the planner is told to
  prefer shared steps.
- **Store traits in the manifest.** Rejected: the manifest hash identifies a KB snapshot.
  Traits aren't chunk metadata, so they live in their own file, and adding one needs no
  re-ingest.
- **A confirm step for a model number read from a blurry photo.** Rejected: sending `guide` back
  to a confirm step would close the issue instead of pausing it (ADR-007). Below 0.7 the number
  is simply not used, and the agent keeps going.
