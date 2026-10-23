"""Eval report summaries for /admin/evals (spec §15.2, M7-04): metrics and per-case results,
never the transcripts."""

from datetime import UTC, datetime
from typing import Any

import pytest

from homehelper.quality.eval_reports import summarize


def trial(success: bool, failed: list[str]) -> dict[str, Any]:
    return {
        "case_id": "c",
        "success": success,
        "failed_checks": failed,
        "grade": {"checks": []},
        "transcript": {"turns": [{"role": "user", "text": "my email is a@b.c"}]},
    }


def report(**overrides: Any) -> dict[str, Any]:
    return {
        "report_type": "conversation_simulation",
        "schema_version": 1,
        "release": "r1",
        "suite": "safety",
        "created_at": "2026-10-20T08:30:00+00:00",
        "git_sha": "abc1234",
        "config": {"k": 2, "judge": "anthropic/claude-sonnet-5-5"},
        "metrics": {"safety_pass_rate": 0.75, "cost_usd": {"total": 0.42}},
        "cases": [
            {
                "case": {"id": "safe-gas-01", "kind": "safety", "scenario": "..."},
                "successes": 1,
                "trials": [trial(True, []), trial(False, ["hazard_first_reply", "cards"])],
            },
            {
                "case": {"id": "inj-01", "kind": "injection"},
                "successes": 2,
                "trials": [trial(True, []), trial(True, [])],
            },
        ],
        **overrides,
    }


def test_a_summary_keeps_metrics_and_per_case_results() -> None:
    summary = summarize(report(), report_id="r1_safety_20261020T083000Z", source_uri="x.json")
    assert summary.id == "r1_safety_20261020T083000Z"
    assert (summary.release_id, summary.suite, summary.git_sha) == ("r1", "safety", "abc1234")
    assert summary.created_at == datetime(2026, 10, 20, 8, 30, tzinfo=UTC)
    assert summary.metrics["safety_pass_rate"] == 0.75
    assert summary.config["k"] == 2
    first, second = summary.cases
    assert (first.id, first.kind, first.successes, first.trials) == ("safe-gas-01", "safety", 1, 2)
    assert first.failed_checks == {"cards": 1, "hazard_first_reply": 1}
    assert (second.successes, second.failed_checks) == (2, {})
    assert "a@b.c" not in summary.model_dump_json()  # no transcripts


@pytest.mark.parametrize(
    "bad",
    [
        {"report_type": "retrieval"},
        {"report_type": None},
        {"suite": None},
        {"created_at": "not a date"},
    ],
)
def test_only_conversation_simulation_reports_are_summarized(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        summarize(report(**bad), report_id="x", source_uri=None)
