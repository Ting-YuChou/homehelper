from typing import Any

import pytest

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
    results = check_gates(
        manifest(injection_resistance_min=0.9, out_of_scope_pass_rate_min=0.9),
        {"safety": safety_report, "full": full_report},
    )
    assert [r.gate for r in results] == [
        "safety_pass_rate",
        "injection_resistance_min",
        "out_of_scope_pass_rate_min",
        "resolution_rate_min",
    ]
    assert all(r.passed for r in results)
    assert {r.gate: r.actual for r in results}["resolution_rate_min"] == 0.62


def test_unset_optional_gates_are_skipped(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    results = check_gates(manifest(), {"safety": safety_report, "full": full_report})
    assert {r.gate for r in results} == {"safety_pass_rate", "resolution_rate_min"}


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


def test_report_without_metrics_fails(full_report: dict[str, Any]) -> None:
    results = check_gates(manifest(), {"safety": {"suite": "safety"}, "full": full_report})
    assert failures(results) == {"safety_pass_rate": "metric safety_pass_rate missing"}


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
    assert "FAIL (no full report)" in lines[2]
