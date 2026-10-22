# ADR-007: Track several open issues per conversation

- **Status:** Accepted; implemented in M3-13 with the amendments below
- **Date:** 2026-10-21
- **Spec:** §7.2, §7.4

## Context

Users interleave problems: halfway through fixing the washer they mention the dryer, then come back. The M3 engine keeps a single `paused_journey`, which falls short in five ways:

1. **One level only.** A third topic overwrites the paused one, and its progress is lost (only a `dropped paused journey` decision is logged).
2. **Going back restarts the issue.** If the user says "forget the dryer, back to the washer" while the dryer issue is still running, `route()` sees another appliance switch: it starts a fresh washer `troubleshoot` from `gather` and pauses the dryer, discarding the washer's plan and cursor.
3. **One reminder only.** Resuming happens only through a `confirm` right after another journey ends. If the user says anything else, the open issue is never brought up again.
4. **One outcome per conversation.** `AgentState.outcome`, `AgentSnapshot.outcome` and the eval success rule (§16.3) cannot express "washer resolved, dryer escalated".
5. **No follow-up across conversations.** Unresolved issues live only in the conversation's checkpoint.

Constraints: routing stays a pure function in the journey engine (P1, ≥ 90% coverage), the LLM never decides control flow, hazard replies stay fixed templates, and the responder's prompt must not grow without bound.

## Decision

Replace the single paused slot with **issues**: every journey run is an issue with a stable id, at most one is active and at most three are paused, and the engine resumes them by deterministic rules.

- **State.** `AgentState` keeps the active issue's fields flat (`active_journey`, `step_id`, `slots`, `plan`, …) so the engine and nodes change little, and adds `active_issue_id`, `paused_issues: list[PausedIssue]` (oldest first, max `MAX_PAUSED_ISSUES = 3`) and `issues: list[IssueRecord]` (every issue opened in the conversation with its outcome). Ids are `iss_<n>`, numbered in opening order. A `summary` such as `"Bosch washer: not draining"` is built by code from the slots, never by the LLM.
- **Pausing.** The existing switch triggers (another appliance in `guide`/`inform`/`handoff`, or an intent that belongs to another journey) push the active issue onto `paused_issues`. When the list is full, the oldest is closed as `abandoned` and logged; nothing is dropped silently.
- **Resuming by appliance.** When a turn's `appliance_category` matches a paused issue and the turn brings no new `symptom`, the engine resumes that issue (the most recent one if several match) instead of starting a new one, and pauses the active issue. A new `symptom` on the same appliance means a new problem: it starts a new issue, and the paused one stays available. In a `collect` step a category change that matches a paused issue resumes it and closes the barely started issue as `abandoned`; otherwise it remains a correction.
- **Resuming by button or reply.** When an issue ends and others are paused, the reply carries the `resume_paused` notice and an `IssuesCard` listing them. Its buttons send `StructuredAction(type="resume_issue" | "close_issue", value=<issue id>)`, which skip the NLU. A typed `confirm` resumes the most recently paused issue; a `deny` leaves them paused, and the offer comes back only when another issue ends. A turn whose reply is a hazard template never carries the offer.
- **Outcomes.** Each issue gets its own outcome when it ends. The conversation `outcome` stays as a summary: `None` while any issue is active or paused, otherwise the highest of `escalated` > `resolved` > `out_of_scope` > `abandoned`. A single-issue conversation therefore behaves exactly as today.

## Consequences

- Interleaved problems keep their progress, and returning to an earlier appliance is no longer a restart.
- Every pause, resume, drop and close is a `Decision` (`kind="route"`), so the trace explains the history of each issue (P7).
- The resume rule uses only slots and signals the NLU already produces; there is no new intent and no LLM-chosen issue id.
- Follow-up changes outside §7.2/§7.4, to land with the implementation:
  - §13.1/§13.3: two new `StructuredAction` types and the `IssuesCard` (an additive change to `channels/events.py`, owned by Track D).
  - `AgentSnapshot` gains `issues`; §16.3 grades multi-issue cases per issue, and new eval scenarios interleave two appliances.
  - §14.1: `conversations.outcome` stores the summary outcome.
- Known limits: matching is by appliance category, so two open issues on the same appliance are told apart only through the card. A paused plan may be stale if the user fixed the problem in the meantime; the resumed `guide` step re-presents the current item, and the user can answer "fixed".
- Cross-conversation follow-up is out of scope here. The likely route is writing unresolved issues through `user_profile` when a conversation goes idle and reading them in `load_context`, but writes may only happen in step actions, so that needs its own design (M5 or later).

## Alternatives considered

- **Unbounded stack of paused journeys:** strict LIFO order is unnatural (users return to any issue, not just the last one), and an unbounded list grows the state and the responder's context.
- **Let the LLM pick which issue a message belongs to:** more flexible, but it puts control flow in the LLM (against P1), cannot be unit-tested as a pure function, and misroutes are hard to explain.
- **Keep one paused journey and only add a resume card:** fixes problem 3 but not 1, 2 or 4.
- **One conversation per issue:** simple state, but users do not think in conversations, and it moves the problem into the UI.

## Amendments made while implementing (M3-13)

- **Settled issues are closed, not paused.** When the user switches away from an issue that already has its answer, it ends with that outcome: an `inform` step as `resolved`, a `handoff` step as `escalated` (booking arrives in M5; revisit then). An issue still collecting details (`collect`/`confirm`) ends as `abandoned`. Paused issues are therefore always unfinished, and "ask when an issue ends" stays meaningful.
- **The provisional outcome is derived, not stored.** `_enter` no longer writes `state.outcome`. Each turn computes the conversation outcome from the issue records plus the active step's outcome (provisional at `handoff`/`inform`), so a single escalation still reports `escalated` at the handoff step, as before.
- **Replies are not issues.** A journey whose entry step is an `end` step (the out-of-scope decline) gets no issue id and no record; its outcome still counts in the summary.
- **Stricter resume-by-appliance.** Besides "no new symptom", the turn must bring no new `question`, its intent's journey must be none or the paused one's, and the category must differ from the active issue's. An escalating hazard on a paused appliance resumes that issue regardless, so its guardrail escalates it instead of the issue staying paused after the user was told to stop using the appliance.
- **An escalating hazard closes the paused issues on that appliance** as `escalated` (all of them for a gas smell, or when the appliance is unknown), so DIY steps cannot come back for an appliance the user was told to stop using. Card turns skip the NLU, so a hazard typed with a card action may be about any appliance and closes all of them. A close or stale card on a hazard turn does not stop the hazard from being routed as usual (the close still applies).
- **Turning a paused issue down by name closes it** when nothing else is running: a `deny` naming a paused appliance ("forget the dishwasher") closes it as `abandoned`, unless the turn also answers a step. Mid-journey such a `deny` is ambiguous ("no, I meant the dishwasher") and resumes as before. A goodbye (`small_talk`) that names a paused appliance never resumes it; the closing reminder covers it. A `confirm_appliance` button never answers the offer: only words do.
- **A card resume is another problem for G-SAFE-05**: water mentioned on the same turn gets the full warning, not the reminder.
- **Each paused issue keeps its `last_retrieval`**, so a resumed step cites its own manual; the search query from a turn about another issue is not reused.
- **A closing reminder.** Besides the offer when an issue ends, the user is reminded once when they wrap up with small talk and paused issues remain (`remind_paused`, `paused_reminder_used`). A declined offer uses it up.
- **Stale card presses** (an id that is not paused) are ignored and logged; they are not step attempts.
- **Evaluation.** The `multi_issue` suite (10 cases) is driven by the runner: it brings up the second problem after the first step card and returns to the first once the second is settled, by card, appliance name, typed "yes", or closing it. Grading is per issue, plus "the paused issue was offered" and per-turn citations against the active issue's manual.
