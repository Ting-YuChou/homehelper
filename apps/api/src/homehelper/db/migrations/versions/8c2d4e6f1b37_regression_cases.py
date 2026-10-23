"""regression_cases: annotations exported as regression cases (M7-02)

Revision ID: 8c2d4e6f1b37
Revises: 3f6b8e2d1a90
Create Date: 2026-10-23 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8c2d4e6f1b37"
down_revision: str | Sequence[str] | None = "3f6b8e2d1a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "regression_cases",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("annotation_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("case", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("media_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("annotation_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("regression_cases")
