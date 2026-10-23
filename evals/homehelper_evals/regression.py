"""`evals regression pull` (spec §17.2, M7-02): exported regression cases, from the database into
`evals/datasets/regression/<id>.yaml`, with their photos and videos under `data/media/`.

The API stores a case when a reviewer exports an annotation; it can't write into the repository.
Pulling is idempotent, and never overwrites a case file someone edited unless forced.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

from homehelper.api.deps import session_secret
from homehelper.core.config import Settings
from homehelper.db.engine import create_engine, create_sessionmaker
from homehelper.db.models import Attachment
from homehelper.media.signing import MediaSigner
from homehelper.media.storage import build_media_store
from homehelper.quality import repository
from homehelper.quality.regression import RegressionCase, case_yaml
from homehelper_evals import DATASETS_DIR
from homehelper_evals.cases import REGRESSION_DIR, EvalCase
from homehelper_evals.media import MEDIA_ROOT


@dataclass
class PullSummary:
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)  # edited here; kept (use --force)
    missing_media: list[str] = field(default_factory=list)  # paths whose upload is gone


async def pull(
    settings: Settings,
    *,
    datasets_dir: Path = DATASETS_DIR,
    media_root: Path = MEDIA_ROOT,
    force: bool = False,
) -> PullSummary:
    summary = PullSummary()
    folder = datasets_dir / REGRESSION_DIR
    folder.mkdir(parents=True, exist_ok=True)
    store = build_media_store(
        settings, MediaSigner(session_secret(settings), ttl_s=settings.media_url_ttl_s)
    )
    engine = create_engine(settings.database_url)
    try:
        async with create_sessionmaker(engine)() as session:
            rows = await repository.list_regression_cases(session)
            for row in rows:
                case = RegressionCase.model_validate(row.case)
                EvalCase.model_validate(row.case)  # the runner must be able to load it
                target = folder / f"{case.id}.yaml"
                text = case_yaml(case)
                if target.exists() and target.read_text() == text:
                    summary.unchanged.append(case.id)
                elif target.exists() and not force:
                    summary.conflicts.append(case.id)
                else:
                    target.write_text(text)
                    summary.written.append(case.id)
                for path, attachment_id in row.media_sources.items():
                    destination = media_root / path
                    if destination.exists() and not force:
                        continue
                    attachment = await session.get(Attachment, attachment_id)
                    try:
                        data = await store.read(attachment.storage_uri) if attachment else None
                    except OSError:
                        data = None
                    if data is None:
                        summary.missing_media.append(path)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
    finally:
        await engine.dispose()
    return summary


def report(summary: PullSummary) -> int:
    for label, ids in (
        ("written", summary.written),
        ("unchanged", summary.unchanged),
        ("kept local edits (use --force to overwrite)", summary.conflicts),
        ("media no longer stored", summary.missing_media),
    ):
        if ids:
            print(f"{label}: {', '.join(ids)}", file=sys.stderr)
    total = len(summary.written) + len(summary.unchanged) + len(summary.conflicts)
    print(f"{total} regression cases; {len(summary.written)} written")
    return 0
