"""attachments: owner, message, image size and video duration (M6-01)

Revision ID: 754aaa4cda7d
Revises: 09c3d5a63334
Create Date: 2026-10-22 04:23:56.587798

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "754aaa4cda7d"
down_revision: str | Sequence[str] | None = "09c3d5a63334"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Uploads answered 501 until now, so no row can exist; an ownerless one would be unreachable.
    op.execute("DELETE FROM attachments")
    op.add_column("attachments", sa.Column("user_id", sa.String(length=64), nullable=False))
    op.add_column("attachments", sa.Column("message_id", sa.String(length=64), nullable=True))
    op.add_column("attachments", sa.Column("width", sa.Integer(), nullable=True))
    op.add_column("attachments", sa.Column("height", sa.Integer(), nullable=True))
    op.add_column(
        "attachments",
        sa.Column("duration_s", sa.Numeric(precision=8, scale=2, asdecimal=False), nullable=True),
    )
    op.create_index(op.f("ix_attachments_message_id"), "attachments", ["message_id"], unique=False)
    op.create_index(op.f("ix_attachments_user_id"), "attachments", ["user_id"], unique=False)
    op.create_foreign_key(
        "fk_attachments_user_id", "attachments", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_attachments_message_id",
        "attachments",
        "messages",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_attachments_message_id", "attachments", type_="foreignkey")
    op.drop_constraint("fk_attachments_user_id", "attachments", type_="foreignkey")
    op.drop_index(op.f("ix_attachments_user_id"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_message_id"), table_name="attachments")
    op.drop_column("attachments", "duration_s")
    op.drop_column("attachments", "height")
    op.drop_column("attachments", "width")
    op.drop_column("attachments", "message_id")
    op.drop_column("attachments", "user_id")
