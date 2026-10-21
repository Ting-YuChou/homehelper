"""Admin API skeleton (spec §13.2, §17.2): conversation review, annotations, eval reports.
Guarded by the `X-Admin-Token` header; the handlers are implemented in M7."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status

from homehelper.api.deps import require_admin
from homehelper.api.schemas import AnnotationCreate

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

NOT_YET = "Admin tools arrive in M7"


@router.get("/conversations", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def review_conversations(
    outcome: str | None = None,
    feedback: Literal["up", "down"] | None = None,
    release_id: str | None = None,
) -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_YET)


@router.post("/annotations", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def annotate(body: AnnotationCreate) -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_YET)


@router.post("/annotations/{annotation_id}/export", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def export_annotation(annotation_id: str) -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_YET)


@router.get("/evals", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def eval_reports() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_YET)
