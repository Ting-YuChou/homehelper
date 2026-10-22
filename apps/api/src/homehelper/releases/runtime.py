"""The release the API runs as (spec §17.3): the manifest named by `RELEASE_ID`, its model
overrides applied to the registry, and a row in the `releases` table."""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from homehelper.core.config import Settings
from homehelper.core.logging import get_logger
from homehelper.db.models import Release
from homehelper.llm.registry import ModelRegistry
from homehelper.releases.manifest import ReleaseManifest, load_manifest, manifest_path

log = get_logger(__name__)


@dataclass(frozen=True)
class ActiveRelease:
    """`manifest` is None when `releases/<RELEASE_ID>.yaml` does not exist (e.g. `dev`)."""

    settings: Settings  # with the manifest's kb_version applied
    registry: ModelRegistry  # with the manifest's model overrides applied
    manifest: ReleaseManifest | None = None
    path: Path | None = None


def load_active_release(settings: Settings) -> ActiveRelease:
    """Raises on an invalid manifest or unknown task override: a bad release must not boot.
    In production the manifest is required."""
    manifest = load_manifest(settings.releases_dir, settings.release_id)
    if manifest is None:
        if settings.app_env == "production":
            raise RuntimeError(f"no release manifest for RELEASE_ID={settings.release_id!r}")
        return ActiveRelease(settings=settings, registry=ModelRegistry.load())
    registry = ModelRegistry.load(overrides=manifest.model_overrides())
    if manifest.kb_version and manifest.kb_version != settings.kb_version:
        if settings.kb_version:
            log.warning(
                "release.kb_version_overrides_setting",
                configured=settings.kb_version,
                release=manifest.kb_version,
            )
        settings = settings.model_copy(update={"kb_version": manifest.kb_version})
    path = manifest_path(settings.releases_dir, manifest.id)
    log.info("release.loaded", release=manifest.id, git_sha=manifest.git_sha, path=str(path))
    return ActiveRelease(settings=settings, registry=registry, manifest=manifest, path=path)


async def upsert_release(engine: AsyncEngine, manifest: ReleaseManifest, path: Path) -> None:
    values = {
        "git_sha": manifest.git_sha,
        "kb_version": manifest.kb_version,
        "models": manifest.model_dump(mode="json", exclude_none=True)["models"],
        "eval_report_uri": str(path),  # the manifest, which lists the reports
    }
    statement = insert(Release).values(id=manifest.id, **values)
    statement = statement.on_conflict_do_update(index_elements=[Release.id], set_=values)
    async with engine.begin() as conn:
        await conn.execute(statement)


async def record_release(engine: AsyncEngine, release: ActiveRelease) -> bool:
    """Upsert the `releases` row at startup. The manifest file stays the source of truth, so a
    database that is not reachable yet only logs a warning (`/readyz` reports the database)."""
    if release.manifest is None or release.path is None:
        return False
    try:
        await upsert_release(engine, release.manifest, release.path)
    except (SQLAlchemyError, OSError) as exc:
        log.warning("release.record_failed", release=release.manifest.id, error=str(exc))
        return False
    return True
