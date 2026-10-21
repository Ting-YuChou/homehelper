"""Storage behind `user_profile` and `service_booking`: in memory (mock mode) or Postgres (real).

User profiles are static (`data/mock/users.json`) in both modes; appliances, repair records and
bookings are mutable, so they live in a store.
"""

from collections.abc import Collection
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from homehelper.mcp_servers.mock_data import MockData
from homehelper.mcp_servers.models import MockAppliance, MockBooking, MockRepairRecord
from homehelper.mcp_servers.schemas import Appliance, Booking, RepairRecord


class SlotTakenError(Exception):
    """The slot already has an active booking."""


class ProfileStore(Protocol):
    async def list_appliances(self, user_id: str) -> list[Appliance]:
        """Ordered by `appliance_id`."""
        ...

    async def get_appliance(self, appliance_id: str) -> Appliance | None: ...
    async def add_appliance(self, appliance: Appliance) -> None: ...
    async def list_repairs(self, user_id: str, appliance_id: str | None) -> list[RepairRecord]:
        """Newest first."""
        ...

    async def add_repair(self, record: RepairRecord) -> None: ...


class BookingStore(Protocol):
    async def active_slot_ids(self, slot_ids: Collection[str]) -> set[str]: ...
    async def add(self, booking: Booking) -> None:
        """Raises `SlotTakenError` when the slot already has an active booking."""
        ...

    async def get(self, booking_id: str) -> Booking | None: ...
    async def update(self, booking: Booking) -> None: ...


def _newest_first(records: list[RepairRecord]) -> list[RepairRecord]:
    return sorted(records, key=lambda r: (r.date, r.record_id), reverse=True)


class InMemoryProfileStore:
    def __init__(self, data: MockData) -> None:
        self._appliances = {a.appliance_id: a for a in data.appliances}
        self._repairs = list(data.repair_history)

    async def list_appliances(self, user_id: str) -> list[Appliance]:
        return sorted(
            (a for a in self._appliances.values() if a.user_id == user_id),
            key=lambda a: a.appliance_id,
        )

    async def get_appliance(self, appliance_id: str) -> Appliance | None:
        return self._appliances.get(appliance_id)

    async def add_appliance(self, appliance: Appliance) -> None:
        self._appliances[appliance.appliance_id] = appliance

    async def list_repairs(self, user_id: str, appliance_id: str | None) -> list[RepairRecord]:
        return _newest_first(
            [
                r
                for r in self._repairs
                if r.user_id == user_id and appliance_id in (None, r.appliance_id)
            ]
        )

    async def add_repair(self, record: RepairRecord) -> None:
        self._repairs.append(record)


class InMemoryBookingStore:
    def __init__(self) -> None:
        self._bookings: dict[str, Booking] = {}

    async def active_slot_ids(self, slot_ids: Collection[str]) -> set[str]:
        wanted = set(slot_ids)
        return {
            b.slot_id
            for b in self._bookings.values()
            if b.status == "booked" and b.slot_id in wanted
        }

    async def add(self, booking: Booking) -> None:
        if await self.active_slot_ids([booking.slot_id]):
            raise SlotTakenError(booking.slot_id)
        self._bookings[booking.booking_id] = booking

    async def get(self, booking_id: str) -> Booking | None:
        return self._bookings.get(booking_id)

    async def update(self, booking: Booking) -> None:
        self._bookings[booking.booking_id] = booking


def _appliance_row(a: Appliance) -> MockAppliance:
    return MockAppliance(**a.model_dump(mode="python") | {"category": a.category.value})


def _repair_row(r: RepairRecord) -> MockRepairRecord:
    return MockRepairRecord(**r.model_dump(mode="python"))


def _validate_appliance(row: MockAppliance) -> Appliance:
    return Appliance.model_validate(row, from_attributes=True)


class PostgresProfileStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def list_appliances(self, user_id: str) -> list[Appliance]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(MockAppliance)
                .where(MockAppliance.user_id == user_id)
                .order_by(MockAppliance.appliance_id)
            )
            return [_validate_appliance(row) for row in rows]

    async def get_appliance(self, appliance_id: str) -> Appliance | None:
        async with self._sessions() as session:
            row = await session.get(MockAppliance, appliance_id)
            return _validate_appliance(row) if row else None

    async def add_appliance(self, appliance: Appliance) -> None:
        async with self._sessions.begin() as session:
            session.add(_appliance_row(appliance))

    async def list_repairs(self, user_id: str, appliance_id: str | None) -> list[RepairRecord]:
        query = select(MockRepairRecord).where(MockRepairRecord.user_id == user_id)
        if appliance_id is not None:
            query = query.where(MockRepairRecord.appliance_id == appliance_id)
        async with self._sessions() as session:
            rows = await session.scalars(query)
            return _newest_first(
                [RepairRecord.model_validate(row, from_attributes=True) for row in rows]
            )

    async def add_repair(self, record: RepairRecord) -> None:
        async with self._sessions.begin() as session:
            session.add(_repair_row(record))


class PostgresBookingStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def active_slot_ids(self, slot_ids: Collection[str]) -> set[str]:
        if not slot_ids:
            return set()
        async with self._sessions() as session:
            rows = await session.scalars(
                select(MockBooking.slot_id).where(
                    MockBooking.slot_id.in_(list(slot_ids)), MockBooking.status == "booked"
                )
            )
            return set(rows)

    async def add(self, booking: Booking) -> None:
        try:
            async with self._sessions.begin() as session:
                session.add(MockBooking(**booking.model_dump(mode="python")))
        except IntegrityError as exc:  # uq_mock_bookings_active_slot
            raise SlotTakenError(booking.slot_id) from exc

    async def get(self, booking_id: str) -> Booking | None:
        async with self._sessions() as session:
            row = await session.get(MockBooking, booking_id)
            return Booking.model_validate(row, from_attributes=True) if row else None

    async def update(self, booking: Booking) -> None:
        async with self._sessions.begin() as session:
            await session.merge(MockBooking(**booking.model_dump(mode="python")))


async def seed_mock_tables(engine: AsyncEngine, data: MockData) -> None:
    """Reset the mock tables to `data/mock/` (drops bookings and records added since)."""
    sessions = async_sessionmaker(engine)
    async with sessions.begin() as session:
        for table in (MockBooking, MockRepairRecord, MockAppliance):
            await session.execute(delete(table))
        session.add_all([_appliance_row(a) for a in data.appliances])
        await session.flush()  # appliances first: repair records reference them
        session.add_all([_repair_row(r) for r in data.repair_history])
