"""Conversation review and annotations (spec §17.2, M7-01), behind `/admin/review`."""

import base64
import binascii
import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status

from homehelper.api.deps import SessionDep, SettingsDep, require_admin
from homehelper.api.manuals import manual_entries
from homehelper.api.schemas import (
    AdminAttachmentRef,
    AdminConversationDetail,
    AdminConversationPage,
    AdminConversationRow,
    AdminManualOut,
    AdminMessageOut,
    AnnotationCreate,
    AnnotationOut,
    AnnotationUpdate,
    AttachmentUrlOut,
    ConversationOut,
)
from homehelper.api.uploads import signed_attachment
from homehelper.conversations import repository as conversations
from homehelper.core.config import Settings
from homehelper.core.logging import get_logger
from homehelper.db.models import Annotation
from homehelper.quality import repository
from homehelper.quality.repository import OPEN, ReviewFilters

router = APIRouter(dependencies=[Depends(require_admin)])
log = get_logger(__name__)

Id = Annotated[str, Path(max_length=64)]
OutcomeFilter = Literal["resolved", "escalated", "abandoned", "out_of_scope", "open"]


def _cursor(updated_at: datetime, conversation_id: str) -> str:
    raw = json.dumps([updated_at.isoformat(), conversation_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _parse_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        stamp, conversation_id = json.loads(raw)
        return datetime.fromisoformat(stamp), str(conversation_id)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from exc


def _trace_url(settings: Settings, trace_id: str | None) -> str | None:
    if not trace_id or not settings.langfuse_project_id:
        return None
    base = settings.langfuse_base_url.rstrip("/")
    return f"{base}/project/{settings.langfuse_project_id}/traces/{trace_id}"


@router.get("/conversations", response_model=AdminConversationPage)
async def review_conversations(
    session: SessionDep,
    outcome: OutcomeFilter | None = None,
    feedback: Literal["up", "down"] | None = None,
    release_id: Annotated[str | None, Query(max_length=64)] = None,
    annotated: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: Annotated[str | None, Query(max_length=300)] = None,
    sample: Annotated[int | None, Query(ge=1, le=100, description="Random sample size")] = None,
) -> AdminConversationPage:
    """Newest first, `limit` per page; with `sample`, that many random conversations instead."""
    filters = ReviewFilters(
        outcome=OPEN if outcome == "open" else outcome,
        feedback=feedback,
        release_id=release_id,
        annotated=annotated,
    )
    rows = await repository.review_conversations(
        session,
        filters,
        limit=sample or limit,
        before=_parse_cursor(before) if before and not sample else None,
        sample=sample is not None,
    )
    items = [
        AdminConversationRow(
            **ConversationOut.model_validate(row.conversation).model_dump(),
            user_id=row.conversation.user_id,
            user_display_name=row.user_display_name,
            user_is_demo=row.user_is_demo,
            message_count=row.message_count,
            up_count=row.up_count,
            down_count=row.down_count,
            annotation_count=row.annotation_count,
            cost_usd=row.cost_usd,
        )
        for row in rows
    ]
    last = rows[-1].conversation if rows else None
    more = not sample and last is not None and len(rows) == limit
    return AdminConversationPage(
        items=items, next_before=_cursor(last.updated_at, last.id) if more and last else None
    )


@router.get("/conversations/{conversation_id}", response_model=AdminConversationDetail)
async def review_conversation(
    conversation_id: Id, session: SessionDep, settings: SettingsDep
) -> AdminConversationDetail:
    found = await repository.get_conversation(session, conversation_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    conversation, user = found
    rows = await conversations.list_messages(session, conversation.id)
    ids = [m.id for m in rows]
    feedback = await repository.feedback_by_message(session, ids)
    attachments = await conversations.attachments_by_message(session, ids)
    annotations = await repository.annotations_by_message(session, ids)
    messages = []
    for row in rows:
        vote = feedback.get(row.id)
        messages.append(
            AdminMessageOut.model_validate(row).model_copy(
                update={
                    "trace_url": _trace_url(settings, row.trace_id),
                    "feedback": vote.rating if vote else None,
                    "feedback_reason": vote.reason if vote else None,
                    "attachments": [
                        AdminAttachmentRef.model_validate(a) for a in attachments.get(row.id, [])
                    ],
                    "annotations": [
                        AnnotationOut.model_validate(a) for a in annotations.get(row.id, [])
                    ],
                }
            )
        )
    return AdminConversationDetail(
        **ConversationOut.model_validate(conversation).model_dump(),
        user_id=user.id,
        user_display_name=user.display_name,
        user_is_demo=user.is_demo,
        messages=messages,
    )


@router.get("/attachments/{attachment_id}", response_model=AttachmentUrlOut)
async def attachment_url(
    attachment_id: Id, request: Request, session: SessionDep
) -> AttachmentUrlOut:
    attachment = await conversations.get_attachment(session, attachment_id)
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    return await signed_attachment(request, attachment)


@router.get("/manuals", response_model=list[AdminManualOut])
async def list_manuals(settings: SettingsDep) -> list[AdminManualOut]:
    """Every manual in the manifest, to pick the one a reply should have cited."""
    entries = sorted(manual_entries(settings.manuals_dir).values(), key=lambda e: e.doc_id)
    return [
        AdminManualOut(doc_id=e.doc_id, title=e.title, brand=e.brand, category=e.category)
        for e in entries
    ]


@router.post("/annotations", response_model=AnnotationOut, status_code=status.HTTP_201_CREATED)
async def annotate(body: AnnotationCreate, session: SessionDep) -> AnnotationOut:
    message = await repository.get_message(session, body.message_id)
    if message is None or message.role != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assistant message not found")
    annotation = await repository.add_annotation(
        session,
        message_id=message.id,
        verdict=body.verdict,
        issue_types=body.issue_types,
        expected_response=body.expected_response,
        notes=body.notes,
    )
    log.info(
        "admin_annotation_created",
        annotation_id=annotation.id,
        message_id=message.id,
        verdict=body.verdict,
        issue_types=body.issue_types,
    )
    return AnnotationOut.model_validate(annotation)


async def _editable(session: SessionDep, annotation_id: str) -> Annotation:
    annotation = await repository.get_annotation(session, annotation_id, for_update=True)
    if annotation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found")
    if annotation.exported_case_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Exported annotations can't change; edit the case instead"
        )
    return annotation


@router.put(
    "/annotations/{annotation_id}", response_model=AnnotationOut, responses={409: {}, 404: {}}
)
async def update_annotation(
    annotation_id: Id, body: AnnotationUpdate, session: SessionDep
) -> AnnotationOut:
    annotation = await _editable(session, annotation_id)
    annotation.verdict = body.verdict
    annotation.issue_types = list(body.issue_types)
    annotation.expected_response = body.expected_response
    annotation.notes = body.notes
    await session.flush()
    await session.refresh(annotation)
    log.info("admin_annotation_updated", annotation_id=annotation.id)
    return AnnotationOut.model_validate(annotation)


@router.delete(
    "/annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {}, 404: {}},
)
async def delete_annotation(annotation_id: Id, session: SessionDep) -> Response:
    annotation = await _editable(session, annotation_id)
    await session.delete(annotation)
    await session.flush()
    log.info("admin_annotation_deleted", annotation_id=annotation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
