import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy.exc import OperationalError

from homehelper.main import create_app
from homehelper.releases import runtime
from homehelper.releases.manifest import ReleaseManifest
from homehelper.releases.runtime import ActiveRelease, load_active_release, record_release
from tests.conftest import make_settings
from tests.unit.releases.conftest import RELEASE_ID

MANIFEST = {
    "id": RELEASE_ID,
    "git_sha": "abc1234",
    "kb_version": "kb_20261030_01",
    "models": {"nlu": "openai/gpt-5.4-mini"},
    "gates": {"resolution_rate_min": 0.58},
}


@pytest.fixture
def releases_dir(tmp_path: Path) -> Path:
    (tmp_path / f"{RELEASE_ID}.yaml").write_text(yaml.safe_dump(MANIFEST))
    return tmp_path


async def test_app_runs_as_the_release_named_by_release_id(
    releases_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[tuple[ReleaseManifest, Path]] = []

    async def fake_upsert(engine: Any, manifest: ReleaseManifest, path: Path) -> None:
        recorded.append((manifest, path))

    monkeypatch.setattr(runtime, "upsert_release", fake_upsert)
    settings = make_settings(release_id=RELEASE_ID, releases_dir=releases_dir, mcp_mode="mock")
    app = create_app(settings)
    assert app.state.release.id == RELEASE_ID
    assert app.state.model_registry.for_task("nlu").model == "openai/gpt-5.4-mini"
    assert app.state.model_registry.for_task("nlu").fallbacks == []
    assert app.state.settings.kb_version == "kb_20261030_01"
    async with app.router.lifespan_context(app):
        pass
    assert [(m.id, p) for m, p in recorded] == [(RELEASE_ID, releases_dir / f"{RELEASE_ID}.yaml")]


async def test_without_a_manifest_the_defaults_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*_: Any) -> None:
        raise AssertionError("no release row without a manifest")

    monkeypatch.setattr(runtime, "upsert_release", fail)
    app = create_app(make_settings(mcp_mode="mock", releases_dir=Path("/nonexistent")))
    assert app.state.release is None
    assert app.state.model_registry.for_task("nlu").model == "anthropic/claude-haiku-5-5"
    async with app.router.lifespan_context(app):
        pass


def test_an_explicit_kb_version_is_overridden_by_the_release(releases_dir: Path) -> None:
    settings = make_settings(
        release_id=RELEASE_ID, releases_dir=releases_dir, kb_version="kb_20261001_01"
    )
    assert load_active_release(settings).settings.kb_version == "kb_20261030_01"


def test_production_needs_a_manifest(tmp_path: Path) -> None:
    settings = make_settings(app_env="production", release_id="r-missing", releases_dir=tmp_path)
    with pytest.raises(RuntimeError, match="no release manifest"):
        load_active_release(settings)


def test_production_needs_a_pinned_kb_version(tmp_path: Path) -> None:
    data = {k: v for k, v in MANIFEST.items() if k != "kb_version"}
    (tmp_path / f"{RELEASE_ID}.yaml").write_text(yaml.safe_dump(data))
    production = make_settings(app_env="production", release_id=RELEASE_ID, releases_dir=tmp_path)
    with pytest.raises(RuntimeError, match="does not pin a kb_version"):
        load_active_release(production)
    # Outside production the configured (or newest ready) KB is used.
    dev = make_settings(release_id=RELEASE_ID, releases_dir=tmp_path)
    assert load_active_release(dev).manifest is not None


def test_production_boots_with_a_complete_manifest(releases_dir: Path) -> None:
    settings = make_settings(app_env="production", release_id=RELEASE_ID, releases_dir=releases_dir)
    release = load_active_release(settings)
    assert release.settings.kb_version == "kb_20261030_01"


def test_unknown_task_override_does_not_boot(tmp_path: Path) -> None:
    data = {**MANIFEST, "models": {"no_such_task": "x"}}
    (tmp_path / f"{RELEASE_ID}.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="unknown task"):
        load_active_release(make_settings(release_id=RELEASE_ID, releases_dir=tmp_path))


async def test_an_unreachable_database_does_not_stop_startup(
    releases_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(*_: Any) -> None:
        raise OperationalError("INSERT", {}, ConnectionRefusedError())

    monkeypatch.setattr(runtime, "upsert_release", down)
    release = load_active_release(make_settings(release_id=RELEASE_ID, releases_dir=releases_dir))
    assert await record_release(None, release) is False  # type: ignore[arg-type]
    no_manifest = ActiveRelease(settings=release.settings, registry=release.registry)
    assert await record_release(None, no_manifest) is False  # type: ignore[arg-type]


def test_the_manifest_can_come_from_the_environment(tmp_path: Path) -> None:
    """Cloud Run passes the manifest in RELEASE_MANIFEST: it belongs to the revision, so
    rolling back traffic rolls the manifest back too (ADR-011)."""
    settings = make_settings(
        app_env="production",
        release_id=RELEASE_ID,
        releases_dir=tmp_path,  # no file there
        release_manifest=json.dumps(MANIFEST),
    )
    release = load_active_release(settings)
    assert release.manifest is not None and release.manifest.id == RELEASE_ID
    assert release.settings.kb_version == "kb_20261030_01"
    assert release.path is None


def test_an_environment_manifest_must_match_release_id(tmp_path: Path) -> None:
    settings = make_settings(
        release_id="r-other", releases_dir=tmp_path, release_manifest=json.dumps(MANIFEST)
    )
    with pytest.raises(ValueError, match="does not match RELEASE_ID"):
        load_active_release(settings)


def test_production_without_a_manifest_needs_an_explicit_kb_version(tmp_path: Path) -> None:
    """Continuous deploys from main have no manifest: they must still pin the KB."""
    settings = make_settings(
        app_env="production",
        release_id="main-abc1234",
        releases_dir=tmp_path,
        kb_version="kb_20261030_01",
        git_sha="abc1234",
    )
    release = load_active_release(settings)
    assert release.manifest is None
    assert release.settings.kb_version == "kb_20261030_01"
    assert release.registry.for_task("nlu").model == "anthropic/claude-haiku-5-5"


async def test_an_unreleased_build_records_its_release_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows: list[dict[str, Any]] = []

    async def fake_upsert_row(engine: Any, release_id: str, values: dict[str, Any]) -> None:
        rows.append({"id": release_id, **values})

    monkeypatch.setattr(runtime, "upsert_row", fake_upsert_row)
    settings = make_settings(
        release_id="main-abc1234", kb_version="kb_20261030_01", git_sha="abc1234"
    )
    assert await record_release(None, load_active_release(settings)) is True  # type: ignore[arg-type]
    assert rows == [
        {
            "id": "main-abc1234",
            "git_sha": "abc1234",
            "kb_version": "kb_20261030_01",
            "models": {},
            "eval_report_uri": None,
        }
    ]
    # Locally there is no image sha, and nothing to record.
    rows.clear()
    assert await record_release(None, load_active_release(make_settings())) is False  # type: ignore[arg-type]
    assert rows == []
