"""mock tables for the user_profile and service_booking MCP servers

Revision ID: 5c1e2a9d7b40
Revises: 86d1142fe842
Create Date: 2026-10-21 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c1e2a9d7b40"
# Track D (M4) adds app-table migrations in parallel: whoever merges second re-points this so
# there is exactly one head (`alembic heads`).
down_revision: str | Sequence[str] | None = "86d1142fe842"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "mock_appliances",
        sa.Column("appliance_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("brand", sa.String(length=64), nullable=False),
        sa.Column("model_number", sa.String(length=64), nullable=False),
        sa.Column("nickname", sa.String(length=120), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("warranty_until", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("appliance_id"),
    )
    op.create_index(
        op.f("ix_mock_appliances_user_id"), "mock_appliances", ["user_id"], unique=False
    )
    op.create_table(
        "mock_repair_history",
        sa.Column("record_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("appliance_id", sa.String(length=64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("issue", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=16), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("performed_by", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["appliance_id"], ["mock_appliances.appliance_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("record_id"),
    )
    op.create_index(
        op.f("ix_mock_repair_history_appliance_id"),
        "mock_repair_history",
        ["appliance_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mock_repair_history_user_id"), "mock_repair_history", ["user_id"], unique=False
    )
    op.create_table(
        "mock_bookings",
        sa.Column("booking_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("appliance_id", sa.String(length=64), nullable=False),
        sa.Column("slot_id", sa.String(length=96), nullable=False),
        sa.Column("technician_id", sa.String(length=64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issue", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["appliance_id"], ["mock_appliances.appliance_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("booking_id"),
    )
    op.create_index(op.f("ix_mock_bookings_user_id"), "mock_bookings", ["user_id"], unique=False)
    op.create_index(
        "uq_mock_bookings_active_slot",
        "mock_bookings",
        ["slot_id"],
        unique=True,
        postgresql_where=sa.text("status = 'booked'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("mock_bookings")
    op.drop_table("mock_repair_history")
    op.drop_table("mock_appliances")
