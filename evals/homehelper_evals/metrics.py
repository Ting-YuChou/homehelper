"""Aggregate metrics over graded trials (spec §16.3 table)."""

import statistics
from math import comb
from typing import Any

from pydantic import BaseModel

from homehelper_evals.cases import CaseKind, EvalCase
from homehelper_evals.graders import Grade
from homehelper_evals.graders.deterministic import card_doc_ids, revealed_at
from homehelper_evals.manifest import doc_groups
from homehelper_evals.transcript import Transcript

EVAL_SIDE_TASKS = frozenset({"user_simulator", "judge"})
JUDGE_CHECKS = frozenset({"judge_safety", "expected_behavior"})


class TrialResult(BaseModel):
    transcript: Transcript
    grade: Grade

    @property
    def success(self) -> bool:
        return self.grade.success


class CaseResult(BaseModel):
    case: EvalCase
    trials: list[TrialResult]

    @property
    def successes(self) -> int:
        return sum(t.success for t in self.trials)


def pass_hat_k(results: list[CaseResult], k: int) -> float | None:
    """τ-bench pass^k: the chance that k trials of a case, drawn without replacement from its n
    recorded trials, all succeed, averaged over cases (unbiased estimator C(c, k) / C(n, k))."""
    eligible = [r for r in results if len(r.trials) >= k]
    if not eligible:
        return None
    return statistics.fmean(comb(r.successes, k) / comb(len(r.trials), k) for r in eligible)


def _rate(trials: list[TrialResult]) -> float | None:
    return statistics.fmean(t.success for t in trials) if trials else None


def _mean(values: list[float] | list[bool] | list[int]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _check_rate(trials: list[TrialResult], name: str) -> float | None:
    results = [c.passed for t in trials for c in t.grade.checks if c.name == name]
    return _mean([r for r in results if r is not None])


def turns_to_first_step(transcript: Transcript) -> int | None:
    """User turns sent before the first reply with a step card (1: the first reply had one)."""
    sent = 0
    for turn in transcript.turns:
        if turn.role == "user":
            sent += 1
        elif turn.step_cards:
            return sent
    return None


def citation_scope(
    case: EvalCase, transcript: Transcript, groups: dict[str, tuple[str | None, str | None]]
) -> dict[str, int]:
    """Step-card citations by manual: the user's own, another model of the same brand and
    category, or another appliance's."""
    own = (case.brand, case.category.value if case.category else None)
    counts = {"own": 0, "same_brand": 0, "other": 0}
    for turn in transcript.agent_turns:
        for card in turn.step_cards:
            for doc_id in card_doc_ids(card):
                if doc_id == case.expected_doc_id:
                    counts["own"] += 1
                elif groups.get(doc_id) == own:
                    counts["same_brand"] += 1
                else:
                    counts["other"] += 1
    return counts


def no_model_metrics(results: list[CaseResult], k: int) -> dict[str, Any] | None:
    """No-model suites, by what the user knows and whether the brand alone pins the manual
    ("several": the brand has several manuals in the category)."""
    picked = [r for r in results if r.case.kind == "scenario" and r.case.paired_with]
    if not picked:
        return None
    groups = doc_groups()
    report: dict[str, Any] = {}
    for knowledge in ("unknown", "finds_when_asked"):
        for size in ("several", "single", "all"):
            rs = [
                r
                for r in picked
                if r.case.model_knowledge == knowledge
                and (size == "all" or ((r.case.manuals_for_brand or 1) > 1) == (size == "several"))
            ]
            if not rs:
                continue
            trials = [t for r in rs for t in r.trials]
            scopes = [citation_scope(r.case, t.transcript, groups) for r in rs for t in r.trials]
            cited = {key: sum(s[key] for s in scopes) for key in ("own", "same_brand", "other")}
            total = sum(cited.values())
            rubrics = [(r.case, t.grade.rubric) for r in rs for t in r.trials if t.grade.rubric]
            entry: dict[str, Any] = {
                "cases": len(rs),
                "trials": len(trials),
                "success_rate": _rate(trials),
                "resolved": _mean([t.transcript.outcome == "resolved" for t in trials]),
                "pass_hat_k": {str(j): pass_hat_k(rs, j) for j in range(1, k + 1)},
                "fix_offered": _mean(
                    [
                        rubric.fix_offered
                        for case, rubric in rubrics
                        if rubric.fix_offered is not None and case.user_fixable
                    ]
                ),
                "model_requests": _mean(
                    [r.model_requests for _, r in rubrics if r.model_requests is not None]
                ),
                "model_honesty": _mean(
                    [r.model_honesty for _, r in rubrics if r.model_honesty is not None]
                ),
                "model_asks_pass": _check_rate(trials, "model_asks"),
                "turns_to_first_step": _mean(
                    [n for t in trials if (n := turns_to_first_step(t.transcript)) is not None]
                ),
                "step_citations": {
                    key: round(count / total, 4) if total else None for key, count in cited.items()
                },
            }
            if knowledge == "finds_when_asked":
                entry["model_given"] = _mean(
                    [revealed_at(r.case, t.transcript) is not None for r in rs for t in r.trials]
                )
                entry["model_citations_pass"] = _check_rate(trials, "model_citations")
            report[f"{knowledge}/{size}"] = entry
    return report


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1], 1)


def compute_metrics(results: list[CaseResult], k: int) -> dict[str, Any]:
    by_kind: dict[CaseKind, list[CaseResult]] = {}
    for result in results:
        by_kind.setdefault(result.case.kind, []).append(result)
    trials_of = {kind: [t for r in rs for t in r.trials] for kind, rs in by_kind.items()}
    all_trials = [t for r in results for t in r.trials]
    scenario_trials = trials_of.get("scenario", [])
    scenarios = by_kind.get("scenario", [])

    citation_results = [
        c.passed
        for t in all_trials
        for c in t.grade.checks
        if c.name == "citations" and c.passed is not None
    ]
    resolved_turns = [
        len(t.transcript.user_turns)
        for t in scenario_trials
        if t.success and t.transcript.outcome == "resolved"
    ]
    rubrics = [t.grade.rubric for t in all_trials if t.grade.rubric]
    usage = [u for t in all_trials for u in t.transcript.usage]
    agent_cost = sum(u.cost_usd for u in usage if u.task not in EVAL_SIDE_TASKS)
    turn_latencies = [a.latency_ms for t in all_trials for a in t.transcript.agent_turns]
    durations = [t.transcript.duration_ms for t in all_trials]
    issue_hits = [
        c.passed
        for t in trials_of.get("multi_issue", [])
        for c in t.grade.checks
        if c.name == "issue_outcomes" and c.passed is not None
    ]
    failed: dict[str, int] = {}
    for trial in all_trials:
        for name in trial.grade.failed():
            failed[name] = failed.get(name, 0) + 1

    return {
        "cases": len(results),
        "trials": len(all_trials),
        "success_rate": _rate(all_trials),
        "resolution_rate": _rate(scenario_trials),
        "pass_hat_k": {str(j): pass_hat_k(scenarios, j) for j in range(1, k + 1)},
        "pass_hat_k_by_kind": {
            kind: {str(j): pass_hat_k(rs, j) for j in range(1, k + 1)}
            for kind, rs in sorted(by_kind.items())
        },
        "safety_pass_rate": _rate(trials_of.get("safety", [])),
        "injection_resistance": _rate(trials_of.get("injection", [])),
        "out_of_scope_pass_rate": _rate(trials_of.get("out_of_scope", [])),
        "multi_issue_pass_rate": _rate(trials_of.get("multi_issue", [])),
        "tool_scenario_pass_rate": _rate(trials_of.get("tools", [])),
        "multimodal_pass_rate": _rate(trials_of.get("multimodal", [])),
        "regression_pass_rate": _rate(trials_of.get("regression", [])),
        # Trials whose every issue ended as expected (the rest of the pass rate is citations,
        # the offer, turn limits and safety).
        "issue_outcome_accuracy": statistics.fmean(issue_hits) if issue_hits else None,
        "citation_accuracy": statistics.fmean(citation_results) if citation_results else None,
        # Trials the citation check applied to (needs a model number and a known manual), so a
        # null accuracy is never silent.
        "citation_trials": len(citation_results),
        "avg_turns_to_resolution": statistics.fmean(resolved_turns) if resolved_turns else None,
        "rubric": {
            dim: round(statistics.fmean(getattr(r, dim) for r in rubrics), 2) if rubrics else None
            for dim in ("one_step_at_a_time", "clarity", "empathy", "english")
        },
        "errors": sum(t.transcript.end_reason == "error" for t in all_trials),
        "judge_unavailable": sum(t.grade.judge_unavailable for t in all_trials),
        # ... of which the trial failed because a judge check had to run (strict mode).
        "judge_unavailable_failed": sum(
            t.grade.judge_unavailable and bool(JUDGE_CHECKS & set(t.grade.failed()))
            for t in all_trials
        ),
        "failed_checks": dict(sorted(failed.items())),
        "no_model": no_model_metrics(results, k),
        "latency_ms": {
            "agent_turn_p50": _percentile(turn_latencies, 50),
            "agent_turn_p95": _percentile(turn_latencies, 95),
            "conversation_p50": _percentile(durations, 50),
            "conversation_p95": _percentile(durations, 95),
        },
        "cost_usd": {
            "total": round(sum(u.cost_usd for u in usage), 6),
            "agent": round(agent_cost, 6),
            "user_simulator": round(
                sum(u.cost_usd for u in usage if u.task == "user_simulator"), 6
            ),
            "judge": round(sum(u.cost_usd for u in usage if u.task == "judge"), 6),
            "agent_per_conversation": round(agent_cost / len(all_trials), 6)
            if all_trials
            else None,
        },
    }
