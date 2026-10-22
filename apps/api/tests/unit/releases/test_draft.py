from typing import Any

import pytest

from homehelper.releases.draft import DraftError, draft_manifest
from homehelper.releases.manifest import TaskOverride
from tests.unit.releases.conftest import RELEASE_ID

GATES = {"resolution_rate_min": 0.58}


def reports(safety: dict[str, Any], full: dict[str, Any]) -> dict[str, Any]:
    return {"safety": ("evals/reports/s.json", safety), "full": ("evals/reports/f.json", full)}


def test_draft_takes_git_sha_and_models_from_the_reports(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    manifest = draft_manifest(
        RELEASE_ID, reports(safety_report, full_report), gates=GATES, kb_version="kb_20261030_01"
    )
    assert manifest.git_sha == "abc1234"
    assert manifest.models == {"nlu": "anthropic/claude-haiku-5-5"}  # bare id: no fallbacks
    assert manifest.eval_reports == {
        "safety": "evals/reports/s.json",
        "full": "evals/reports/f.json",
    }
    assert manifest.gates.safety_pass_rate == 1.0
    assert manifest.gates.resolution_rate_min == 0.58
    assert manifest.kb_version == "kb_20261030_01"


def test_partial_task_overrides_are_kept(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    override = {"responder": {"model": "openai/gpt-5.5", "fallbacks": [], "max_tokens": 3000}}
    for report in (safety_report, full_report):
        report["config"]["model_overrides"] = override
    manifest = draft_manifest(RELEASE_ID, reports(safety_report, full_report), gates=GATES)
    assert manifest.models == {
        "responder": TaskOverride(model="openai/gpt-5.5", fallbacks=[], max_tokens=3000)
    }


def test_no_overrides_means_no_models(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    safety_report["config"]["model_overrides"] = None
    del full_report["config"]["model_overrides"]
    assert draft_manifest(RELEASE_ID, reports(safety_report, full_report), gates=GATES).models == {}


def test_git_sha_mismatch_is_refused(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    full_report["git_sha"] = "def5678"
    with pytest.raises(DraftError, match="disagree on git_sha"):
        draft_manifest(RELEASE_ID, reports(safety_report, full_report), gates=GATES)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"release": "dev"}, "was run for release 'dev'"),
        ({"suite": "smoke"}, "is a 'smoke' report"),
        ({"git_sha": None}, "has no git_sha"),
        (
            {"config": {"model_overrides": {"nlu": {"model": "x", "fallbacks": []}}}},
            "model overrides",
        ),
    ],
)
def test_inconsistent_reports_are_refused(
    safety_report: dict[str, Any], full_report: dict[str, Any], change: dict[str, Any], message: str
) -> None:
    full_report.update(change)
    with pytest.raises(DraftError, match=message):
        draft_manifest(RELEASE_ID, reports(safety_report, full_report), gates=GATES)


def test_unreadable_report_and_no_reports_are_refused(safety_report: dict[str, Any]) -> None:
    with pytest.raises(DraftError, match="not a readable"):
        draft_manifest(RELEASE_ID, reports(safety_report, None), gates=GATES)  # type: ignore[arg-type]
    with pytest.raises(DraftError, match="at least one"):
        draft_manifest(RELEASE_ID, {}, gates=GATES)


def test_gates_and_models_are_validated(
    safety_report: dict[str, Any], full_report: dict[str, Any]
) -> None:
    with pytest.raises(DraftError, match="resolution_rate_min"):
        draft_manifest(RELEASE_ID, reports(safety_report, full_report), gates={})
    for report in (safety_report, full_report):
        report["config"]["model_overrides"] = {"no_such_task": {"model": "x", "fallbacks": []}}
    with pytest.raises(DraftError, match="unknown task"):
        draft_manifest(RELEASE_ID, reports(safety_report, full_report), gates=GATES)
