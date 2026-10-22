"""`GET /v1/me/appliances` reads the `user_profile` MCP server in mock mode (spec §13.2)."""

from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from homehelper.api.deps import current_user
from homehelper.db.models import User
from homehelper.main import create_app
from homehelper.mcp_servers.factory import McpOverrides, build_mcp_servers
from homehelper.mcp_servers.mock_data import load_mock_data
from homehelper.mcp_servers.schemas import Appliance, RepairRecord
from homehelper.mcp_servers.stores import InMemoryProfileStore
from tests.conftest import make_settings
from tests.unit.mcp_servers.conftest import fixed_clock

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture
def store() -> InMemoryProfileStore:
    return InMemoryProfileStore(load_mock_data(REPO / "data" / "mock"))


@pytest.fixture
async def app(store: InMemoryProfileStore) -> AsyncIterator[FastAPI]:
    settings = make_settings(mcp_mode="mock", data_dir=REPO / "data")
    app = create_app(settings)
    # A fixed "today" for the warranty status, and a store the test can add records to.
    app.state.mcp = build_mcp_servers(
        settings,
        engine=app.state.db_engine,
        overrides=McpOverrides(profile_store=store, clock=fixed_clock),
    )
    yield app
    await app.state.redis.aclose()
    await app.state.db_engine.dispose()


async def get_as(app: FastAPI, user: User) -> httpx.Response:
    app.dependency_overrides[current_user] = lambda: user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/v1/me/appliances")


def demo(user_id: str) -> User:
    return User(id=user_id, display_name=user_id, is_demo=True)


async def test_demo_user_gets_appliances_with_warranty_and_repairs(app: FastAPI) -> None:
    response = await get_as(app, demo("demo_alex"))
    assert response.status_code == 200
    by_id = {a["appliance_id"]: a for a in response.json()}
    assert list(by_id) == ["apl_alex_coffee", "apl_alex_dryer", "apl_alex_washer"]

    washer = by_id["apl_alex_washer"]
    assert (washer["brand"], washer["model_number"]) == ("LG", "WM4000HWA")
    assert washer["category"] == "washing_machine"
    assert washer["warranty"] == {
        "status": "expired",
        "warranty_until": "2023-06-04",
        "days_remaining": None,
    }
    assert [r["record_id"] for r in washer["recent_repairs"]] == ["rep_alex_washer_1"]
    assert "user_id" not in washer["recent_repairs"][0]

    dryer = by_id["apl_alex_dryer"]
    assert dryer["warranty"]["status"] == "active"
    assert dryer["warranty"]["days_remaining"] == (date(2027, 2, 10) - fixed_clock().date()).days
    assert dryer["recent_repairs"] == []


async def test_unknown_warranty_for_landlord_owned_appliances(app: FastAPI) -> None:
    by_id = {a["appliance_id"]: a for a in (await get_as(app, demo("demo_sam"))).json()}
    assert by_id["apl_sam_washer"]["warranty"] == {
        "status": "unknown",
        "warranty_until": None,
        "days_remaining": None,
    }


async def test_recent_repairs_are_newest_first_and_capped(
    app: FastAPI, store: InMemoryProfileStore
) -> None:
    for day in (1, 3, 2, 5, 4):
        await store.add_repair(
            RepairRecord(
                record_id=f"rep_test_{day}",
                user_id="demo_alex",
                appliance_id="apl_alex_dryer",
                date=date(2026, 9, day),
                issue="No heat",
                resolution="Cleaned the lint filter",
                outcome="resolved",
                performed_by="self",
            )
        )
    by_id = {a["appliance_id"]: a for a in (await get_as(app, demo("demo_alex"))).json()}
    repairs = by_id["apl_alex_dryer"]["recent_repairs"]
    assert [r["record_id"] for r in repairs] == ["rep_test_5", "rep_test_4", "rep_test_3"]


async def test_guests_get_an_empty_list(app: FastAPI) -> None:
    guest = User(id="guest_abc123", display_name="Guest", is_demo=False)
    response = await get_as(app, guest)
    assert response.status_code == 200
    assert response.json() == []


async def test_unknown_demo_user_gets_an_empty_list(app: FastAPI) -> None:
    response = await get_as(app, demo("demo_nobody"))
    assert response.status_code == 200
    assert response.json() == []


class BrokenStore(InMemoryProfileStore):
    async def list_appliances(self, user_id: str) -> list[Appliance]:
        raise ConnectionError("db down")


async def test_a_failing_data_platform_is_a_503_not_an_empty_list(app: FastAPI) -> None:
    broken = BrokenStore(load_mock_data(REPO / "data" / "mock"))
    app.state.mcp = build_mcp_servers(
        app.state.settings,
        engine=app.state.db_engine,
        overrides=McpOverrides(profile_store=broken, clock=fixed_clock),
    )
    response = await get_as(app, demo("demo_alex"))
    assert response.status_code == 503
