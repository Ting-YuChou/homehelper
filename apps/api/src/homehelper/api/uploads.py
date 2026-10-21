"""Attachment upload and retrieval (spec §11.1). Implemented in M6-01; the routes exist now so the
API surface and the generated client types are complete."""

from fastapi import APIRouter, HTTPException, status

from homehelper.api.deps import UserDep

router = APIRouter(tags=["uploads"])

NOT_YET = "Uploads arrive in M6"


@router.post("/uploads", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def upload(user: UserDep) -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_YET)


@router.get("/attachments/{attachment_id}", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def get_attachment(attachment_id: str, user: UserDep) -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_YET)
