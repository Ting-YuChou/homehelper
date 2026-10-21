"""Every MCP tool and whether the LLM may call it (spec §12.1).

This is the single source of truth: servers register tools through `common.mcp_tool`, which reads
the access level from here and stamps it on the tool (MCP `annotations` and `_meta`), so a tool
missing from this table cannot be registered. The agent's MCP client (M5-07) filters on
`LLM_CALLABLE_TOOLS`; write tools run only from journey step actions, in code.
"""

from dataclasses import dataclass
from enum import StrEnum


class ToolAccess(StrEnum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ToolSpec:
    server: str
    name: str
    access: ToolAccess
    # Read tools are LLM-callable unless excluded; web content reaches the LLM only through the
    # knowledge layer's injection guard (spec §10.6), so `web_search.search` is not.
    llm_callable: bool

    @property
    def qualified_name(self) -> str:
        return f"{self.server}.{self.name}"


def _read(server: str, name: str, *, llm_callable: bool = True) -> ToolSpec:
    return ToolSpec(server, name, ToolAccess.READ, llm_callable)


def _write(server: str, name: str) -> ToolSpec:
    return ToolSpec(server, name, ToolAccess.WRITE, llm_callable=False)


TOOLS: tuple[ToolSpec, ...] = (
    _read("user_profile", "get_profile"),
    _read("user_profile", "list_appliances"),
    _read("user_profile", "get_appliance"),
    _write("user_profile", "add_appliance"),
    _read("user_profile", "get_warranty_status"),
    _read("user_profile", "list_repair_history"),
    _write("user_profile", "add_repair_record"),
    _read("parts_catalog", "search_parts"),
    _read("parts_catalog", "get_part"),
    _read("tutorials", "search_videos"),
    _read("service_booking", "list_slots"),
    _write("service_booking", "book"),
    _write("service_booking", "cancel"),
    _read("web_search", "search", llm_callable=False),
)

TOOL_SPECS: dict[str, ToolSpec] = {t.qualified_name: t for t in TOOLS}
SERVER_NAMES: tuple[str, ...] = tuple(dict.fromkeys(t.server for t in TOOLS))
WRITE_TOOLS = frozenset(t.qualified_name for t in TOOLS if t.access is ToolAccess.WRITE)
LLM_CALLABLE_TOOLS = frozenset(t.qualified_name for t in TOOLS if t.llm_callable)

# Key under each tool's `_meta`, so clients that only see the MCP listing can filter too.
META_KEY = "homehelper"


def is_llm_callable(qualified_name: str) -> bool:
    """Fails closed: unknown tools are never exposed to the LLM."""
    return qualified_name in LLM_CALLABLE_TOOLS
