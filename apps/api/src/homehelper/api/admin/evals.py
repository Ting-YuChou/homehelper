"""Eval reports for `/admin/evals` (spec §15.2, M7-04): per-release trends of the suites."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from homehelper.api.deps import SessionDep, require_admin
from homehelper.api.schemas import EvalMetricsOut, EvalReportDetail, EvalReportOut
from homehelper.db.models import EvalReportRow
from homehelper.quality import eval_reports
from homehelper.quality.eval_reports import CaseSummary
from homehelper.releases.gates import weakened_run_error

router = APIRouter(prefix="/evals", dependencies=[Depends(require_admin)])


def _out(row: EvalReportRow, kb_version: str | None) -> EvalReportOut:
    return EvalReportOut(
        id=row.id,
        release_id=row.release_id,
        suite=row.suite,
        created_at=row.created_at,
        git_sha=row.git_sha,
        kb_version=kb_version,
        config=row.config,
        metrics=EvalMetricsOut.model_validate(row.metrics),
        weakened=weakened_run_error({"config": row.config}),
    )


@router.get("", response_model=list[EvalReportOut])
async def list_reports(
    session: SessionDep,
    suite: Annotated[str | None, Query(max_length=32)] = None,
    release_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> list[EvalReportOut]:
    """Newest first, without per-case results."""
    rows = await eval_reports.list_eval_reports(
        session, suite=suite, release_id=release_id, limit=limit
    )
    kb = await eval_reports.kb_versions(session, [r.release_id for r in rows])
    return [_out(row, kb.get(row.release_id)) for row in rows]


@router.get("/{report_id}", response_model=EvalReportDetail, responses={404: {}})
async def get_report(
    report_id: Annotated[str, Path(max_length=160)], session: SessionDep
) -> EvalReportDetail:
    row = await eval_reports.get_eval_report(session, report_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    kb = await eval_reports.kb_versions(session, [row.release_id])
    summary = _out(row, kb.get(row.release_id))
    cases = [CaseSummary.model_validate(c) for c in row.cases]
    return EvalReportDetail(**summary.model_dump(), cases=cases)
