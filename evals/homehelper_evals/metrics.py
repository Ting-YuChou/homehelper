"""Aggregate metrics over graded trials (spec §16.3 table)."""

import statistics
from math import comb
from typing import Any

from pydantic import BaseModel

from homehelper_evals.cases import CaseKind, EvalCase
from homehelper_evals.graders import Grade
from homehelper_evals.transcript import Transcript

EVAL_SIDE_TASKS = frozenset({"user_simulator", "judge"})


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
        # ... of which the trial failed because the safety check had to run (strict mode).
        "judge_unavailable_failed": sum(
            t.grade.judge_unavailable and "judge_safety" in t.grade.failed() for t in all_trials
        ),
        "failed_checks": dict(sorted(failed.items())),
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
