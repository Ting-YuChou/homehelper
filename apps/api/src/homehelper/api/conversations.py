"""Conversations CRUD and the streaming message endpoint (spec §13.2, §13.3)."""

from collections.abc import AsyncIterator
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from pydantic import RootModel
from redis.exceptions import RedisError

from homehelper.api.deps import SessionDep, SettingsDep, UserDep, client_ip
from homehelper.api.schemas import (
    AttachmentRef,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    MessageOut,
)
from homehelper.channels.events import AgentEvent, ErrorEvent
from homehelper.channels.web import SendMessageRequest, SSEResponse, WebChannelAdapter
from homehelper.conversations import repository
from homehelper.conversations.service import ConversationService
from homehelper.core.logging import get_logger
from homehelper.db.models import Conversation
from homehelper.ratelimit import TurnGuards

router = APIRouter(prefix="/conversations", tags=["conversations"])
log = get_logger(__name__)

ConversationId = Annotated[str, Path(max_length=64)]


class SSEEvent(RootModel[AgentEvent]):
    """One `data:` payload of the message stream; the SSE `event:` name equals its `type`."""


async def _owned(session: SessionDep, conversation_id: str, user_id: str) -> Conversation:
    conversation = await repository.get_conversation(session, conversation_id, user_id=user_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(user: UserDep, session: SessionDep) -> list[ConversationOut]:
    rows = await repository.list_conversations(session, user.id)
    return [ConversationOut.model_validate(row) for row in rows]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate, user: UserDep, session: SessionDep, settings: SettingsDep
) -> ConversationOut:
    conversation = await repository.create_conversation(
        session, user_id=user.id, release_id=settings.release_id, title=body.title
    )
    return ConversationOut.model_validate(conversation)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: ConversationId, user: UserDep, session: SessionDep
) -> ConversationDetail:
    conversation = await _owned(session, conversation_id, user.id)
    rows = await repository.list_messages(session, conversation.id)
    ids = [m.id for m in rows]
    ratings = await repository.feedback_ratings(session, ids)
    attachments = await repository.attachments_by_message(session, ids)
    messages = [
        MessageOut.model_validate(row).model_copy(
            update={
                "feedback": ratings.get(row.id),
                "attachments": [
                    AttachmentRef.model_validate(a) for a in attachments.get(row.id, [])
                ],
            }
        )
        for row in rows
    ]
    summary = ConversationOut.model_validate(conversation)
    return ConversationDetail(**summary.model_dump(), messages=messages)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: ConversationId, user: UserDep, session: SessionDep
) -> Response:
    conversation = await _owned(session, conversation_id, user.id)
    await repository.soft_delete_conversation(session, conversation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


STREAM_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": SSEEvent, "description": "A `text/event-stream` of agent events."},
    409: {"description": "`conversation_busy`: the previous message is still being handled."},
    422: {"description": "`invalid_attachment`: an attachment can't be sent with this message."},
    429: {"description": "`rate_limited` (see `Retry-After`)."},
    503: {"description": "`maintenance` (daily spend cap reached) or `unavailable`."},
}
MAINTENANCE = ErrorEvent(
    code="maintenance",
    message="HomeHelper has reached today's usage limit. Please come back tomorrow.",
)
BUSY = ErrorEvent(
    code="conversation_busy", message="Still working on your previous message. One moment."
)
UNAVAILABLE = ErrorEvent(code="unavailable", message="HomeHelper is busy. Please try again.")


async def _once(event: AgentEvent) -> AsyncIterator[AgentEvent]:
    yield event


def _rate_limited(retry_after_s: int) -> ErrorEvent:
    minutes = max(1, round(retry_after_s / 60))
    return ErrorEvent(
        code="rate_limited",
        message=f"You've sent a lot of messages. Please try again in about {minutes} min.",
    )


@router.post(
    "/{conversation_id}/messages",
    response_class=SSEResponse,
    responses=STREAM_RESPONSES,
)
async def send_message(
    conversation_id: ConversationId,
    body: SendMessageRequest,
    request: Request,
    user: UserDep,
    session: SessionDep,
) -> Response:
    """Stream one turn. Guard failures are a single `error` event with a matching status."""
    conversation = await _owned(session, conversation_id, user.id)
    channel: WebChannelAdapter = request.app.state.web_channel
    service: ConversationService = request.app.state.conversations
    guards: TurnGuards = request.app.state.turn_guards

    def refuse(
        event: ErrorEvent, status_code: int, headers: dict[str, str] | None = None
    ) -> Response:
        log.info("turn_refused", code=event.code, conversation_id=conversation.id)
        return channel.render(_once(event), status_code=status_code, headers=headers)

    if body.attachments:
        problem = await repository.claim_attachments(
            session, body.attachments, user_id=user.id, conversation_id=conversation.id
        )
        if problem is not None:
            return refuse(
                ErrorEvent(code="invalid_attachment", message=problem),
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )

    try:
        if await guards.spend.over_cap():
            return refuse(MAINTENANCE, status.HTTP_503_SERVICE_UNAVAILABLE)
        ip = client_ip(request, request.app.state.settings)
        for limiter, key in (
            (guards.ip_limiter, f"rl:ip:{ip}"),
            (guards.user_limiter, f"rl:user:{user.id}"),
        ):
            decision = await limiter.hit(key)
            if not decision.allowed:
                return refuse(
                    _rate_limited(decision.retry_after_s),
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    {"Retry-After": str(decision.retry_after_s)},
                )
        token = await guards.lock.acquire(conversation.id)
    except RedisError:
        log.exception("turn_guards_unavailable")
        return refuse(UNAVAILABLE, status.HTTP_503_SERVICE_UNAVAILABLE)
    if token is None:
        return refuse(BUSY, status.HTTP_409_CONFLICT)

    async def on_finish(cost_usd: float) -> None:
        try:
            await guards.spend.add(cost_usd)
        finally:
            await guards.lock.release(conversation.id, token)

    inbound = channel.parse_inbound(body, conversation_id=conversation.id, user_id=user.id)
    trace_id = structlog.contextvars.get_contextvars().get("trace_id")
    return channel.render(service.start_turn(inbound, trace_id=trace_id, on_finish=on_finish))
