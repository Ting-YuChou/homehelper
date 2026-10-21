"""MCP servers in real mode: mounted in the API, backed by the Postgres mock tables."""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from homehelper.core.config import Settings
from homehelper.db.engine import create_engine
from homehelper.mcp_servers.mock_data import load_mock_data
from homehelper.mcp_servers.registry import TOOLS
from homehelper.mcp_servers.stores import seed_mock_tables
from tests.conftest import make_settings
from tests.unit.mcp_servers.test_mounting import mcp_session, running

pytestmark = pytest.mark.integration

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
REPO = Path(__file__).resolve().parents[4]


@pytest.fixture
async def settings() -> Settings:
    settings = make_settings(
        mcp_mode="real",
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql+asyncpg://homehelper:homehelper@localhost:5432/homehelper"
        ),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    )
    # env.py runs its own event loop, so drive Alembic from a worker thread.
    await asyncio.to_thread(command.upgrade, Config(str(ALEMBIC_INI)), "head")
    engine = create_engine(settings.database_url)
    await seed_mock_tables(engine, load_mock_data(REPO / "data" / "mock"))
    await engine.dispose()
    return settings


async def test_mounted_servers_list_tools(settings: Settings) -> None:
    async with running(settings) as app:
        for server in app.state.mcp.servers:
            async with mcp_session(app, server) as session:
                listed = {t.name for t in (await session.list_tools()).tools}
            assert listed == {t.name for t in TOOLS if t.server == server}


async def test_user_profile_reads_and_writes_postgres(settings: Settings) -> None:
    async with running(settings) as app, mcp_session(app, "user_profile") as session:
        listed = await session.call_tool("list_appliances", {"user_id": "demo_alex"})
        assert listed.structuredContent is not None
        ids = [a["appliance_id"] for a in listed.structuredContent["result"]]
        assert ids == ["apl_alex_coffee", "apl_alex_dryer", "apl_alex_washer"]

        added = await session.call_tool(
            "add_repair_record",
            {
                "user_id": "demo_alex",
                "appliance_id": "apl_alex_washer",
                "issue": "OE error again",
                "resolution": "Cleaned the drain pump filter",
            },
        )
        assert not added.isError, added.content
        history = await session.call_tool(
            "list_repair_history", {"user_id": "demo_alex", "appliance_id": "apl_alex_washer"}
        )
        assert history.structuredContent is not None
        records = history.structuredContent["result"]
        assert [r["issue"] for r in records] == [
            "OE error again",
            "Washer would not drain and showed the OE error code.",
        ]


async def test_service_booking_round_trip_on_postgres(settings: Settings) -> None:
    async with running(settings) as app, mcp_session(app, "service_booking") as session:
        slots = await session.call_tool(
            "list_slots", {"zip_code": "94110", "category": "washing_machine"}
        )
        assert slots.structuredContent is not None
        slot_id = slots.structuredContent["result"][0]["slot_id"]
        args = {"user_id": "demo_alex", "slot_id": slot_id, "appliance_id": "apl_alex_washer"}

        booked = await session.call_tool("book", {**args, "issue": "Won't drain"})
        assert booked.structuredContent is not None, booked.content
        twice = await session.call_tool("book", {**args, "issue": "Again"})
        assert twice.isError  # uq_mock_bookings_active_slot

        booking_id = booked.structuredContent["booking_id"]
        cancelled = await session.call_tool(
            "cancel", {"user_id": "demo_alex", "booking_id": booking_id}
        )
        assert cancelled.structuredContent is not None, cancelled.content
        assert cancelled.structuredContent["status"] == "cancelled"
        rebooked = await session.call_tool("book", {**args, "issue": "Rebook"})
        assert not rebooked.isError, rebooked.content
