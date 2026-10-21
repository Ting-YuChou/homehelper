"""Conversations CRUD and the streaming message endpoint (spec §13.2, §13.3)."""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from pydantic import RootModel

from homehelper.api.deps import SessionDep, SettingsDep, UserDep
from homehelper.api.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    MessageOut,
)
from homehelper.channels.events import AgentEvent
from homehelper.channels.web import SendMessageRequest, SSEResponse, WebChannelAdapter
from homehelper.conversations import repository
from homehelper.conversations.service import ConversationService
from homehelper.db.models import Conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])

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
    ratings = await repository.feedback_ratings(session, [m.id for m in rows])
    messages = [
        MessageOut.model_validate(row).model_copy(update={"feedback": ratings.get(row.id)})
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
}


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
    conversation = await _owned(session, conversation_id, user.id)
    channel: WebChannelAdapter = request.app.state.web_channel
    service: ConversationService = request.app.state.conversations
    inbound = channel.parse_inbound(body, conversation_id=conversation.id, user_id=user.id)
    trace_id = structlog.contextvars.get_contextvars().get("trace_id")
    return channel.render(service.start_turn(inbound, trace_id=trace_id))
