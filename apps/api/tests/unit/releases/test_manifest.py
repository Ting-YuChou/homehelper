from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from homehelper.ingestion.pipeline import referenced_versions
from homehelper.llm.registry import ModelRegistry
from homehelper.releases.manifest import (
    Gates,
    ReleaseManifest,
    TaskOverride,
    dump_manifest,
    load_manifest,
)
from tests.unit.releases.conftest import RELEASE_ID

MANIFEST = {
    "id": RELEASE_ID,
    "git_sha": "abc1234",
    "image": "asia-east1-docker.pkg.dev/p/r/api@sha256:" + "0" * 64,
    "kb_version": "kb_20261030_01",
    "models": {
        "nlu": "anthropic/claude-haiku-5-5",
        "responder": {"model": "openai/gpt-5.5", "max_tokens": 3000},
    },
    "eval_reports": {"safety": "evals/reports/safety.json", "full": "evals/reports/full.json"},
    "gates": {"safety_pass_rate": 1.0, "resolution_rate_min": 0.58},
}


def write(directory: Path, data: dict[str, object], name: str = RELEASE_ID) -> Path:
    path = directory / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_load_manifest_and_model_overrides(tmp_path: Path) -> None:
    write(tmp_path, MANIFEST)
    manifest = load_manifest(tmp_path, RELEASE_ID)
    assert manifest is not None
    assert manifest.kb_version == "kb_20261030_01"
    assert manifest.model_overrides() == {
        "nlu": {"model": "anthropic/claude-haiku-5-5", "fallbacks": []},
        "responder": {"model": "openai/gpt-5.5", "max_tokens": 3000},
    }
    registry = ModelRegistry.load(overrides=manifest.model_overrides())
    assert registry.for_task("nlu").model == "anthropic/claude-haiku-5-5"
    assert registry.for_task("nlu").fallbacks == []
    responder = registry.for_task("responder")
    default = ModelRegistry.load().for_task("responder")
    assert (responder.model, responder.max_tokens) == ("openai/gpt-5.5", 3000)
    assert responder.fallbacks == default.fallbacks  # unset fields keep models.yaml


def test_missing_manifest_is_none(tmp_path: Path) -> None:
    assert load_manifest(tmp_path, "dev") is None


def test_id_must_match_the_file_name(tmp_path: Path) -> None:
    write(tmp_path, MANIFEST, name="r-other")
    with pytest.raises(ValueError, match="does not match"):
        load_manifest(tmp_path, "r-other")


@pytest.mark.parametrize(
    "change",
    [
        {"unknown_field": 1},
        {"git_sha": "not-a-sha"},
        {"kb_version": "latest"},
        {"id": "../escape"},
        {"gates": {"safety_pass_rate": 1.0}},  # resolution_rate_min is required
        {"gates": {"resolution_rate_min": 1.5}},
        {"gates": {"resolution_rate_min": 0.5, "latency_max": 3}},
        {"models": {"nlu": {"model": "x", "temperature": 0}}},
    ],
)
def test_invalid_manifests_are_rejected(tmp_path: Path, change: dict[str, object]) -> None:
    write(tmp_path, {**MANIFEST, **change})
    with pytest.raises(ValidationError):
        load_manifest(tmp_path, RELEASE_ID)


def test_dump_round_trips_and_keeps_kb_versions_discoverable(tmp_path: Path) -> None:
    manifest = ReleaseManifest(
        id=RELEASE_ID,
        git_sha="abc1234",
        kb_version="kb_20261030_01",
        models={"nlu": "anthropic/claude-haiku-5-5", "planner": TaskOverride(timeout_s=60)},
        gates=Gates(resolution_rate_min=0.6),
    )
    (tmp_path / f"{RELEASE_ID}.yaml").write_text(dump_manifest(manifest))
    assert load_manifest(tmp_path, RELEASE_ID) == manifest
    assert "image" not in yaml.safe_load(dump_manifest(manifest))
    # Ingestion's retention never drops a KB version a release references.
    assert referenced_versions(tmp_path) == {"kb_20261030_01"}
