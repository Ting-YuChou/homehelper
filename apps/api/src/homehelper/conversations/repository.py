"""Queries on the application tables. Callers own the session and the transaction."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from homehelper.db.models import Conversation, Feedback, Message, User

TITLE_CHARS = 80


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


async def upsert_user(
    session: AsyncSession, user_id: str, display_name: str, *, is_demo: bool
) -> User:
    stmt = (
        insert(User)
        .values(id=user_id, display_name=display_name, is_demo=is_demo)
        .on_conflict_do_update(index_elements=[User.id], set_={"display_name": display_name})
        .returning(User)
    )
    return (await session.execute(stmt)).scalar_one()


async def get_user(session: AsyncSession, user_id: str) -> User | None:
    return await session.get(User, user_id)


async def create_conversation(
    session: AsyncSession, *, user_id: str, release_id: str, title: str | None = None
) -> Conversation:
    conversation = Conversation(
        id=new_id("conv"), user_id=user_id, release_id=release_id, title=title
    )
    session.add(conversation)
    await session.flush()
    await session.refresh(conversation)
    return conversation


async def list_conversations(
    session: AsyncSession, user_id: str, *, limit: int = 50
) -> Sequence[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.deleted_at.is_(None))
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()


async def get_conversation(
    session: AsyncSession, conversation_id: str, *, user_id: str
) -> Conversation | None:
    """The user's conversation, or None if it doesn't exist, is someone else's, or is deleted."""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
        Conversation.deleted_at.is_(None),
    )
    return (await session.scalars(stmt)).one_or_none()


async def soft_delete_conversation(session: AsyncSession, conversation: Conversation) -> None:
    conversation.deleted_at = utcnow()
    await session.flush()


async def list_messages(session: AsyncSession, conversation_id: str) -> Sequence[Message]:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    )
    return (await session.scalars(stmt)).all()


async def feedback_ratings(session: AsyncSession, message_ids: Sequence[str]) -> dict[str, str]:
    if not message_ids:
        return {}
    stmt = select(Feedback.message_id, Feedback.rating).where(Feedback.message_id.in_(message_ids))
    return {message_id: rating for message_id, rating in (await session.execute(stmt)).all()}


async def add_message(session: AsyncSession, message: Message) -> Message:
    session.add(message)
    await session.flush()
    return message


async def add_cost(session: AsyncSession, message_id: str, cost_usd: float) -> None:
    await session.execute(
        update(Message)
        .where(Message.id == message_id)
        .values(cost_usd=func.coalesce(Message.cost_usd, 0) + cost_usd)
    )


async def finish_turn(
    session: AsyncSession,
    conversation_id: str,
    *,
    outcome: str | None,
    active_journey: str | None,
    first_text: str | None,
) -> None:
    """Record what the turn changed: outcome, journey, a title from the first message."""
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        return
    conversation.outcome = outcome
    conversation.active_journey = active_journey
    if conversation.title is None and first_text:
        conversation.title = first_text[:TITLE_CHARS]
    conversation.updated_at = utcnow()
    await session.flush()


async def get_message_for_user(
    session: AsyncSession, message_id: str, *, user_id: str
) -> Message | None:
    stmt = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.id == message_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
    )
    return (await session.scalars(stmt)).one_or_none()


async def upsert_feedback(
    session: AsyncSession, message_id: str, *, rating: str, reason: str | None
) -> Feedback:
    stmt = (
        insert(Feedback)
        .values(id=new_id("fb"), message_id=message_id, rating=rating, reason=reason)
        .on_conflict_do_update(
            index_elements=[Feedback.message_id],
            set_={"rating": rating, "reason": reason, "created_at": utcnow()},
        )
        .returning(Feedback)
    )
    return (await session.execute(stmt)).scalar_one()
