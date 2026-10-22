"""In-process MCP calls (`McpServers.client` / `call`): unwrapped results and tool errors."""

import pytest

from homehelper.db.engine import create_engine
from homehelper.mcp_servers.client import McpToolError, unwrap_structured
from homehelper.mcp_servers.factory import McpServers, build_mcp_servers
from homehelper.mcp_servers.schemas import Appliance, UserProfile
from tests.conftest import make_settings


@pytest.fixture
async def servers() -> McpServers:
    settings = make_settings(mcp_mode="mock")
    return build_mcp_servers(settings, engine=create_engine(settings.database_url))


async def test_call_returns_plain_data_and_unwraps_lists(servers: McpServers) -> None:
    profile = await servers.call("user_profile", "get_profile", {"user_id": "demo_alex"})
    assert profile["display_name"] == "Alex Kim"
    listed = await servers.call("user_profile", "list_appliances", {"user_id": "demo_alex"})
    assert isinstance(listed, list) and listed[0]["appliance_id"] == "apl_alex_coffee"


async def test_call_as_validates_into_the_record_types(servers: McpServers) -> None:
    async with servers.client("user_profile") as client:
        profile = await client.call_as(UserProfile, "get_profile", {"user_id": "demo_sam"})
        appliances = await client.call_as(
            list[Appliance], "list_appliances", {"user_id": "demo_sam"}
        )
    assert profile.housing == "renter"
    assert all(isinstance(a, Appliance) for a in appliances)


async def test_tool_errors_raise_mcp_tool_error(servers: McpServers) -> None:
    with pytest.raises(McpToolError, match="Unknown user") as raised:
        await servers.call("user_profile", "get_profile", {"user_id": "nobody"})
    assert (raised.value.server, raised.value.tool) == ("user_profile", "get_profile")
    with pytest.raises(McpToolError):  # argument validation fails inside the server
        await servers.call(
            "user_profile", "list_repair_history", {"user_id": "demo_alex", "limit": 0}
        )


def test_unwrap_structured() -> None:
    assert unwrap_structured({"result": [1, 2]}) == [1, 2]
    assert unwrap_structured({"result": 1, "other": 2}) == {"result": 1, "other": 2}


async def test_errors_in_the_session_body_are_not_wrapped(servers: McpServers) -> None:
    with pytest.raises(McpToolError):
        async with servers.client("user_profile") as client:
            await client.call("get_appliance", {"user_id": "demo_alex", "appliance_id": "nope"})
    with pytest.raises(KeyError):
        async with servers.client("user_profile"):
            raise KeyError("mine")
