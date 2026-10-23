"""eval_reports: summaries of eval runs for /admin/evals (M7-04)

Revision ID: a4f1c7e9d2b5
Revises: 8c2d4e6f1b37
Create Date: 2026-10-23 02:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a4f1c7e9d2b5"
down_revision: str | Sequence[str] | None = "8c2d4e6f1b37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "eval_reports",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("release_id", sa.String(length=64), nullable=False),
        sa.Column("suite", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("git_sha", sa.String(length=40), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cases", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_eval_reports_suite_created", "eval_reports", ["suite", "created_at"], unique=False
    )
    op.create_index(
        op.f("ix_eval_reports_release_id"), "eval_reports", ["release_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_eval_reports_release_id"), table_name="eval_reports")
    op.drop_index("ix_eval_reports_suite_created", table_name="eval_reports")
    op.drop_table("eval_reports")
