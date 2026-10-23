"""Eval reports into the database for `/admin/evals` (spec §16.4, M7-04).

`evals run --record` publishes the report it wrote; `evals publish <files or folders>` publishes
earlier ones (the JSON files are git-ignored and not in the image). Re-publishing a report
updates its row.
"""

import json
from collections.abc import Sequence
from pathlib import Path

from homehelper.core.config import Settings
from homehelper.db.engine import create_engine, create_sessionmaker
from homehelper.quality.eval_reports import summarize, upsert_eval_report
from homehelper_evals import REPO_ROOT


def _source_uri(path: Path) -> str:
    resolved = path.resolve()
    return str(resolved.relative_to(REPO_ROOT)) if resolved.is_relative_to(REPO_ROOT) else str(path)


async def publish_reports(
    settings: Settings, paths: Sequence[Path]
) -> tuple[list[str], list[Path]]:
    """(published report ids, skipped files: not conversation-simulation reports)."""
    files = [f for p in paths for f in (sorted(p.glob("*.json")) if p.is_dir() else [p])]
    summaries, skipped = [], []
    for file in files:
        try:
            summaries.append(
                summarize(
                    json.loads(file.read_text()), report_id=file.stem, source_uri=_source_uri(file)
                )
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            skipped.append(file)
    engine = create_engine(settings.database_url)
    try:
        async with create_sessionmaker(engine).begin() as session:
            for summary in summaries:
                await upsert_eval_report(session, summary)
    finally:
        await engine.dispose()
    return [s.id for s in summaries], skipped
