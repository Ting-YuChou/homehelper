"""The release the API runs as (spec §17.3): the manifest named by `RELEASE_ID`, its model
overrides applied to the registry, and a row in the `releases` table.

The manifest comes from `RELEASE_MANIFEST` (Cloud Run: part of the revision, so rolling traffic
back rolls the manifest back too; ADR-011) or else from `releases/<RELEASE_ID>.yaml`. A build
deployed from main without a release has no manifest; in production it must pin `KB_VERSION`.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from homehelper.core.config import Settings
from homehelper.core.logging import get_logger
from homehelper.db.models import Release
from homehelper.llm.registry import ModelRegistry
from homehelper.releases.manifest import (
    GIT_SHA_PATTERN,
    ReleaseManifest,
    load_manifest,
    manifest_path,
)

log = get_logger(__name__)


@dataclass(frozen=True)
class ActiveRelease:
    """`manifest` is None without a manifest (e.g. `dev`, or a build deployed from main);
    `path` is None when there is no manifest file (no manifest, or `RELEASE_MANIFEST`)."""

    settings: Settings  # with the manifest's kb_version applied
    registry: ModelRegistry  # with the manifest's model overrides applied
    manifest: ReleaseManifest | None = None
    path: Path | None = None


def _environment_manifest(settings: Settings) -> ReleaseManifest | None:
    if not settings.release_manifest:
        return None
    data = yaml.safe_load(settings.release_manifest)  # JSON is YAML
    manifest = ReleaseManifest.model_validate(data)
    if manifest.id != settings.release_id:
        raise ValueError(
            f"RELEASE_MANIFEST id {manifest.id!r} does not match RELEASE_ID {settings.release_id!r}"
        )
    return manifest


def load_active_release(settings: Settings) -> ActiveRelease:
    """Raises on an invalid manifest or unknown task override: a bad release must not boot.
    In production the manifest is required and must pin `kb_version`: otherwise the API would
    serve whichever KB is newest, not the one the release was evaluated on."""
    production = settings.app_env == "production"
    manifest = _environment_manifest(settings)
    path = None
    if manifest is None:
        manifest = load_manifest(settings.releases_dir, settings.release_id)
        path = manifest_path(settings.releases_dir, settings.release_id) if manifest else None
    if manifest is None:
        if production and not settings.kb_version:
            raise RuntimeError(
                f"no release manifest for RELEASE_ID={settings.release_id!r} and no KB_VERSION"
            )
        if production:
            log.info(
                "release.unreleased_build", release=settings.release_id, git_sha=settings.git_sha
            )
        return ActiveRelease(settings=settings, registry=ModelRegistry.load())
    if production and not manifest.kb_version:
        raise RuntimeError(f"release {manifest.id!r} does not pin a kb_version")
    registry = ModelRegistry.load(overrides=manifest.model_overrides())
    if manifest.kb_version and manifest.kb_version != settings.kb_version:
        if settings.kb_version:
            log.warning(
                "release.kb_version_overrides_setting",
                configured=settings.kb_version,
                release=manifest.kb_version,
            )
        settings = settings.model_copy(update={"kb_version": manifest.kb_version})
    source = str(path) if path else "RELEASE_MANIFEST"
    log.info("release.loaded", release=manifest.id, git_sha=manifest.git_sha, source=source)
    return ActiveRelease(settings=settings, registry=registry, manifest=manifest, path=path)


async def upsert_row(engine: AsyncEngine, release_id: str, values: dict[str, Any]) -> None:
    statement = insert(Release).values(id=release_id, **values)
    statement = statement.on_conflict_do_update(index_elements=[Release.id], set_=values)
    async with engine.begin() as conn:
        await conn.execute(statement)


async def upsert_release(engine: AsyncEngine, manifest: ReleaseManifest, path: Path | None) -> None:
    # The manifest, which lists the reports; release.yml commits it to `releases/<id>.yaml`.
    uri = path or manifest_path(Path("releases"), manifest.id)
    values = {
        "git_sha": manifest.git_sha,
        "kb_version": manifest.kb_version,
        "models": manifest.model_dump(mode="json", exclude_none=True)["models"],
        "eval_report_uri": str(uri),
    }
    await upsert_row(engine, manifest.id, values)


async def record_release(engine: AsyncEngine, release: ActiveRelease) -> bool:
    """Upsert the `releases` row at startup. The manifest stays the source of truth, so a
    database that is not reachable yet only logs a warning (`/readyz` reports the database).
    A build without a manifest is recorded when the image knows its commit (`GIT_SHA`), so its
    conversations and eval reports still join to a code version and a KB."""
    settings = release.settings
    try:
        if release.manifest is not None:
            await upsert_release(engine, release.manifest, release.path)
        elif GIT_SHA_PATTERN.fullmatch(settings.git_sha):
            values = {
                "git_sha": settings.git_sha,
                "kb_version": settings.kb_version,
                "models": {},
                "eval_report_uri": None,
            }
            await upsert_row(engine, settings.release_id, values)
        else:
            return False
    except (SQLAlchemyError, OSError) as exc:
        log.warning("release.record_failed", release=settings.release_id, error=str(exc))
        return False
    return True
