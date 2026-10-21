"""`service_booking` MCP server: technician slots and bookings (spec §12.1, M5-05).

Slots are generated from each technician's weekly template in `technicians.json` for the next
`HORIZON_DAYS` days (local time, starting tomorrow), so the demo never runs out of dates. A slot id
encodes technician and local start (`tech_dana.20261021T0900`); booking re-derives it, so a
stale or made-up id is rejected. Bookings live in `mock_bookings` (real) or memory (mock).
"""

from datetime import datetime, time, timedelta
from typing import Annotated
from uuid import uuid4
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from homehelper.knowledge.schemas import CategoryId
from homehelper.mcp_servers.common import Clock, mcp_tool, new_server, utc_now
from homehelper.mcp_servers.mock_data import MockData
from homehelper.mcp_servers.schemas import WEEKDAYS, Booking, Slot, Technician
from homehelper.mcp_servers.stores import BookingStore, ProfileStore, SlotTakenError

HORIZON_DAYS = 7

INSTRUCTIONS = "Available technician visit slots near the user, and booking or cancelling a visit."

UserId = Annotated[str, Field(description="The signed-in user's id")]


def technician_slots(tech: Technician, now: datetime, days: int = HORIZON_DAYS) -> list[Slot]:
    tz = ZoneInfo(tech.timezone)
    today = now.astimezone(tz).date()
    slots: list[Slot] = []
    for offset in range(1, days + 1):
        day = today + timedelta(days=offset)
        for hhmm in tech.weekly_slots.get(WEEKDAYS[day.weekday()], []):
            start = datetime.combine(day, time.fromisoformat(hhmm), tzinfo=tz)
            slots.append(
                Slot(
                    slot_id=f"{tech.technician_id}.{start:%Y%m%dT%H%M}",
                    technician_id=tech.technician_id,
                    technician_name=tech.name,
                    company=tech.company,
                    rating=tech.rating,
                    visit_fee_usd=tech.visit_fee_usd,
                    starts_at=start,
                    ends_at=start + timedelta(minutes=tech.slot_minutes),
                )
            )
    return slots


def build_service_booking_server(
    data: MockData, bookings: BookingStore, profiles: ProfileStore, *, clock: Clock = utc_now
) -> FastMCP:
    server = new_server("service_booking", INSTRUCTIONS)
    technicians = {t.technician_id: t for t in data.technicians}

    @mcp_tool(server, title="List technician slots")
    async def list_slots(
        zip_code: Annotated[str, Field(pattern=r"^\d{5}$", description="US ZIP code")],
        category: CategoryId,
        limit: Annotated[int, Field(ge=1, le=20)] = 6,
    ) -> list[Slot]:
        """Open visit slots in the next week from technicians who serve this ZIP and appliance."""
        now = clock()
        candidates = [
            slot
            for tech in data.technicians
            if tech.serves(zip_code, category)
            for slot in technician_slots(tech, now)
        ]
        taken = await bookings.active_slot_ids([s.slot_id for s in candidates])
        free = sorted((s for s in candidates if s.slot_id not in taken), key=lambda s: s.starts_at)
        return free[:limit]

    @mcp_tool(server, title="Book a technician")
    async def book(
        user_id: UserId,
        slot_id: Annotated[str, Field(description="A slot id from list_slots")],
        appliance_id: str,
        issue: Annotated[str, Field(min_length=1, max_length=1000)],
    ) -> Booking:
        """Book a visit (write tool: journey step actions only)."""
        user = data.user(user_id)
        if user is None:
            raise ToolError(f"Unknown user {user_id!r}")
        appliance = await profiles.get_appliance(appliance_id)
        if appliance is None or appliance.user_id != user_id:
            raise ToolError(f"Appliance {appliance_id!r} not found for this user")
        now = clock()
        tech = technicians.get(slot_id.split(".", 1)[0])
        open_slots = {s.slot_id: s for s in technician_slots(tech, now)} if tech else {}
        slot = open_slots.get(slot_id)
        if tech is None or slot is None:
            raise ToolError(f"Slot {slot_id!r} is not available")
        if not tech.serves(user.zip_code, appliance.category):
            raise ToolError("That technician does not serve this appliance at the user's address")
        booking = Booking(
            booking_id=f"bkg_{uuid4().hex[:12]}",
            user_id=user_id,
            appliance_id=appliance_id,
            slot_id=slot_id,
            technician_id=tech.technician_id,
            starts_at=slot.starts_at,
            issue=issue,
            status="booked",
            created_at=now,
        )
        try:
            await bookings.add(booking)
        except SlotTakenError:
            raise ToolError("That slot was just taken; choose another one") from None
        return booking

    @mcp_tool(server, title="Cancel a booking", destructive=True)
    async def cancel(user_id: UserId, booking_id: str) -> Booking:
        """Cancel an upcoming visit (write tool: journey step actions only)."""
        booking = await bookings.get(booking_id)
        if booking is None or booking.user_id != user_id:
            raise ToolError(f"Booking {booking_id!r} not found for this user")
        if booking.status == "cancelled":
            raise ToolError("This booking is already cancelled")
        now = clock()
        if booking.starts_at <= now:
            raise ToolError("Past visits cannot be cancelled")
        cancelled = booking.model_copy(update={"status": "cancelled", "cancelled_at": now})
        await bookings.update(cancelled)
        return cancelled

    return server
