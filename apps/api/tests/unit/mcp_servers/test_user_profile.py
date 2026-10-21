from datetime import date

import pytest
from mcp.server.fastmcp import FastMCP

from homehelper.mcp_servers.mock_data import MockData
from homehelper.mcp_servers.schemas import Appliance, WarrantyState
from homehelper.mcp_servers.stores import InMemoryProfileStore
from homehelper.mcp_servers.user_profile import build_user_profile_server, warranty_status
from tests.unit.mcp_servers.conftest import connect, fixed_clock


@pytest.fixture
def server(data: MockData) -> FastMCP:
    return build_user_profile_server(data, InMemoryProfileStore(data), clock=fixed_clock)


async def test_get_profile(server: FastMCP) -> None:
    async with connect(server) as client:
        profile = await client.call("get_profile", user_id="demo_sam")
        assert profile["housing"] == "renter"
        assert profile["zip_code"] == "10027"
        assert "Unknown user" in await client.error("get_profile", user_id="nobody")


async def test_list_and_get_appliances(server: FastMCP) -> None:
    async with connect(server) as client:
        appliances = await client.call("list_appliances", user_id="demo_alex")
        assert [a["appliance_id"] for a in appliances] == [
            "apl_alex_coffee",
            "apl_alex_dryer",
            "apl_alex_washer",
        ]
        washer = await client.call(
            "get_appliance", user_id="demo_alex", appliance_id="apl_alex_washer"
        )
        assert washer["brand"] == "LG"
        assert washer["model_number"] == "WM4000HWA"
        assert washer["category"] == "washing_machine"


async def test_other_users_appliances_are_not_found(server: FastMCP) -> None:
    async with connect(server) as client:
        message = await client.error(
            "get_appliance", user_id="demo_sam", appliance_id="apl_alex_washer"
        )
        assert "not found" in message


async def test_add_appliance_then_list(server: FastMCP) -> None:
    async with connect(server) as client:
        added = await client.call(
            "add_appliance",
            user_id="demo_sam",
            category="dishwasher",
            brand="Bosch",
            model_number=" SHE3AR76UC ",
            purchase_date="2026-09-01",
        )
        assert added["appliance_id"].startswith("apl_")
        assert added["model_number"] == "SHE3AR76UC"
        ids = [a["appliance_id"] for a in await client.call("list_appliances", user_id="demo_sam")]
        assert added["appliance_id"] in ids


async def test_add_appliance_rejects_unknown_category(server: FastMCP) -> None:
    async with connect(server) as client:
        await client.error(
            "add_appliance", user_id="demo_sam", category="oven", brand="GE", model_number="X1"
        )


@pytest.mark.parametrize(
    ("appliance_id", "status", "days"),
    [
        ("apl_alex_dryer", "active", 113),
        ("apl_alex_washer", "expired", None),
        ("apl_sam_washer", "unknown", None),
    ],
)
async def test_get_warranty_status(
    server: FastMCP, data: MockData, appliance_id: str, status: str, days: int | None
) -> None:
    async with connect(server) as client:
        owner = next(a.user_id for a in data.appliances if a.appliance_id == appliance_id)
        result = await client.call("get_warranty_status", user_id=owner, appliance_id=appliance_id)
        assert result["status"] == status
        assert result["days_remaining"] == days


def test_warranty_active_through_its_last_day() -> None:
    appliance = Appliance(
        appliance_id="a",
        user_id="u",
        category="dryer",  # type: ignore[arg-type]
        brand="LG",
        model_number="X",
        warranty_until=date(2026, 10, 20),
    )
    status = warranty_status(appliance, date(2026, 10, 20))
    assert status.status is WarrantyState.ACTIVE
    assert status.days_remaining == 0


async def test_repair_history_newest_first_and_filtered(server: FastMCP) -> None:
    async with connect(server) as client:
        records = await client.call("list_repair_history", user_id="demo_jordan")
        assert [r["date"] for r in records] == sorted((r["date"] for r in records), reverse=True)
        dishwasher = await client.call(
            "list_repair_history",
            user_id="demo_jordan",
            appliance_id="apl_jordan_dishwasher",
            limit=1,
        )
        assert [r["record_id"] for r in dishwasher] == ["rep_jordan_dishwasher_2"]


async def test_add_repair_record_defaults_to_today(server: FastMCP) -> None:
    async with connect(server) as client:
        record = await client.call(
            "add_repair_record",
            user_id="demo_alex",
            appliance_id="apl_alex_dryer",
            issue="Clothes still damp",
            resolution="Cleaned the lint filter",
        )
        assert record["date"] == "2026-10-20"
        assert record["outcome"] == "resolved"
        assert record["performed_by"] == "self"
        history = await client.call(
            "list_repair_history", user_id="demo_alex", appliance_id="apl_alex_dryer"
        )
        assert history[0]["record_id"] == record["record_id"]
        await client.error(
            "add_repair_record",
            user_id="demo_alex",
            appliance_id="apl_sam_washer",
            issue="x",
            resolution="y",
        )
