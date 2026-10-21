"""Write tools are marked consistently everywhere the LLM's tool list could be built from."""

from homehelper.agent.engine.schema import MCP_READ_TOOLS, MCP_WRITE_TOOLS, is_write_tool
from homehelper.db.engine import create_engine
from homehelper.mcp_servers.factory import build_mcp_servers
from homehelper.mcp_servers.registry import (
    LLM_CALLABLE_TOOLS,
    META_KEY,
    TOOL_SPECS,
    WRITE_TOOLS,
    is_llm_callable,
)
from tests.conftest import make_settings


async def test_live_tool_annotations_and_meta_match_the_registry() -> None:
    settings = make_settings(mcp_mode="mock")
    servers = build_mcp_servers(settings, engine=create_engine(settings.database_url))
    seen: set[str] = set()
    for name, server in servers.servers.items():
        for tool in await server.list_tools():
            spec = TOOL_SPECS[f"{name}.{tool.name}"]
            seen.add(spec.qualified_name)
            write = spec.qualified_name in WRITE_TOOLS
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is (not write)
            assert tool.meta == {
                META_KEY: {"access": spec.access.value, "llm_callable": spec.llm_callable}
            }
            assert tool.outputSchema is not None, "every tool returns a typed, structured result"
    assert seen == {q for q, t in TOOL_SPECS.items() if t.server in servers.servers}


def test_registry_agrees_with_the_journey_dsl_tool_lists() -> None:
    assert {f"mcp:{t}" for t in WRITE_TOOLS} == MCP_WRITE_TOOLS
    assert {f"mcp:{t}" for t in LLM_CALLABLE_TOOLS} == MCP_READ_TOOLS
    assert all(is_write_tool(f"mcp:{t}") for t in WRITE_TOOLS)


def test_write_and_unknown_tools_are_never_llm_callable() -> None:
    assert not WRITE_TOOLS & LLM_CALLABLE_TOOLS
    assert not is_llm_callable("service_booking.book")
    assert not is_llm_callable("web_search.search")
    assert not is_llm_callable("user_profile.delete_everything")
    assert is_llm_callable("user_profile.list_appliances")
