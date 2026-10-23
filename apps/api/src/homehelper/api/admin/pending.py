"""Admin routes still to come in M7 (regression export, eval reports)."""

from fastapi import APIRouter, Depends, HTTPException, status

from homehelper.api.deps import require_admin

router = APIRouter(dependencies=[Depends(require_admin)])

NOT_YET = "Not implemented yet"


@router.post("/annotations/{annotation_id}/export", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def export_annotation(annotation_id: str) -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_YET)


@router.get("/evals", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def eval_reports() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_YET)
