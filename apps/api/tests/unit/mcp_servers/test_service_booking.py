from datetime import datetime, timedelta

import pytest
from mcp.server.fastmcp import FastMCP

from homehelper.mcp_servers.mock_data import MockData
from homehelper.mcp_servers.service_booking import build_service_booking_server
from homehelper.mcp_servers.stores import InMemoryBookingStore, InMemoryProfileStore
from tests.unit.mcp_servers.conftest import NOW, connect


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def server(data: MockData, clock: Clock) -> FastMCP:
    return build_service_booking_server(
        data, InMemoryBookingStore(), InMemoryProfileStore(data), clock=clock
    )


async def test_list_slots_next_week_in_local_time(server: FastMCP) -> None:
    async with connect(server) as client:
        bay = await client.call("list_slots", zip_code="94110", category="washing_machine")
        nyc = await client.call("list_slots", zip_code="10027", category="microwave", limit=2)
        nowhere = await client.call("list_slots", zip_code="60601", category="dryer")
    # Now is Tuesday 10:00 in California; slots start tomorrow, Dana works Thu/Sat/Mon/Tue.
    assert [s["slot_id"] for s in bay[:3]] == [
        "tech_dana.20261022T1000",
        "tech_dana.20261022T1400",
        "tech_dana.20261024T1000",
    ]
    assert bay[0]["starts_at"] == "2026-10-22T10:00:00-07:00"
    assert bay[0]["ends_at"] == "2026-10-22T12:00:00-07:00"
    assert len(bay) == 6
    assert [s["starts_at"] for s in nyc] == [
        "2026-10-21T09:00:00-04:00",
        "2026-10-21T14:00:00-04:00",
    ]
    assert nowhere == []


async def test_book_takes_the_slot_and_cancel_frees_it(server: FastMCP) -> None:
    async with connect(server) as client:
        slot = "tech_dana.20261022T1000"
        booking = await client.call(
            "book",
            user_id="demo_alex",
            slot_id=slot,
            appliance_id="apl_alex_washer",
            issue="Washer won't drain (OE)",
        )
        assert booking["status"] == "booked"
        assert booking["technician_id"] == "tech_dana"
        assert booking["starts_at"] == "2026-10-22T10:00:00-07:00"
        free = await client.call("list_slots", zip_code="94110", category="washing_machine")
        assert slot not in {s["slot_id"] for s in free}
        taken = await client.error(
            "book", user_id="demo_maria", slot_id=slot, appliance_id="apl_maria_washer", issue="x"
        )
        assert "just taken" in taken

        other = await client.error("cancel", user_id="demo_maria", booking_id=booking["booking_id"])
        assert "not found" in other
        cancelled = await client.call(
            "cancel", user_id="demo_alex", booking_id=booking["booking_id"]
        )
        assert cancelled["status"] == "cancelled"
        assert cancelled["cancelled_at"] is not None
        free = await client.call("list_slots", zip_code="94110", category="washing_machine")
        assert slot in {s["slot_id"] for s in free}
        again = await client.error("cancel", user_id="demo_alex", booking_id=booking["booking_id"])
        assert "already cancelled" in again


@pytest.mark.parametrize(
    ("user_id", "slot_id", "appliance_id", "message"),
    [
        ("demo_alex", "tech_dana.20261023T1000", "apl_alex_washer", "not available"),  # Friday
        ("demo_alex", "tech_dana.20261020T0900", "apl_alex_washer", "not available"),  # past
        ("demo_alex", "tech_nobody.20261022T1000", "apl_alex_washer", "not available"),
        ("demo_alex", "tech_dana.20261022T1000", "apl_sam_washer", "not found"),
        ("demo_alex", "tech_dana.20261022T1000", "apl_alex_coffee", "does not serve"),
        ("demo_sam", "tech_dana.20261022T1000", "apl_sam_washer", "does not serve"),  # NYC
        ("nobody", "tech_dana.20261022T1000", "apl_alex_washer", "Unknown user"),
    ],
)
async def test_book_rejects_invalid_requests(
    server: FastMCP, user_id: str, slot_id: str, appliance_id: str, message: str
) -> None:
    async with connect(server) as client:
        error = await client.error(
            "book", user_id=user_id, slot_id=slot_id, appliance_id=appliance_id, issue="x"
        )
    assert message in error


async def test_past_visits_cannot_be_cancelled(server: FastMCP, clock: Clock) -> None:
    async with connect(server) as client:
        booking = await client.call(
            "book",
            user_id="demo_alex",
            slot_id="tech_priya.20261021T1100",
            appliance_id="apl_alex_coffee",
            issue="Brews slowly",
        )
        clock.now = NOW + timedelta(days=2)
        error = await client.error("cancel", user_id="demo_alex", booking_id=booking["booking_id"])
    assert "Past visits" in error
