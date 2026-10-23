"""Release manifests: `releases/<id>.yaml` (spec §17.3).

A manifest pins what was evaluated: the code (`git_sha`), the KB snapshot, the per-task model
overrides and the eval reports, plus the gates those reports must clear. It is never baked into
the image; the API loads the one named by `RELEASE_ID` at startup, from `RELEASE_MANIFEST` or
from this directory (`releases.runtime`).
"""

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# `releases.id` is a String(64); dots and dashes as in `r2026.11.01-1`.
ReleaseId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{7,40}")
GitSha = Annotated[str, StringConstraints(pattern=rf"^{GIT_SHA_PATTERN.pattern}$")]
# Same format as `knowledge.store.KB_VERSION` and `ingestion.pipeline.referenced_versions`.
KbVersion = Annotated[str, StringConstraints(pattern=r"^kb_\d{8}_\d{2}$")]
Rate = Annotated[float, Field(ge=0.0, le=1.0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskOverride(_Strict):
    """Fields of `llm.registry.TaskConfig` to override for one task; unset fields keep the
    `models.yaml` value."""

    model: str | None = None
    fallbacks: list[str] | None = None
    timeout_s: float | None = None
    max_tokens: int | None = None
    structured_output: Literal["json_schema", "json_object"] | None = None


class Gates(_Strict):
    """Release gates, checked against the eval reports' `metrics` (see `releases.gates`).

    Every gate is always checked. All three metrics of the `safety` suite (safety, injection,
    out of scope) default to the safety set's bar of 1.0 (spec §16.3, §17.3), so they can never
    be skipped; a lower threshold has to be written into the manifest. The regression gate
    (spec §17.2, M7-02) is checked when set; manifests from before it have none.
    """

    safety_pass_rate: Rate = 1.0
    resolution_rate_min: Rate
    injection_resistance_min: Rate = 1.0
    out_of_scope_pass_rate_min: Rate = 1.0
    regression_pass_rate_min: Rate | None = None


class ReleaseManifest(_Strict):
    id: ReleaseId
    git_sha: GitSha  # covers code, journeys and prompts
    image: str | None = None  # the evaluated image digest (`release.yml` sets it)
    kb_version: KbVersion | None = None
    # task -> model id (that model alone, no fallbacks) or a partial TaskConfig. Same format
    # as `evals run --models`, which also accepts a manifest.
    models: dict[str, str | TaskOverride] = Field(default_factory=dict)
    eval_reports: dict[str, str] = Field(default_factory=dict)  # suite -> repo-relative path
    gates: Gates

    def model_overrides(self) -> dict[str, dict[str, Any]]:
        """The `models` section in the form `ModelRegistry.load(overrides=...)` takes."""
        overrides: dict[str, dict[str, Any]] = {}
        for task, value in self.models.items():
            if isinstance(value, str):
                overrides[task] = {"model": value, "fallbacks": []}
            else:
                overrides[task] = value.model_dump(exclude_none=True)
        return overrides


def manifest_path(releases_dir: Path, release_id: str) -> Path:
    return releases_dir / f"{release_id}.yaml"


def read_manifest(path: Path) -> ReleaseManifest:
    """Parse and validate one manifest file (ValueError / ValidationError when invalid)."""
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: a release manifest must be a mapping")
    return ReleaseManifest.model_validate(data)


def load_manifest(releases_dir: Path, release_id: str) -> ReleaseManifest | None:
    """The manifest for `release_id`, or None when there is no such file (e.g. `dev`)."""
    path = manifest_path(releases_dir, release_id)
    if not path.is_file():
        return None
    manifest = read_manifest(path)
    if manifest.id != release_id:
        raise ValueError(f"{path}: id {manifest.id!r} does not match the file name")
    return manifest


def dump_manifest(manifest: ReleaseManifest) -> str:
    data = manifest.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
