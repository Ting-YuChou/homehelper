"""Admin queries over every user's conversations (spec §17.2). Callers own the transaction.

Unlike `conversations.repository`, nothing here is scoped to one user: these back `/v1/admin`
only, behind `require_admin`. Deleted conversations stay hidden here too.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from homehelper.conversations.repository import new_id
from homehelper.db.models import Annotation, Conversation, Feedback, Message, User

OPEN = "open"  # outcome filter for conversations that have no outcome yet


@dataclass(frozen=True)
class ReviewFilters:
    outcome: str | None = None  # an Outcome, or OPEN for none yet
    feedback: Literal["up", "down"] | None = None
    release_id: str | None = None
    annotated: bool | None = None


@dataclass(frozen=True)
class ReviewRow:
    conversation: Conversation
    user_display_name: str
    user_is_demo: bool
    message_count: int
    up_count: int
    down_count: int
    annotation_count: int
    cost_usd: float


def _review_query(filters: ReviewFilters) -> Select[Any]:
    messages = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count().label("messages"),
            func.coalesce(func.sum(Message.cost_usd), 0).label("cost"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    feedback = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count().filter(Feedback.rating == "up").label("up"),
            func.count().filter(Feedback.rating == "down").label("down"),
        )
        .join(Feedback, Feedback.message_id == Message.id)
        .group_by(Message.conversation_id)
        .subquery()
    )
    annotations = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count(Annotation.id).label("annotations"),
        )
        .join(Annotation, Annotation.message_id == Message.id)
        .group_by(Message.conversation_id)
        .subquery()
    )
    up = func.coalesce(feedback.c.up, 0)
    down = func.coalesce(feedback.c.down, 0)
    annotation_count = func.coalesce(annotations.c.annotations, 0)
    stmt = (
        select(
            Conversation,
            User.display_name,
            User.is_demo,
            func.coalesce(messages.c.messages, 0),
            up,
            down,
            annotation_count,
            func.coalesce(messages.c.cost, 0),
        )
        .join(User, User.id == Conversation.user_id)
        .outerjoin(messages, messages.c.conversation_id == Conversation.id)
        .outerjoin(feedback, feedback.c.conversation_id == Conversation.id)
        .outerjoin(annotations, annotations.c.conversation_id == Conversation.id)
        .where(Conversation.deleted_at.is_(None))
    )
    if filters.outcome == OPEN:
        stmt = stmt.where(Conversation.outcome.is_(None))
    elif filters.outcome is not None:
        stmt = stmt.where(Conversation.outcome == filters.outcome)
    if filters.feedback == "up":
        stmt = stmt.where(up > 0)
    elif filters.feedback == "down":
        stmt = stmt.where(down > 0)
    if filters.release_id is not None:
        stmt = stmt.where(Conversation.release_id == filters.release_id)
    if filters.annotated is True:
        stmt = stmt.where(annotation_count > 0)
    elif filters.annotated is False:
        stmt = stmt.where(annotation_count == 0)
    return stmt


async def review_conversations(
    session: AsyncSession,
    filters: ReviewFilters,
    *,
    limit: int,
    before: tuple[datetime, str] | None = None,
    sample: bool = False,
) -> list[ReviewRow]:
    """Newest first (keyset-paged with `before` = the last row's (updated_at, id)), or a random
    sample of `limit` rows."""
    stmt = _review_query(filters)
    if sample:
        stmt = stmt.order_by(func.random())
    else:
        if before is not None:
            stmt = stmt.where(tuple_(Conversation.updated_at, Conversation.id) < before)
        stmt = stmt.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    rows = (await session.execute(stmt.limit(limit))).all()
    return [
        ReviewRow(
            conversation=row[0],
            user_display_name=row[1],
            user_is_demo=row[2],
            message_count=int(row[3]),
            up_count=int(row[4]),
            down_count=int(row[5]),
            annotation_count=int(row[6]),
            cost_usd=float(row[7]),
        )
        for row in rows
    ]


async def get_conversation(
    session: AsyncSession, conversation_id: str
) -> tuple[Conversation, User] | None:
    stmt = (
        select(Conversation, User)
        .join(User, User.id == Conversation.user_id)
        .where(Conversation.id == conversation_id, Conversation.deleted_at.is_(None))
    )
    row = (await session.execute(stmt)).one_or_none()
    return (row[0], row[1]) if row else None


async def get_message(session: AsyncSession, message_id: str) -> Message | None:
    """A message of a conversation that isn't deleted."""
    stmt = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.id == message_id, Conversation.deleted_at.is_(None))
    )
    return (await session.scalars(stmt)).one_or_none()


async def feedback_by_message(
    session: AsyncSession, message_ids: Sequence[str]
) -> dict[str, Feedback]:
    if not message_ids:
        return {}
    rows = await session.scalars(select(Feedback).where(Feedback.message_id.in_(message_ids)))
    return {row.message_id: row for row in rows}


async def annotations_by_message(
    session: AsyncSession, message_ids: Sequence[str]
) -> dict[str, list[Annotation]]:
    if not message_ids:
        return {}
    stmt = (
        select(Annotation)
        .where(Annotation.message_id.in_(message_ids))
        .order_by(Annotation.created_at, Annotation.id)
    )
    grouped: dict[str, list[Annotation]] = {}
    for annotation in await session.scalars(stmt):
        grouped.setdefault(annotation.message_id, []).append(annotation)
    return grouped


async def add_annotation(
    session: AsyncSession,
    *,
    message_id: str,
    verdict: str,
    issue_types: Sequence[str],
    expected_response: str | None,
    notes: str | None,
) -> Annotation:
    annotation = Annotation(
        id=new_id("ann"),
        message_id=message_id,
        verdict=verdict,
        issue_types=list(issue_types),
        expected_response=expected_response,
        notes=notes,
    )
    session.add(annotation)
    await session.flush()
    await session.refresh(annotation)
    return annotation


async def get_annotation(
    session: AsyncSession, annotation_id: str, *, for_update: bool = False
) -> Annotation | None:
    stmt = select(Annotation).where(Annotation.id == annotation_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).one_or_none()
