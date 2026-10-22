"""Application tables (Alembic-managed, spec §14.1). KB snapshot tables (`data_kb_*`) belong to
ingestion; `mock_*` tables belong to the MCP servers (M5); the LangGraph checkpointer keeps its own
tables in the `langgraph` schema."""

from datetime import datetime
from typing import Any, Literal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

KBStatus = Literal["building", "ready", "failed", "deleted"]
MessageRole = Literal["user", "assistant", "system"]
FeedbackRating = Literal["up", "down"]
AttachmentKind = Literal["image", "video"]
Verdict = Literal["correct", "incorrect"]


class Base(DeclarativeBase):
    pass


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class KBVersion(Base):
    """One frozen knowledge-base snapshot (spec §10.3). Rows are never edited after `ready`."""

    __tablename__ = "kb_versions"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)  # kb_YYYYMMDD_NN
    manifest_hash: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(100))
    embedding_dim: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="building")
    created_at: Mapped[datetime] = _created_at()


class User(Base):
    """A demo user (id = the mock user id from `data/mock/users.json`) or an anonymous guest."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created_at()


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Not a foreign key: releases are files under `releases/` first and rows only once published.
    release_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(200))
    outcome: Mapped[str | None] = mapped_column(String(16))
    active_journey: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base):
    """The UI and history source of truth (spec §14.1), assembled from the agent's event stream."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="ck_messages_role"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    cards: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    action: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6, asdecimal=False))
    created_at: Mapped[datetime] = _created_at()


class Attachment(Base):
    """An uploaded photo or video (spec §11.1). Owned by its uploader; bound to the conversation
    and user message it was sent with. `analysis` caches what the vision or video model saw."""

    __tablename__ = "attachments"
    __table_args__ = (CheckConstraint("kind IN ('image', 'video')", name="ck_attachments_kind"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    storage_uri: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Numeric(8, 2, asdecimal=False))
    status: Mapped[str] = mapped_column(String(16), default="uploaded")
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()


class Feedback(Base):
    """👍/👎 on an assistant message; one row per message, a second vote replaces the first."""

    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint("rating IN ('up', 'down')", name="ck_feedback_rating"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True
    )
    rating: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class Annotation(Base):
    """A reviewer's verdict on an assistant message (spec §17.2); may become a regression case."""

    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint("verdict IN ('correct', 'incorrect')", name="ck_annotations_verdict"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    verdict: Mapped[str] = mapped_column(String(16))
    issue_types: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    expected_response: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    exported_case_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at()


class Release(Base):
    """An immutable bundle of code, prompts, journeys, models and KB version (spec §17.3)."""

    __tablename__ = "releases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    git_sha: Mapped[str] = mapped_column(String(40))
    kb_version: Mapped[str | None] = mapped_column(String(32))
    models: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    eval_report_uri: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
