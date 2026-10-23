"""Photo and video uploads (spec §11.1, M6-01).

`POST /uploads` checks, cleans and stores one file and returns its attachment id; a message then
refers to it. `GET /attachments/{id}` gives the owner a short-lived signed URL. With local
storage that URL is `/media/{token}`: the token alone grants access, like a GCS signed URL, so an
`<img src>` works without the session cookie.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import UploadFile

from homehelper.api.deps import SessionDep, UserDep
from homehelper.api.schemas import AttachmentOut, AttachmentUrlOut, UploadErrorOut
from homehelper.conversations import repository
from homehelper.core.logging import get_logger
from homehelper.db.models import Attachment
from homehelper.media.pipeline import prepare_upload
from homehelper.media.signing import MediaSigner
from homehelper.media.storage import LocalMediaStore, MediaStore, new_key
from homehelper.media.validation import MAX_VIDEO_BYTES, UploadRejected
from homehelper.ratelimit import TurnGuards

router = APIRouter(tags=["uploads"])
log = get_logger(__name__)

FORM_OVERHEAD = 64 * 1024  # multipart boundaries and headers around the file
AttachmentId = Annotated[str, PathParam(max_length=64)]

UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}
UPLOAD_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": UploadErrorOut} for code in (411, 413, 415, 422, 429)
}


def _refuse(code: str, message: str, status_code: int, **headers: str) -> JSONResponse:
    log.info("upload_refused", code=code)
    return JSONResponse({"detail": message, "code": code}, status_code, headers=headers or None)


def _copy(upload: UploadFile, target: Path) -> None:
    upload.file.seek(0)
    with target.open("wb") as out:
        shutil.copyfileobj(upload.file, out)


@router.post(
    "/uploads",
    status_code=status.HTTP_201_CREATED,
    response_model=AttachmentOut,
    responses=UPLOAD_ERRORS,
    openapi_extra=UPLOAD_BODY,
)
async def upload(request: Request, user: UserDep, session: SessionDep) -> Any:
    """Upload one photo or video as the multipart field `file`."""
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        return _refuse("length_required", "Uploads need a Content-Length.", 411)
    if int(length) > MAX_VIDEO_BYTES + FORM_OVERHEAD:
        return _refuse("too_large", "Videos can be up to 100 MB.", 413)
    guards: TurnGuards = request.app.state.turn_guards
    decision = await guards.upload_limiter.hit(f"rl:upload:user:{user.id}")
    if not decision.allowed:
        return _refuse(
            "rate_limited",
            "You've uploaded a lot of files. Please try again later.",
            429,
            **{"Retry-After": str(decision.retry_after_s)},
        )

    store: MediaStore = request.app.state.media_store
    async with request.form(max_files=1, max_fields=1) as form:
        file = form.get("file")
        if not isinstance(file, UploadFile):
            return _refuse("missing_file", "Attach the photo or video as `file`.", 422)
        with tempfile.TemporaryDirectory(prefix="hh-upload-") as tmp:
            work_dir = Path(tmp)
            source = work_dir / "original"
            await asyncio.to_thread(_copy, file, source)
            try:
                prepared = await asyncio.to_thread(prepare_upload, source, work_dir)
            except UploadRejected as rejected:
                return _refuse(rejected.code, rejected.message, rejected.status_code)
            uri = await store.put(new_key(prepared.ext), prepared.path, prepared.mime)

    attachment = await repository.add_attachment(
        session,
        Attachment(
            id=repository.new_id("att"),
            user_id=user.id,
            kind=prepared.kind,
            storage_uri=uri,
            mime=prepared.mime,
            size=prepared.size,
            width=prepared.width,
            height=prepared.height,
            duration_s=prepared.duration_s,
            status="ready",
        ),
    )
    await session.refresh(attachment)
    log.info("upload_stored", attachment_id=attachment.id, kind=prepared.kind, size=prepared.size)
    return AttachmentOut.model_validate(attachment)


@router.get(
    "/attachments/{attachment_id}",
    response_model=AttachmentUrlOut,
    responses={404: {"model": UploadErrorOut}},
)
async def get_attachment(
    attachment_id: AttachmentId, request: Request, user: UserDep, session: SessionDep
) -> AttachmentUrlOut:
    attachment = await repository.get_attachment(session, attachment_id, user_id=user.id)
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    return await signed_attachment(request, attachment)


async def signed_attachment(request: Request, attachment: Attachment) -> AttachmentUrlOut:
    """A short-lived URL for an attachment the caller may see (its owner, or an admin)."""
    store: MediaStore = request.app.state.media_store
    base_url = str(request.url_for("get_media", token="_")).removesuffix("_")
    signed = await store.signed_url(
        attachment.storage_uri, attachment_id=attachment.id, base_url=base_url
    )
    return AttachmentUrlOut(
        id=attachment.id,
        kind=attachment.kind,  # type: ignore[arg-type]
        mime=attachment.mime,
        url=signed.url,
        expires_at=signed.expires_at,
    )


@router.get("/media/{token}", name="get_media", response_class=FileResponse)
async def get_media(token: str, request: Request, session: SessionDep) -> FileResponse:
    """Serve a locally stored upload to whoever holds an unexpired token (no session needed)."""
    signer: MediaSigner = request.app.state.media_signer
    store: MediaStore = request.app.state.media_store
    attachment_id = signer.loads(token)
    attachment = await repository.get_attachment(session, attachment_id) if attachment_id else None
    if attachment is None or not isinstance(store, LocalMediaStore):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(
        store.path(attachment.storage_uri),
        media_type=attachment.mime,
        content_disposition_type="inline",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": f"private, max-age={signer.ttl_s}",
        },
    )
