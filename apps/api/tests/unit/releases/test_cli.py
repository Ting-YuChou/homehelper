import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from homehelper.cli import app
from tests.unit.releases.conftest import FIXTURES, RELEASE_ID

runner = CliRunner()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo root with the fixture reports under evals/reports/."""
    reports = tmp_path / "evals" / "reports"
    reports.mkdir(parents=True)
    for name in ("safety.json", "full.json"):
        shutil.copy(FIXTURES / name, reports / name)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def draft(*extra: str) -> Any:
    return runner.invoke(
        app,
        [
            "release",
            "draft",
            "--id",
            RELEASE_ID,
            "--report",
            "safety=evals/reports/safety.json",
            "--report",
            "full=evals/reports/full.json",
            "--releases-dir",
            "releases",
            *extra,
        ],
    )


def test_draft_then_check_passes(repo: Path) -> None:
    result = draft("--gate", "resolution_rate_min=0.6", "--kb-version", "kb_20261030_01")
    assert result.exit_code == 0, result.output
    path = repo / "releases" / f"{RELEASE_ID}.yaml"
    data = yaml.safe_load(path.read_text())
    assert data["git_sha"] == "abc1234"
    assert data["eval_reports"]["full"] == "evals/reports/full.json"

    checked = runner.invoke(app, ["release", "check", str(path)])
    assert checked.exit_code == 0, checked.output
    assert "all 2 gates passed" in checked.output

    again = draft("--gate", "resolution_rate_min=0.6")
    assert again.exit_code == 1
    assert "immutable" in again.output


def test_check_fails_when_a_gate_fails(repo: Path) -> None:
    assert draft("--gate", "resolution_rate_min=0.7").exit_code == 0
    checked = runner.invoke(app, ["release", "check", f"releases/{RELEASE_ID}.yaml"])
    assert checked.exit_code == 1
    assert "FAIL (0.620 < 0.700)" in checked.output


def test_check_fails_when_a_report_is_gone(repo: Path) -> None:
    assert draft("--gate", "resolution_rate_min=0.5").exit_code == 0
    (repo / "evals" / "reports" / "full.json").unlink()
    checked = runner.invoke(app, ["release", "check", f"releases/{RELEASE_ID}.yaml"])
    assert checked.exit_code == 1
    assert "no full report" in checked.output


def test_draft_refuses_reports_from_different_commits(repo: Path) -> None:
    full = repo / "evals" / "reports" / "full.json"
    full.write_text(json.dumps({**json.loads(full.read_text()), "git_sha": "def5678"}))
    result = draft("--gate", "resolution_rate_min=0.5")
    assert result.exit_code == 1
    assert "disagree on git_sha" in result.output
    assert not (repo / "releases").exists()


@pytest.mark.parametrize("gate", ["resolution_rate_min", "resolution_rate_min=high"])
def test_draft_rejects_malformed_gates(repo: Path, gate: str) -> None:
    assert draft("--gate", gate).exit_code == 2


def test_check_rejects_an_invalid_manifest(repo: Path) -> None:
    (repo / "bad.yaml").write_text("id: x\n")
    assert runner.invoke(app, ["release", "check", "bad.yaml"]).exit_code == 2
