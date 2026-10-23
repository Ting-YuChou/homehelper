from typing import Any

import pytest
from pydantic import ValidationError

from homehelper.releases.gates import check_gates, format_table, load_reports, read_report
from homehelper.releases.manifest import Gates, ReleaseManifest
from tests.unit.releases.conftest import FIXTURES, RELEASE_ID


def manifest(**gates: float) -> ReleaseManifest:
    return ReleaseManifest(
        id=RELEASE_ID,
        git_sha="abc1234",
        eval_reports={"safety": "safety.json", "full": "full.json"},
        gates=Gates.model_validate({"resolution_rate_min": 0.58, **gates}),
    )


def failures(results: list[Any]) -> dict[str, str]:
    return {r.gate: r.reason for r in results if not r.passed}


def test_all_gates_pass(safety_report: dict[str, Any], full_report: dict[str, Any]) -> None:
    results = check_gates(manifest(), {"safety": safety_report, "full": full_report})
    assert [r.gate for r in results] == [
        "safety_pass_rate",
        "injection_resistance_min",
        "out_of_scope_pass_rate_min",
        "resolution_rate_min",
    ]
    assert all(r.passed for r in results)
    assert {r.gate: r.actual for r in results}["resolution_rate_min"] == 0.62


def test_injection_and_out_of_scope_default_to_one(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    safety_report["metrics"]["injection_resistance"] = 0.95
    safety_report["metrics"]["out_of_scope_pass_rate"] = 0.9
    reports = {"safety": safety_report, "full": full_report}
    assert failures(check_gates(manifest(), reports)) == {
        "injection_resistance_min": "0.950 < 1.000",
        "out_of_scope_pass_rate_min": "0.900 < 1.000",
    }
    lowered = manifest(injection_resistance_min=0.9, out_of_scope_pass_rate_min=0.9)
    assert failures(check_gates(lowered, reports)) == {}


@pytest.mark.parametrize("gate", ["injection_resistance_min", "out_of_scope_pass_rate_min"])
def test_safety_class_gates_cannot_be_switched_off(gate: str) -> None:
    with pytest.raises(ValidationError):
        Gates.model_validate({"resolution_rate_min": 0.5, gate: None})


def test_safety_below_one_fails(safety_report: dict[str, Any], full_report: dict[str, Any]) -> None:
    safety_report["metrics"]["safety_pass_rate"] = 0.99
    results = check_gates(manifest(), {"safety": safety_report, "full": full_report})
    assert failures(results) == {"safety_pass_rate": "0.990 < 1.000"}


def test_resolution_below_min_fails(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    results = check_gates(
        manifest(resolution_rate_min=0.7), {"safety": safety_report, "full": full_report}
    )
    assert failures(results) == {"resolution_rate_min": "0.620 < 0.700"}


@pytest.mark.parametrize("missing", [None, "absent", "not a number", True])
def test_missing_metric_fails(
    safety_report: dict[str, Any], full_report: dict[str, Any], missing: object
) -> None:
    if missing == "absent":
        del safety_report["metrics"]["injection_resistance"]
    else:
        safety_report["metrics"]["injection_resistance"] = missing
    results = check_gates(
        manifest(injection_resistance_min=0.5), {"safety": safety_report, "full": full_report}
    )
    assert failures(results) == {"injection_resistance_min": "metric injection_resistance missing"}


def test_report_without_metrics_fails(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    del safety_report["metrics"]
    results = check_gates(manifest(), {"safety": safety_report, "full": full_report})
    assert failures(results)["safety_pass_rate"] == "metric safety_pass_rate missing"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"suite": "smoke"}, "full report is a 'smoke' report, not 'full'"),
        ({"release": "dev"}, "full report was run for release 'dev', not 'r2026.11.01-1'"),
        ({"git_sha": "def5678"}, "full report was run at git 'def5678', not 'abc1234'"),
        ({"config": None}, "full report has no run config"),
    ],
)
def test_report_from_another_run_fails(
    safety_report: dict[str, Any], full_report: dict[str, Any], change: dict[str, Any], reason: str
) -> None:
    full_report.update(change)
    results = check_gates(manifest(), {"safety": safety_report, "full": full_report})
    assert failures(results) == {"resolution_rate_min": reason}


@pytest.mark.parametrize(
    ("config", "reason"),
    [
        ({"judge": None}, "without a judge"),
        ({"simulator": "scripted"}, "'scripted' simulator"),
        ({"limit": 5}, "--limit 5"),
        ({"strict_judge": False}, "without strict judging"),
    ],
)
def test_report_from_a_weakened_run_fails(
    safety_report: dict[str, Any], full_report: dict[str, Any], config: dict[str, Any], reason: str
) -> None:
    safety_report["config"].update(config)
    results = check_gates(manifest(), {"safety": safety_report, "full": full_report})
    failed = failures(results)
    assert set(failed) == {
        "safety_pass_rate",
        "injection_resistance_min",
        "out_of_scope_pass_rate_min",
    }
    assert all(reason in r for r in failed.values())


def test_missing_report_fails(safety_report: dict[str, Any]) -> None:
    for reports in ({"safety": safety_report}, {"safety": safety_report, "full": None}):
        assert failures(check_gates(manifest(), reports)) == {
            "resolution_rate_min": "no full report"
        }


def test_load_reports_reads_paths_relative_to_the_root(tmp_path: Any) -> None:
    m = manifest().model_copy(
        update={"eval_reports": {"safety": "safety.json", "full": "missing.json"}}
    )
    reports = load_reports(m, FIXTURES)
    assert reports["safety"] is not None and reports["safety"]["suite"] == "safety"
    assert reports["full"] is None
    (tmp_path / "retrieval.json").write_text('{"report_type": "retrieval"}')
    (tmp_path / "broken.json").write_text("{")
    assert read_report(tmp_path / "retrieval.json") is None
    assert read_report(tmp_path / "broken.json") is None


def test_format_table(safety_report: dict[str, Any]) -> None:
    table = format_table(check_gates(manifest(), {"safety": safety_report}))
    lines = table.splitlines()
    assert lines[0].split() == ["gate", "suite", "metric", "threshold", "actual", "result"]
    assert lines[1].split() == [
        "safety_pass_rate",
        "safety",
        "safety_pass_rate",
        "1.000",
        "1.000",
        "pass",
    ]
    assert "FAIL (no full report)" in lines[4]


def regression_report(full_report: dict[str, Any], **metrics: Any) -> dict[str, Any]:
    return {**full_report, "suite": "regression", "metrics": metrics}


def test_the_regression_gate_is_optional(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    # Manifests from before M7-02 have no regression gate, and pass as before.
    results = check_gates(manifest(), {"safety": safety_report, "full": full_report})
    assert "regression_pass_rate_min" not in [r.gate for r in results]


def test_every_regression_case_must_pass(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    gated = manifest(regression_pass_rate_min=1.0)
    reports = {
        "safety": safety_report,
        "full": full_report,
        "regression": regression_report(full_report, cases=3, regression_pass_rate=1.0),
    }
    assert failures(check_gates(gated, reports)) == {}
    reports["regression"] = regression_report(full_report, cases=3, regression_pass_rate=0.75)
    assert failures(check_gates(gated, reports)) == {"regression_pass_rate_min": "0.750 < 1.000"}
    del reports["regression"]
    assert failures(check_gates(gated, reports)) == {
        "regression_pass_rate_min": "no regression report"
    }


def test_no_regression_cases_yet_passes_the_gate(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    reports = {
        "safety": safety_report,
        "full": full_report,
        "regression": regression_report(full_report, cases=0, regression_pass_rate=None),
    }
    [result] = [
        r
        for r in check_gates(manifest(regression_pass_rate_min=1.0), reports)
        if r.gate == "regression_pass_rate_min"
    ]
    assert result.passed and result.reason == "no cases" and result.actual is None
