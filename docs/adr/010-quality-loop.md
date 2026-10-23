# ADR-010: Quality loop: admin review, regression cases replayed from real conversations, reports in the database

- **Status:** Accepted
- **Date:** 2026-10-23
- **Spec:** §13.2, §14.1, §15.2, §16.4–§16.5, §17.2–§17.3

## Context

M7 closes the loop of spec §17.2: reviewers look at real conversations, annotate replies, turn
the bad ones into regression tests, and a release must pass them. `/admin/evals` shows how the
eval suites move from release to release. Implementing that raised these questions:

1. How the browser authenticates as an admin without holding the admin token.
2. Where an exported regression case goes, when the API runs on Cloud Run and can't write into
   the repository.
3. What a regression case is: how much of the conversation it replays, and what it checks.
4. How a replay copes with an agent that now answers differently from the recorded one.
5. Where `/admin/evals` reads reports from, when the JSON files are git-ignored and not in the
   image.
6. How the regression suite gates a release while nothing has been exported yet.

## Decision

1. **The admin token is exchanged for a cookie.**
   - `POST /v1/admin/session` checks the token (constant-time) and sets `hh_admin`: signed with
     the session secret under its own salt, httpOnly, `SameSite=Lax`, Secure outside local and
     test, valid for 8 hours. Sign-in attempts are rate limited per IP (10 an hour).
   - The cookie carries a fingerprint of `ADMIN_TOKEN`, so rotating the token ends every admin
     session. With no token configured nothing validates, as before.
   - `X-Admin-Token` still works for scripts. CORS is unchanged: the browser never sends it.
   - Admin writes go through the same Origin check as every other cookie-authenticated write.

2. **Exported cases are stored in the database and pulled into the repository.**
   - `POST /v1/admin/annotations/{id}/export` writes the case to `regression_cases` and sets the
     annotation's `exported_case_id`; an exported annotation can no longer change (409).
   - `uv run evals regression pull` writes each case to
     `evals/datasets/regression/<id>.yaml` (one file per case, so cases never conflict in git)
     and copies its photos and videos from the media store to `data/media/regression/`
     (git-ignored). It is idempotent and keeps a case file that was edited locally unless
     `--force` is given.
   - The case format is `homehelper.quality.regression.RegressionCase`. The API image has no
     evals package, so the contract lives in `homehelper`; `EvalCase` is a superset and a test
     keeps the two aligned.

3. **A case replays the conversation up to the annotated reply.**
   - Every user message before the reply is replayed in order: its text, its card button press
     and its attachments. The demo user stays the same, so profile tools see the same data;
     guests replay as guests.
   - `stop_after_script` ends the replay right after the reply to the last scripted message
     (`end_reason = script_done`). No user simulator runs, and the turn limit can't fail.
   - The checks are suggested from the issue types, and the reviewer can change them before
     exporting:

     | Issue type | Suggested checks |
     |---|---|
     | `unsafe` | no step cards; the judge checks that the reply refers to a technician |
     | `missed_escalation` | outcome `escalated`; no step cards |
     | `too_many_steps_at_once` | at most one step card per reply |
     | `wrong_manual`, `hallucination` | the manual the reviewer picks must be the one cited |
     | any | the reviewer's expected response, judged on the last reply (`expected_behavior`) |

   - `expected_behavior` is a pass/fail LLM-judge check. The regression suite is strict, so an
     unavailable judge fails the trial, as on the other release suites.
   - A case must check something; an export with no checks is refused (422).

4. **A button the agent no longer offers becomes its words.** A replayed agent may answer
   differently, for example without the step card the user pressed. The replay then sends what
   the button says ("Didn't help.") instead of a press the agent would reject, and marks the
   turn `diverged`. The informational `script` check counts these turns; it never fails a trial,
   because answering differently is what a regression test exists to catch.

5. **Report summaries go into the database.**
   - `evals run --record` stores a summary of the report it wrote in `eval_reports`, and
     `evals publish <files|dirs>` stores earlier ones. The summary holds the release, suite, git
     sha, run config, metrics and per-case results, but no transcripts: they are large and may
     contain what real users typed.
   - `/admin/evals` charts one metric per small chart for each suite, ordered by run time.
   - Runs that can't gate a release are flagged with the same rule the gates use
     (`releases.gates.weakened_run_error`). They stay out of the trend lines unless the reviewer
     asks for them, so a cheap trial run never looks like a regression.
   - The charts are hand-written SVG; the pages need no chart library.

6. **The regression gate passes when there is nothing to replay.**
   - `Gates.regression_pass_rate_min` is optional, so manifests written before M7 still load and
     pass. `release.yml` sets it to 1.0: every exported case must pass on every trial.
   - A regression report with no cases passes with the reason "no cases". The gate starts to
     bite with the first exported case.

## Consequences

- **Admins see every user's conversations.** Today these are demo users and anonymous guests.
  In production `ADMIN_TOKEN` comes from Secret Manager (M8); there is still a single shared
  admin identity, so annotations record no annotator.
- **Exporting needs a manual step.** A case exists in the database first and only enters the
  suite once someone pulls it and commits the file. That is deliberate: the case is reviewed in
  a pull request like any other test.
- **Replays are not deterministic.** Web search results seen in the recorded conversation are
  not stored, so a replay gets mock search results; and the agent's own answers vary. k = 4
  trials and the `diverged` count show how stable a case is. If the gate proves too flaky, the
  fallback is a pass^1 threshold below 1.0, written into the manifest.
- **Cases with media can't replay in CI yet.** Their files are git-ignored; M8 serves them from
  GCS. Until then a regression suite with missing media exits 5, as the multimodal suite does.
- **Conversations longer than 12 user messages before the annotated reply can't be exported**
  (the eval runner's turn limit).
- **Old reports chart with gaps.** A metric that an older report lacks is null and left out of
  that chart.
