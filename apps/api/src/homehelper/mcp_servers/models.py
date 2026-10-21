"""Postgres mock tables behind `user_profile` and `service_booking` in real mode (spec §14.1).

`user_id` is deliberately not a foreign key to the app's `users` table: the mock data platform
stands apart from the application schema, keyed by the demo user ids in `data/mock/users.json`.
"""

import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from homehelper.db.models import Base


class MockAppliance(Base):
    __tablename__ = "mock_appliances"

    appliance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32))
    brand: Mapped[str] = mapped_column(String(64))
    model_number: Mapped[str] = mapped_column(String(64))
    nickname: Mapped[str | None] = mapped_column(String(120))
    purchase_date: Mapped[dt.date | None] = mapped_column(Date)
    warranty_until: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MockRepairRecord(Base):
    __tablename__ = "mock_repair_history"

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    appliance_id: Mapped[str] = mapped_column(
        ForeignKey("mock_appliances.appliance_id", ondelete="CASCADE"), index=True
    )
    date: Mapped[dt.date] = mapped_column(Date)
    issue: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(16))
    resolution: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(32))
    performed_by: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MockBooking(Base):
    __tablename__ = "mock_bookings"
    # A slot can hold only one active booking; cancelled ones free it again.
    __table_args__ = (
        Index(
            "uq_mock_bookings_active_slot",
            "slot_id",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
    )

    booking_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    appliance_id: Mapped[str] = mapped_column(
        ForeignKey("mock_appliances.appliance_id", ondelete="CASCADE")
    )
    slot_id: Mapped[str] = mapped_column(String(96))
    technician_id: Mapped[str] = mapped_column(String(64))
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    issue: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
