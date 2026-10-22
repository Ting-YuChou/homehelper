"""The agent's MCP client: whitelists, `user_id` binding and failure handling (M5-07)."""

from datetime import UTC, datetime
from pathlib import Path

import anyio

from homehelper.agent.tools import McpToolbox, from_llm_name, llm_name
from homehelper.knowledge.schemas import CategoryId
from homehelper.mcp_servers.factory import McpOverrides, McpServers, build_mcp_servers
from homehelper.mcp_servers.mock_data import load_mock_data
from homehelper.mcp_servers.schemas import Video
from homehelper.mcp_servers.stores import InMemoryBookingStore
from tests.conftest import make_settings

REPO = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 10, 20, 17, 0, tzinfo=UTC)
GUIDE_TOOLS = ["mcp:tutorials.search_videos", "mcp:parts_catalog.search_parts"]
PROFILE_TOOLS = ["mcp:user_profile.list_appliances", "mcp:user_profile.get_warranty_status"]


def servers(bookings: InMemoryBookingStore | None = None) -> McpServers:
    return build_mcp_servers(
        make_settings(mcp_mode="mock"),
        overrides=McpOverrides(
            data=load_mock_data(REPO / "data" / "mock"),
            booking_store=bookings or InMemoryBookingStore(),
            clock=lambda: NOW,
        ),
    )


def test_llm_names_round_trip() -> None:
    assert llm_name("mcp:tutorials.search_videos") == "tutorials__search_videos"
    assert from_llm_name("tutorials__search_videos") == "tutorials.search_videos"


async def test_offers_only_allowed_llm_callable_read_tools() -> None:
    toolbox = McpToolbox(servers())
    allowed = [*GUIDE_TOOLS, "mcp:service_booking.book", "mcp:web_search.search"]
    specs = await toolbox.llm_tools(allowed, user_id="demo_alex")
    assert [s.name for s in specs] == ["tutorials__search_videos", "parts_catalog__search_parts"]
    assert all(s.parameters["type"] == "object" for s in specs)


async def test_user_id_is_hidden_from_the_llm_and_tools_need_a_user() -> None:
    toolbox = McpToolbox(servers())
    signed_in = await toolbox.llm_tools(PROFILE_TOOLS, user_id="demo_alex")
    assert [s.name for s in signed_in] == [
        "user_profile__list_appliances",
        "user_profile__get_warranty_status",
    ]
    for spec in signed_in:
        assert "user_id" not in spec.parameters["properties"]
        assert "user_id" not in spec.parameters.get("required", [])
    assert await toolbox.llm_tools(PROFILE_TOOLS, user_id=None) == []


async def test_llm_supplied_user_id_is_overwritten() -> None:
    toolbox = McpToolbox(servers())
    outcome = await toolbox.call_llm(
        "user_profile__list_appliances",
        {"user_id": "demo_maria"},
        allowed=PROFILE_TOOLS,
        user_id="demo_alex",
    )
    assert outcome.ok
    assert {a["user_id"] for a in outcome.data} == {"demo_alex"}
    assert outcome.arguments == {}  # recorded without user_id


async def test_llm_cannot_call_write_tools_or_tools_not_offered() -> None:
    bookings = InMemoryBookingStore()
    toolbox = McpToolbox(servers(bookings))
    slots = await toolbox.call_action(
        "mcp:service_booking.list_slots",
        {"zip_code": "94110", "category": "washing_machine"},
        user_id=None,
    )
    assert slots.ok and slots.data
    booked = await toolbox.call_llm(
        "service_booking__book",
        {"slot_id": slots.data[0]["slot_id"], "appliance_id": "apl_alex_washer", "issue": "x"},
        allowed=[*GUIDE_TOOLS, "mcp:service_booking.book"],  # even if a YAML listed it
        user_id="demo_alex",
    )
    assert not booked.ok
    assert booked.error == "this tool is not available"
    assert not await bookings.active_slot_ids([slots.data[0]["slot_id"]])
    not_offered = await toolbox.call_llm(
        "parts_catalog__search_parts", {}, allowed=["mcp:tutorials.search_videos"], user_id=None
    )
    assert not not_offered.ok


async def test_actions_may_write_with_the_bound_user() -> None:
    bookings = InMemoryBookingStore()
    toolbox = McpToolbox(servers(bookings))
    slots = await toolbox.call_action(
        "mcp:service_booking.list_slots",
        {"zip_code": "94110", "category": "washing_machine"},
        user_id=None,
    )
    slot_id = slots.data[0]["slot_id"]
    booked = await toolbox.call_action(
        "mcp:service_booking.book",
        {"slot_id": slot_id, "appliance_id": "apl_alex_washer", "issue": "Not draining"},
        user_id="demo_alex",
    )
    assert booked.ok, booked.error
    assert booked.data["user_id"] == "demo_alex"
    assert await bookings.active_slot_ids([slot_id]) == {slot_id}
    guest = await toolbox.call_action(
        "mcp:service_booking.book",
        {"slot_id": slot_id, "appliance_id": "apl_alex_washer", "issue": "x"},
        user_id=None,
    )
    assert (guest.ok, guest.error) == (False, "no signed-in user")


async def test_tool_errors_and_unknown_tools_come_back_as_failed_outcomes() -> None:
    toolbox = McpToolbox(servers())
    unknown_user = await toolbox.call_action(
        "mcp:user_profile.get_profile", {}, user_id="guest_123"
    )
    assert not unknown_user.ok
    assert unknown_user.error
    assert not (await toolbox.call_action("mcp:nope.tool", {}, user_id=None)).ok
    bad_args = await toolbox.call_action(
        "mcp:service_booking.list_slots", {"zip_code": "abc"}, user_id=None
    )
    assert not bad_args.ok


class SlowVideos:
    async def search(
        self, query: str, *, brand: str | None, category: CategoryId | None, max_results: int
    ) -> list[Video]:
        await anyio.sleep(1)
        return []


async def test_timeouts_come_back_as_failed_outcomes() -> None:
    mcp = build_mcp_servers(
        make_settings(mcp_mode="mock"),
        overrides=McpOverrides(
            data=load_mock_data(REPO / "data" / "mock"), video_search=SlowVideos()
        ),
    )
    outcome = await McpToolbox(mcp, timeout_s=0.2).call_action(
        "mcp:tutorials.search_videos", {"query": "drain filter"}, user_id=None
    )
    assert (outcome.ok, outcome.error) == (False, "TimeoutError")
