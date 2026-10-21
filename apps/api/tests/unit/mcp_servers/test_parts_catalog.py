import pytest
from mcp.server.fastmcp import FastMCP

from homehelper.mcp_servers.mock_data import MockData
from homehelper.mcp_servers.parts_catalog import build_parts_catalog_server
from tests.unit.mcp_servers.conftest import connect


@pytest.fixture
def server(data: MockData) -> FastMCP:
    return build_parts_catalog_server(data.parts)


async def test_search_by_model_and_symptom_puts_model_specific_parts_first(server: FastMCP) -> None:
    async with connect(server) as client:
        parts = await client.call(
            "search_parts",
            category="washing_machine",
            brand="LG",
            model="WM4000HWA",
            symptom="washer won't drain, OE error",
        )
    ids = [p["part_id"] for p in parts]
    assert ids[:2] == ["prt_lg_drain_pump_filter", "prt_lg_drain_pump"]
    assert all(p["category"] in ("washing_machine", None) for p in parts)


async def test_incompatible_model_and_other_brand_are_excluded(server: FastMCP) -> None:
    async with connect(server) as client:
        samsung = await client.call(
            "search_parts", category="dryer", brand="Samsung", model="DVE45B6300W"
        )
        lg = await client.call("search_parts", category="dryer", brand="LG", model="RH1077AVK")
    assert "prt_samsung_dryer_lint_filter" in {p["part_id"] for p in samsung}
    # Brand-specific Samsung parts don't show for an LG dryer; generic tools still do.
    assert {p["part_id"] for p in lg} == {"prt_dryer_vent_kit"}


async def test_general_tools_need_a_matching_symptom(server: FastMCP) -> None:
    async with connect(server) as client:
        without = await client.call("search_parts", category="refrigerator")
        with_symptom = await client.call(
            "search_parts", category="refrigerator", symptom="fridge not cooling"
        )
    assert "prt_multimeter" not in {p["part_id"] for p in without}
    assert {"prt_fridge_thermometer", "prt_coil_brush"} <= {p["part_id"] for p in with_symptom}


async def test_search_needs_a_filter_and_get_part(server: FastMCP) -> None:
    async with connect(server) as client:
        assert "at least one" in await client.error("search_parts")
        part = await client.call("get_part", part_id="prt_descaler")
        assert part["price_usd"] == 12.99
        assert part["image_url"].startswith("https://")
        assert "Unknown part" in await client.error("get_part", part_id="nope")
