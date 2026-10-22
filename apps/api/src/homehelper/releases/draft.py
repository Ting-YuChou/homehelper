"""`homehelper release draft`: a manifest from the eval reports of one release run (M7-03).

The code version and the model overrides come from the reports themselves, so the manifest
describes exactly what was evaluated; reports that disagree, or that come from a weakened run
(no judge, scripted simulator, `--limit`, lenient judge), are refused.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from homehelper.llm.registry import ModelRegistry
from homehelper.releases.gates import Report, weakened_run_error
from homehelper.releases.manifest import Gates, ReleaseManifest, TaskOverride


class DraftError(ValueError):
    pass


def _compact(override: Mapping[str, Any]) -> str | TaskOverride:
    """`{"model": m, "fallbacks": []}` (what `evals run --models` makes of a bare id) -> `m`."""
    if set(override) == {"model", "fallbacks"} and override["fallbacks"] == []:
        return str(override["model"])
    return TaskOverride.model_validate(override)


def draft_manifest(
    release_id: str,
    reports: Mapping[str, tuple[str, Report | None]],
    *,
    gates: Mapping[str, float],
    kb_version: str | None = None,
    image: str | None = None,
) -> ReleaseManifest:
    """`reports` maps a suite to (path as recorded in the manifest, loaded report or None)."""
    if not reports:
        raise DraftError("at least one --report is required")
    shas: dict[str, str] = {}
    overrides: dict[str, dict[str, Any]] = {}
    for suite, (path, report) in reports.items():
        if report is None:
            raise DraftError(f"{suite}: {path} is not a readable conversation-simulation report")
        if report.get("suite") != suite:
            raise DraftError(f"{suite}: {path} is a {report.get('suite')!r} report")
        if report.get("release") != release_id:
            raise DraftError(
                f"{suite}: {path} was run for release {report.get('release')!r}, "
                f"not {release_id!r} (pass --release to evals run)"
            )
        sha = report.get("git_sha")
        if not isinstance(sha, str) or not sha:
            raise DraftError(f"{suite}: {path} has no git_sha")
        if error := weakened_run_error(report):
            raise DraftError(f"{suite}: {path} {error}")
        shas[suite] = sha
        config = report.get("config")
        overrides[suite] = (
            config.get("model_overrides") if isinstance(config, dict) else None
        ) or {}
    if len(set(shas.values())) > 1:
        raise DraftError(f"reports disagree on git_sha: {shas}")
    first, *rest = overrides.values()
    if any(other != first for other in rest):
        raise DraftError(f"reports disagree on model overrides: {overrides}")

    try:
        manifest = ReleaseManifest(
            id=release_id,
            git_sha=next(iter(shas.values())),
            image=image,
            kb_version=kb_version,
            models={task: _compact(value) for task, value in first.items()},
            eval_reports={suite: path for suite, (path, _) in reports.items()},
            gates=Gates.model_validate(gates),
        )
    except ValidationError as exc:
        raise DraftError(str(exc)) from exc
    try:
        ModelRegistry.load(overrides=manifest.model_overrides())
    except (ValueError, ValidationError) as exc:
        raise DraftError(f"models: {exc}") from exc
    return manifest
