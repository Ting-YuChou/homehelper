"""Release gates (spec §17.3, M7-03): each gate compares one metric of one eval suite's report
with the manifest's threshold. A missing report or metric fails its gate, and so does a report
that was not produced for this release (suite, release id, git_sha) or by a weakened run (no
judge, scripted simulator, `--limit`, lenient judge), so a release can never pass on data it
does not have."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homehelper.releases.manifest import ReleaseManifest

# The report format written by `evals run` (evals/homehelper_evals/runner.py).
REPORT_TYPE = "conversation_simulation"


@dataclass(frozen=True)
class GateSpec:
    gate: str  # field of `Gates`
    suite: str  # the eval suite whose report holds the metric
    metric: str  # key in the report's `metrics`


GATE_SPECS: tuple[GateSpec, ...] = (
    GateSpec("safety_pass_rate", "safety", "safety_pass_rate"),
    GateSpec("injection_resistance_min", "safety", "injection_resistance"),
    GateSpec("out_of_scope_pass_rate_min", "safety", "out_of_scope_pass_rate"),
    GateSpec("resolution_rate_min", "full", "resolution_rate"),
)


@dataclass(frozen=True)
class GateResult:
    gate: str
    suite: str
    metric: str
    threshold: float
    actual: float | None
    passed: bool
    reason: str  # why it failed, or "ok"


Report = Mapping[str, Any]


def weakened_run_error(report: Report) -> str | None:
    """Why the report's run cannot gate a release, or None. Keys as written by `evals run`
    (`config` in evals/homehelper_evals/cli.py): a release run has an LLM judge and an LLM user
    simulator, covers every case (no `--limit`) and treats an unavailable judge as a failure."""
    config = report.get("config")
    if not isinstance(config, Mapping):
        return "has no run config"
    if not config.get("judge"):
        return "was run without a judge (--no-judge)"
    simulator = config.get("simulator")
    if not isinstance(simulator, str) or not simulator.startswith("llm"):
        return f"was run with the {simulator!r} simulator, not the LLM one"
    if config.get("limit") is not None:
        return f"was run with --limit {config.get('limit')}"
    if config.get("strict_judge") is not True:
        return "was run without strict judging"
    return None


def provenance_error(manifest: ReleaseManifest, suite: str, report: Report) -> str | None:
    """Why the report does not belong to this manifest's `suite`, or None."""
    if report.get("suite") != suite:
        return f"is a {report.get('suite')!r} report, not {suite!r}"
    if report.get("release") != manifest.id:
        return f"was run for release {report.get('release')!r}, not {manifest.id!r}"
    if report.get("git_sha") != manifest.git_sha:
        return f"was run at git {report.get('git_sha')!r}, not {manifest.git_sha!r}"
    return weakened_run_error(report)


def _check(
    spec: GateSpec, threshold: float, report: Report | None, manifest: ReleaseManifest
) -> GateResult:
    def result(actual: float | None, reason: str | None = None) -> GateResult:
        passed = reason is None
        return GateResult(
            spec.gate, spec.suite, spec.metric, threshold, actual, passed, reason or "ok"
        )

    if report is None:
        return result(None, f"no {spec.suite} report")
    if error := provenance_error(manifest, spec.suite, report):
        return result(None, f"{spec.suite} report {error}")
    metrics = report.get("metrics")
    value = metrics.get(spec.metric) if isinstance(metrics, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return result(None, f"metric {spec.metric} missing")
    actual = float(value)
    return result(actual, None if actual >= threshold else f"{actual:.3f} < {threshold:.3f}")


def check_gates(
    manifest: ReleaseManifest, reports: Mapping[str, Report | None]
) -> list[GateResult]:
    """One result per gate. `reports` maps a suite to its loaded report; None or an absent
    suite means the report is missing."""
    return [
        _check(spec, getattr(manifest.gates, spec.gate), reports.get(spec.suite), manifest)
        for spec in GATE_SPECS
    ]


def read_report(path: Path) -> dict[str, Any] | None:
    """A conversation-simulation report, or None when the file is missing, unreadable or of
    another type (e.g. a retrieval report)."""
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict) or report.get("report_type") != REPORT_TYPE:
        return None
    return report


def load_reports(manifest: ReleaseManifest, root: Path) -> dict[str, dict[str, Any] | None]:
    """The manifest's `eval_reports`, read from paths relative to `root` (the repo root).
    `check_gates` re-checks that each one belongs to the manifest (`provenance_error`)."""
    return {suite: read_report(root / path) for suite, path in manifest.eval_reports.items()}


def format_table(results: list[GateResult]) -> str:
    rows = [("gate", "suite", "metric", "threshold", "actual", "result")]
    for r in results:
        actual = "-" if r.actual is None else f"{r.actual:.3f}"
        verdict = "pass" if r.passed else f"FAIL ({r.reason})"
        rows.append((r.gate, r.suite, r.metric, f"{r.threshold:.3f}", actual, verdict))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )
