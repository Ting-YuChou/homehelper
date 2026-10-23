"""annotations: updated_at, for edits made before an annotation is exported (M7-01)

Revision ID: 3f6b8e2d1a90
Revises: 754aaa4cda7d
Create Date: 2026-10-22 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f6b8e2d1a90"
down_revision: str | Sequence[str] | None = "754aaa4cda7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "annotations",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("annotations", "updated_at")
