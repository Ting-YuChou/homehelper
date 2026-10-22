# M5-07/08: agent tools — evaluation report

- **Suite:** `tools` (`evals/datasets/tools.yaml`, 8 cases × k=4 = 32 trials), strict judge.
- **Agent:** `homehelper_evals.builders:journey`. Each trial gets its own mock-mode MCP servers and a fixed clock.
- **Models:** `evals/models/opencode-go.yaml`, the same mapping as the M2-06 and M3 runs.
  - Responder and planner: DeepSeek v4.1 flash. The responder keeps DeepSeek's default thinking mode; the planner has thinking off (`reasoning_effort: none`).
  - NLU, supervisor and user simulator: Haiku 5.5. Judge: MiniMax M3.
- **Knowledge base:** `kb_20261022_01`, the newest ready version; `KB_VERSION` is not pinned.
- **Code:** the runs used a local branch (`eval/m5-tools`, not pushed) that merges this branch with the local, unpushed `eval-dataset-fixes` branch (scenario dataset and manifest review). Those fixes change scenario-derived cases. They do not change `tools.yaml`, which is hand-written. The reports' `git_sha` values are merge commits on that local branch.

## Results

| Run | Code | Pass rate (pass^1) | pass^4 | Agent turn p50 / p95 |
|---|---|---|---|---|
| v1 | first real-model run, after the LiteLLM/MCP fix | 53.1% | 50.0% | 21.2 s / 46.9 s |
| v2 | review fixes, technician routing, simulator rule | 75.0% | 75.0% | 18.4 s / 66.2 s |
| v3 | third-review fixes, NLU tie-break, supervisor wording | 87.5% | 87.5% | 24.6 s / 244.5 s |
| v4 | final (this branch) | **87.5%** | **87.5%** | 21.2 s / 40.2 s |

| Case | v1 | v2 | v3 | v4 |
|---|---|---|---|---|
| prefill-history | 4/4 | 4/4 | 4/4 | 4/4 |
| warranty-question | 4/4 | 4/4 | 4/4 | 4/4 |
| list-appliances | 4/4 | 4/4 | 4/4 | 4/4 |
| book-technician | 1/4 | 4/4 | 4/4 | 4/4 |
| guest-no-booking | 0/4 | 4/4 | 4/4 | 4/4 |
| parts-vacuum | 0/4 | 0/4 | 4/4 | 4/4 |
| repeat-error-code | 0/4 | 0/4 | 0/4 | 0/4 |
| video-how-to | 4/4 | 4/4 | 4/4 | 4/4 |

Cost: about $0.05–0.08 for each 32-trial run.

### NLU (`evals/datasets/nlu.yaml`, 71 messages, Haiku 5.5)

| Metric | M3 (68) | M5 final (71) |
|---|---|---|
| Intent accuracy | 95.6% | 95.8% |
| Slot accuracy: category / brand / model / error code | 100% / 93.3% / 100% / 100% | 100% / 100% / 100% / 100% |
| Hazard recall / precision | 92.3% / 100% | 92.3% / 92.3% |

Hazard recall moved between 92.3% and 100% across runs of the same prompt. The code layer of the two-layer detection covers the misses.

## What the runs found

The first attempt failed on every tool turn. Unit tests did not catch either cause, because they stub the completion call:

- **LiteLLM's MCP bridge.** When `tools` are passed, LiteLLM imports its MCP proxy bridge, which needs `mcp>=2`; we pin `<2`. Every tool call raised an `ImportError`. `tool_turn` now passes `_skip_mcp_handler=True`. A unit test runs the real `litellm.acompletion` with mock tool calls.
- **Forced tool choice.** DeepSeek's thinking mode, like Anthropic's extended thinking, rejects `tool_choice="required"`. The client now sends `"auto"` and enforces "must call a tool" itself: it retries once with a nudge, and the responder falls back to a plain structured reply.

v1 → v2:

- **Asking for a technician with no journey running found no journey.** The guest case got an off-topic reply. `book_technician` now also starts `troubleshoot`, whose guardrail escalates.
- **User simulator.** The simulated user pressed "not fixed" and asked for a part or a technician in the same turn. The web UI cannot send both, and the agent reads only the button. Simulator rule 4 now says a button sends only the button, and other requests are typed. This also affected the M3 runs, so M5 numbers are not directly comparable with them.
- **Supervisor.** It rejected "the video is shown in the app", because it did not know about cards. Its prompt now says parts, videos, step results and visit times are shown as cards.

v2 → v3:

- **NLU.** "My Shark vacuum lost suction even after I washed the filters. What part should I buy?" was `report_problem`, and the user's question was never answered. A message that explicitly asks which part to buy, or for a technician to come, now takes that intent. "Do I need a new pump?" stays `report_problem`. Both are dataset examples.

## Still failing: `repeat-error-code`

- **Case:** a Bosch dishwasher shows E15 again. The user's repair history says draining the base pan fixed it last time.
- **Why it fails:**
  - The Bosch SHE3AR76UC manual has no E15 or base-pan content. Retrieval falls back to category level, and the plan comes from Siemens manuals.
  - The planner does not see the repair history. A step taken only from it would also be dropped as uncited.
- **What it needs:** a design change, so that a plan step can cite the user's repair history (a tool result) alongside manual excerpts. Listed as a follow-up.

## Latency

- Single LLM calls take 5–10 s. A responder tool call with DeepSeek in thinking mode took up to 54 s once, measured locally on one `parts-vacuum` turn of 93 s.
- A turn can make several calls: tool rounds, a retry when the model answers in text instead of calling `reply`, and a supervisor revision.
- v3's p95 of 244 s came from those slow calls queuing under the concurrent run on OpenCode Go. v4's p95 was 40 s.
- Production uses Sonnet for the responder, so these numbers describe the eval models.

## Code review

Six fresh-context reviews ran on this branch. The PR description lists their findings; ADR-008 records the resulting decisions and known limits.
