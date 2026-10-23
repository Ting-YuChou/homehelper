"""Eval reports for `/admin/evals` (spec §15.2, §16.4, M7-04).

`evals run --record` and `evals publish` store a summary of each conversation-simulation report:
its metrics, run config and per-case results. Transcripts stay in the JSON file: they are large
and may hold what real users typed.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from homehelper.db.models import EvalReportRow, Release

REPORT_TYPE = "conversation_simulation"  # = homehelper.releases.gates.REPORT_TYPE


class CaseSummary(BaseModel):
    id: str
    kind: str
    successes: int
    trials: int
    failed_checks: dict[str, int] = Field(default_factory=dict)  # check -> failing trials


class EvalReportSummary(BaseModel):
    id: str
    release_id: str
    suite: str
    created_at: datetime
    git_sha: str | None
    config: dict[str, Any]
    metrics: dict[str, Any]
    cases: list[CaseSummary]
    source_uri: str | None


def summarize(
    report: Mapping[str, Any], *, report_id: str, source_uri: str | None
) -> EvalReportSummary:
    """Raises ValueError for anything but a conversation-simulation report."""
    if report.get("report_type") != REPORT_TYPE:
        raise ValueError(f"not a {REPORT_TYPE} report")
    cases = []
    for entry in report.get("cases") or []:
        trials = entry.get("trials") or []
        failed = Counter(name for trial in trials for name in trial.get("failed_checks") or [])
        cases.append(
            CaseSummary(
                id=entry["case"]["id"],
                kind=entry["case"].get("kind", "scenario"),
                successes=int(entry.get("successes", 0)),
                trials=len(trials),
                failed_checks=dict(sorted(failed.items())),
            )
        )
    return EvalReportSummary.model_validate(
        {
            "id": report_id,
            "release_id": report.get("release"),
            "suite": report.get("suite"),
            "created_at": report.get("created_at"),
            "git_sha": report.get("git_sha"),
            "config": report.get("config") or {},
            "metrics": report.get("metrics") or {},
            "cases": cases,
            "source_uri": source_uri,
        }
    )


async def upsert_eval_report(session: AsyncSession, summary: EvalReportSummary) -> None:
    values = summary.model_dump(mode="json")
    values["created_at"] = summary.created_at
    stmt = insert(EvalReportRow).values(**values)
    update: dict[str, Any] = {k: stmt.excluded[k] for k in values if k != "id"}
    update["imported_at"] = func.now()  # onupdate doesn't apply to an upsert
    await session.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=update))


async def list_eval_reports(
    session: AsyncSession,
    *,
    suite: str | None = None,
    release_id: str | None = None,
    limit: int = 500,
) -> Sequence[EvalReportRow]:
    """Newest first."""
    stmt = select(EvalReportRow)
    if suite is not None:
        stmt = stmt.where(EvalReportRow.suite == suite)
    if release_id is not None:
        stmt = stmt.where(EvalReportRow.release_id == release_id)
    stmt = stmt.order_by(EvalReportRow.created_at.desc(), EvalReportRow.id.desc()).limit(limit)
    return (await session.scalars(stmt)).all()


async def get_eval_report(session: AsyncSession, report_id: str) -> EvalReportRow | None:
    return await session.get(EvalReportRow, report_id)


async def kb_versions(session: AsyncSession, release_ids: Sequence[str]) -> dict[str, str | None]:
    """The knowledge base each published release pinned (releases that have a row)."""
    if not release_ids:
        return {}
    rows = await session.execute(
        select(Release.id, Release.kb_version).where(Release.id.in_(set(release_ids)))
    )
    return dict(rows.tuples().all())
