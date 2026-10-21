# M2-01 root-cause labels: spot check

Frozen file: `data/scenarios/root_cause_steps.v1.json`: 978 scenario variants from 971 scenario
groups (a variant is a group plus one distinct `solution_steps` text; 5 groups have two variants
and 1 group has three, because the same scenario text appears in several manuals).

## How the labels were made

- Produced by the code behind `uv run evals label-root-causes` (`extract` task,
  `anthropic/claude-haiku-5-5`), one call per variant, structured output `RootCauseLabel`
  validated by Pydantic, step number range-checked.
- Fields per variant: `root_cause_step` (1-based), `user_fixable` (false when the fixing step is
  "contact service"), `troubleshootable` (false for warnings and documentation notes that no user
  would report as a problem), `rationale`, plus the step text, scenario, split and row ids for
  review.
- Cost: USD 0.41 in total for two full runs (the first run had no `troubleshootable` field; it
  was discarded after the first spot check, see below).

| | count |
|---|---|
| variants | 978 |
| user-fixable | 899 |
| troubleshootable (used for conversation simulation) | 805 |

## Spot check (72 variants read by hand)

**Run 1, 40 variants** (random seed 42 plus 5 non-fixable ones): the chosen step was reasonable
in 36/40. The four weak ones were all scenarios that are not real problems ("Changes in
product specifications ... can cause confusion", "Ingredients need to be processed in batches").
About one scenario in six in the dataset is a warning or note copied from the manual's safety
section ("Placing flammable substances inside the refrigerator results in risk of fire"). These
make meaningless conversations, so the labeler was extended with `troubleshootable` and rerun.

**Run 2 (frozen file), 32 multi-step variants** (random seed 2026):

- 28/32 good: the step directly addresses the symptom (mesh filter for low water supply, Child
  Lock release, ice bucket seating, door alignment screw, ...).
- 4/32 debatable but usable:
  - `7c88b6789dbf` "Improper operation ... failure to follow instructions": vague scenario,
    step 1 ("read the instructions") picked; should arguably be non-troubleshootable.
  - `aafd5af107ec` water purifier feed-water error: picked "switch off the purifier" over
    "call Customer Care"; `user_fixable` arguably false.
  - `95051ed9626c` vacuum filter: picked "tap the filter" where washing it is the real fix.
  - `0685857f6c4e` Laundry Combo clicking: picked "laundry caught in the door" out of 11
    steps; plausible, not certain.
- Non-troubleshootable flags were right in 12/12 sampled (cord handling, installation and
  chemical warnings); one borderline case ("does not operate if the water tank is empty") was
  excluded although it is a real problem.

Agreement is about 88% on step choice, with the misses concentrated in vague scenarios. Good
enough to freeze: graders only need the simulated user to have *one* consistent fix per case,
and pass^k compares agents on the same labels.

## Known data issues (not fixed, documented)

- Some `solution_steps` mix causes and actions ("House fuse is blown, circuit breaker has
  tripped ..." followed by "Reset circuit breaker"); the label may point at the cause line.
  The simulated user matches semantically, so either phrasing from the agent counts.
- Some troubleshootable scenarios contain hazard words ("a burning smell is detected, and the
  brush roll will not turn"). The agent must escalate on these (spec §8.1), so for the 11 such
  scenarios escalation is also accepted (`cases.HAZARD_HINT`).
- A few root-cause steps are themselves unsafe advice for the symptom (coffee maker with a
  damaged cord: "keep the cord away from hot surfaces"). The rubric judge flags an agent that
  "resolves" these; an agent that escalates fails the outcome check. Candidates for a v2 label
  file if they show up in failure analysis.
