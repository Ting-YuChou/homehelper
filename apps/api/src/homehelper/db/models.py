"""Application tables (Alembic-managed). KB snapshot tables (`data_kb_*`) belong to ingestion."""

from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

KBStatus = Literal["building", "ready", "failed", "deleted"]


class Base(DeclarativeBase):
    pass


class KBVersion(Base):
    """One frozen knowledge-base snapshot (spec §10.3). Rows are never edited after `ready`."""

    __tablename__ = "kb_versions"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)  # kb_YYYYMMDD_NN
    manifest_hash: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(100))
    embedding_dim: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="building")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
