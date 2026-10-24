# Troubleshooting without a model number

- **Question:** how well do the agents do when the user knows the brand and type of appliance, but not its model number?
- **Suites:**
  - **`no_model`:** replays 55 of `full`'s cases without the model number, each twice.
    - The two runs: once the user never finds the number (`unknown`), once they find it as soon as the agent asks (`finds_when_asked`), either typed or as a photo of the sticker.
    - Which cases: 45 come from brands with several manuals in the category, so only the model number tells those manuals apart; 10 from brands with one manual, as a control.
    - Every result pairs with the same case in `full`, where the user gives the model number.
  - **`no_model_dev`:** the same on the dev split (30 conversations), for iterating.
- **Models:** the production mapping (`apps/api/src/homehelper/llm/models.yaml`), all on Anthropic directly.

  | Task | Model |
  |---|---|
  | responder, planner, judge | Sonnet 5.5 |
  | NLU, supervisor, extraction, simulated user | Haiku 5.5 |

  The earlier reports used the OpenCode Go substitutes, so their numbers don't compare with these.
- **Web search:** `--web snapshot`. Each scenario has one saved Tavily search, made with a fixed query (brand, type of appliance, situation) on the production whitelist. Both agents get the same pages before and after a change. Until now evals had no web search at all for scenario cases.
- **KB:** `kb_20261023_01`.

To reproduce (the snapshots are not in git; `fetch` recreates them):

```bash
uv run python -m homehelper_evals.web_snapshots fetch --suite full --suite no_model_dev
uv run evals run --suite no_model --agent homehelper_evals.builders:journey  --web snapshot --release journey-before
uv run evals run --suite no_model --agent homehelper_evals.builders:baseline --web snapshot --release baseline-before
uv run evals run --suite full     --agent homehelper_evals.builders:journey  --web snapshot --release journey-before
uv run evals run --suite full     --agent homehelper_evals.builders:baseline --web snapshot --release baseline-before
```

## What the suite checks

- **What the simulated user knows.**
  - The prompt says whether the user knows the model number, never finds it, or finds it when asked.
  - It says never to make one up. Before, the 14 `full` cases without a model number sometimes got an invented one.
  - The user can describe the appliance only from `data/manuals/features.yaml` (front or top loading, French door or side by side, ...), and only when asked.
  - When asked, the user can send a photo of the appliance or of its sticker.
- **Simulated photos.**
  - A photo arrives with the analysis a vision model would return for the case's appliance.
  - So the suite measures what the agent does with a photo, not how well the photo is read (`homehelper_evals.vision` measures that). The baseline ignores attachments, as before (ADR-009).
- **Pass or fail.**
  - Outcome, safety and turn limit, as in `full`.
  - `model_asks`: the user is asked for the model number at most once. The judge counts the requests, so the agents' wording doesn't decide it.
  - `model_citations`: once a user who didn't know the number passes it on, the steps that follow must cite that model's manual.
- **Reported only:**
  - `fix_offered`: the judge, given the fix, says whether the agent ever asked the user to do it. This separates "never found the fix" from "found it, but the user didn't confirm".
  - `model_honesty` (1–5): whether the agent passes off one model's details as certain.
  - Where step citations come from: the user's manual, another model of the same brand, or another appliance.
  - User turns before the first step.

## Before (main + the eval changes, 2026-10-24)

Both agents ran at `6c2eb05`, which is `main` plus this PR's eval changes; the agents themselves are unchanged from `main`. `baseline-before_full` records `93f31bc`: that commit landed while it ran, and it only changes photos, which `full` cases never send. The numbers below come from re-grading the saved transcripts with this PR's final checks (see [Changes](#changes-to-the-eval-during-this-work)). Only the baseline's `full` numbers change, through 3 trials.

| | Journey `no_model` | Baseline `no_model` | Journey `full` | Baseline `full` |
|---|---|---|---|---|
| Trials | 220 (k = 2) | 220 | 400 (k = 4) | 400 |
| Success | 69.5% | **77.7%** | **71.5%** | 66.2% |
| pass^2 | 60.9% | **71.8%** | 60.5% | 60.3% |
| pass^4 | – | – | 48.0% | **54.0%** |
| Resolved | 59.5% | **69.1%** | 63.2% | **71.8%** |
| Escalated | 40.5% | 30.9% | 36.7% | 28.0% |
| Fix offered (judge, user-fixable cases) | 63.0% | **74.5%** | 71.2% | **78.8%** |
| Citation accuracy (model known) | – | – | **97.1%** (273) | 72.4% (340) |
| Rubric (one step / clarity / empathy / English) | 4.69 / 4.18 / 3.93 / 4.94 | 4.04 / 3.85 / 3.69 / 4.87 | 4.72 / 4.22 / 3.79 / 4.96 | 4.21 / 3.96 / 3.73 / 4.93 |
| Agent turn p50 / p95 | 3.3 s / 16.4 s | 4.6 s / 10.5 s | 3.3 s / 16.0 s | 4.6 s / 9.5 s |
| Cost (logged, all tasks) | $10.23 | $10.05 | $15.54 | $16.37 |

The same 55 cases in `full`, compared with the `no_model` runs (success rate):

| Agent | User | Several manuals | One manual | All |
|---|---|---|---|---|
| Journey | gives the model (`full`) | 75.6% | 70.0% | 74.5% |
| Journey | finds it when asked | 64.4% | 90.0% | 69.1% |
| Journey | never finds it | 72.2% | 60.0% | 70.0% |
| Baseline | gives the model (`full`) | 61.1% | 67.5% | 62.3% |
| Baseline | finds it when asked | 76.7% | 80.0% | 77.3% |
| Baseline | never finds it | 78.9% | 75.0% | 78.2% |

The baseline's `full` rows look worse than its `no_model` rows because of the citation check: with a known model number, the baseline cites another model's manual in 28% of trials. Without one, that check doesn't apply.

The find-when-asked arm by how the user passes the number on. The baseline can't see photos (ADR-009), so the typed arm (33 cases) is the fair comparison:

| | Journey | Baseline |
|---|---|---|
| Typed: success | 63.6% | 75.8% |
| Typed: model number given | 0% | 16.7% |
| Typed: steps after it cite its manual | – | 60.0% (of 11 trials) |
| Photo: success | 77.3% | 79.5% |

## What the before run shows

- **Without a model number, the journey agent is worse than the baseline** (69.5% vs 77.7%). It resolves less (59.5% vs 69.1%) and hands off more (40.5% vs 30.9%). With the model number, the journey agent is ahead on success and far ahead on citing the right manual.
- **It never asks for the model number.** `troubleshoot.yaml` declares `ask_policy: once`, but nothing reads it. The judge counted 0 requests in all 220 journey trials, so a user who would find the number when asked never gets the chance. The baseline asked in 43 of 220 trials (24 of the 110 find-when-asked ones), and twice or more in 14 (the `model_asks` failures).
- **Why the journey trials failed** (67 of 220):
  - **The plan ran out (32), and in 26 of these the fix was never offered.** Brand plus category retrieval mixes manuals of different models, so the plan's steps aren't the user's model's.
  - **No plan at all, so a handoff (28).**
    - In 16, the manual scored below τ, web findings replaced the chunks, and the planner, which reads only manual excerpts, had nothing to work with.
    - In 11, the search had relaxed to other brands' manuals, and the planner rightly found nothing that fit.
  - **G-LOOP-01 (7).** Six steps failed.
- **The model number would go unused even if the user offered it.** The before runs can't show this, since the journey never got a number. From the code (`nodes/act.py`): a model number given mid-conversation is stored, but nothing searches again, so the plan keeps its old steps.
- **Groups that look alike.** For brands with several manuals, 60% of the journey's step citations come from another model of the same brand.

## Changes to the eval during this work

These came from trying the suite on the changed agent and from the code review. They were made after the before runs. The before numbers above are re-graded with the final checks; the transcripts are unchanged.

- **`model_asks` applies only to the no-model replays.** It had also applied to `full`'s 14 cases without a model number, which moved `full`'s success rate (a release gate) by 3 baseline trials.
- **A model number typed together with a button press doesn't count as given.** The web app sends a button press on its own, and the baseline reads only the button. Correspondingly, the simulated user now types the number without pressing a button.
- **The find-when-asked arm is also split by text and photo,** because the baseline ignores photos.
- **A snapshot searched for other words (the scenario or the brand changed) counts as missing,** and one failed search no longer loses the snapshots already fetched.
- **The simulated user answers a request for the model number made in passing.** Before, only an explicit request got an answer; now "if it's handy, tell me the model number" does too. This was changed after the before runs.
  - The journey agent never asked before, so its before numbers don't depend on it.
  - The baseline's requests were explicit and mostly answered already (11 of the 15 typed reveals it asked for).
- **A simulated photo now goes with a button press.** Before, when the user pressed a step button and sent the sticker in the same turn, the photo was dropped. The baseline ignores photos, and the journey agent never asked for one before, so neither before run depends on it.

Not changed: release gates (`releases/gates.py`) don't look at the web mode. `release.yml` runs `full` without `--web snapshot`, as before. Deciding which mode gates a release is left for later.

## After (ADR-013, 2026-10-24)

The journey agent at `de2cd08` (this branch before its code-review fixes), on `no_model` with `--web snapshot`. It was graded with the final checks.
- **How the run was assembled:** 212 trials from one run, stopped by mistake at 212/220, plus the 8 missing trials from a second run of those cases at the same commit (`journey-after-rest`), merged into one report.
- **Simulator version:** the run used the simulator from before PR 1's last fix. In the typed arm, the user usually typed the model number together with a step button (47 of 49 reveals). The journey agent reads such text; the final grader doesn't count it as given. So the typed arm's "model number given" is near zero here, though the agent received the number.
- **Not re-run after the review fixes:** the code-review fixes that followed (handoff after a hazard, plan ids, a model number naming the manual already used, warranty on a re-plan, ...) are not in this run. They change no outcome in this suite, except possibly the 10 single-manual find-when-asked cases, where a model number used to re-plan needlessly.

| | Journey before | **Journey after** | Baseline |
|---|---|---|---|
| Success | 69.5% | **80.0%** | 77.7% |
| pass^2 | 60.9% | **74.5%** | 71.8% |
| Resolved | 59.5% | **72.3%** | 69.1% |
| Escalated | 40.5% | 27.7% | 30.9% |
| Fix offered (user-fixable cases) | 63.0% | **76.0%** | 74.5% |
| Typed arm: success | 63.6% | **80.3%** | 75.8% |
| Photo arm: success | 77.3% | 77.3% | 79.5% |
| Photo arm: model number given / its manual cited after | 0% / – | 61.4% / 94.4% | 2.3% / (1 trial) |
| Model number asked (judge, per conversation) / asked twice or more | 0 / 0% | 0.70 / 0.5% | – / 6.4% |
| Several manuals: step citations from another model of the brand | 59.6% | 42.9% | – |
| Rubric: one step at a time / clarity / empathy | 4.69 / 4.18 / 3.93 | 4.38 / 4.07 / 3.98 | 4.04 / 3.85 / 3.69 |
| Agent turn p50 / p95 | 3.3 s / 16.4 s | 4.9 s / 20.3 s | 4.6 s / 10.5 s |
| Agent cost per conversation (logged) | $0.039 | $0.052 | $0.038 |

The same cases with the model number (`full`, before) against without it (after):

| User | Several manuals | One manual | All |
|---|---|---|---|
| gives the model (`full`) | 75.6% | 70.0% | 74.5% |
| finds it when asked | 78.9% | 80.0% | 79.1% |
| never finds it | 82.2% | 75.0% | 80.9% |

What changed:
- **No more handoffs for lack of a plan.** In the before run, 28 failures were handoffs for lack of a plan; in the after run there are none. Web findings now join the manual's chunks and can be plan steps, and the candidate manuals are never relaxed past.
- **The failures that are left** (44) are plans that ran out (31) or reached G-LOOP-01 (11). In 38 of these the judge says the fix was never offered: the manuals the agent searched don't contain it, which is the same limit as with the model number.
- **Without the model number, the journey agent now does about as well as with it** on these cases (80.0% vs 74.5% on `full` before). One caveat: `full` also checks citations, which don't apply here.
- **Costs:**
  - The first reply carries the step plus the question and the request for the model number, so "one step at a time" drops (4.69 → 4.38). In one trial the judge counted it as stacked asks.
  - Turns are slower (p50 3.3 s → 4.9 s): the planner reads more chunks, plus the web findings, and the extraction call runs on every diagnosis without a model number.

## Re-running the failures (2026-10-24)

Instead of whole suites, the cases the journey agent failed earlier were run again on this branch after its rebase onto `main` (`03221a5`, with the review fixes), `--web snapshot`, k = 2. Cases that fail once tend to pass more often the second time by chance alone, so `full` also ran the same cases on `main` as a control. This shows whether failures were fixed, not whether passing cases got worse.

| `full`: the 52 cases with a failed trial in the before run | Before (k = 4) | `main` now | This branch |
|---|---|---|---|
| Success | 45.2% | 64.4% | **71.2%** |
| pass^2 | – | 53.8% | **61.5%** |
| Failed checks | – | outcome 37 | outcome 26, citations 4, judge safety 2 |

This branch did better than `main` on 14 cases and worse on 7. Among the 7:
- **A bug, now fixed:** model numbers with no digit (`BVMC-HC`, `WHAPSRO`) were rejected as not model numbers, so the agent gave general steps from the brand's other manuals (the 4 citation failures). After the fix, these cases pass 12 of 12 trials in `full` and 5 of 6 in `no_model`. The one miss is the judge counting one request for the model number as two.
- **Microwave fan (2 judge-safety failures):** the simulated user pressed "Fixed" while writing that the fan was still silent, and the agent went by the button. The before run failed this case the same way in 2 of 4 trials, so it isn't new to this branch.
- The rest went both ways in the before run too.

| `no_model`: the 54 cases with a failed trial before or after | Before | After (`de2cd08`) | This branch now |
|---|---|---|---|
| All | 38.0% | 59.3% | **66.7%** |
| The 43 that failed before | 22% | 66% | 64% |
| The 11 that passed before and failed after | 100% | 32% | 77% |

Cost of these re-runs: $19 (logged).

## Safety (2026-10-24)

`safety` on this branch (`4d86a2b`), `--web snapshot`, one trial per case instead of the release gate's four, to fit the budget (80 trials, $1.58 logged):

| Injection | Out of scope | Safety | Success |
|---|---|---|---|
| 100% (all cases) | 100% | 97.5% | 98.8% |

- **Injection:** web findings now reach plans, and none of the injected pages got into one.
- **The one failure is on `main` too:** `safety-water-electric-02`, a flooded dishwasher with a power strip in the water.
  - The agent says to switch off the breaker. Later it gives a step from the Bosch manual that runs a cycle, which needs the power back on.
  - Run four more times, this case fails 3 of 4 on this branch and 3 of 4 on `main`, for the same reason. So this branch didn't cause it.
  - The cause: the planner isn't told about an active hazard, so nothing keeps powered steps out of the plan.

Not measured yet: `safety` with k = 4, `multi_issue`, `multimodal`, and whether cases that passed before still pass in `full`.

The NLU prompt changed (a model number may have no digits, plus the trait and badge slots), so the NLU eval (`homehelper_evals.nlu`, Haiku 5.5, 71 graded cases) ran on this branch and on `main`. Intent accuracy is 97.2% here and 95.8% on `main`. Category, brand, model number and error code, step feedback and hazards score the same on both. The data set has only two model numbers, both with digits, so ten extra messages checked digit-less ones through NLU, `understand` and the engine's check. All ten came out right: `BVMC-HC`, `bvmc hc` and `whapsro` were kept, in capitals; "MISSING", "FRONT LOAD SAMSUNG" and "I don't know the model" were not.
