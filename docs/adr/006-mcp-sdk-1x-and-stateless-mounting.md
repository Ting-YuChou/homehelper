# ADR-006: MCP SDK 1.x, stateless mounted servers, and a tool registry

- **Status:** Accepted
- **Date:** 2026-10-21
- **Spec:** §12.1

## Context

ADR-004 chose MCP servers mounted in the API. Implementing them (M5-02..06) raised three questions:

1. The official Python SDK released 2.x in July 2026 (`FastMCP` renamed to `MCPServer`), but `langchain-mcp-adapters` 0.3.2, which the agent uses to load tools (M5-07), requires `mcp<2`. One uv lock serves both the servers and the agent.
2. Cloud Run runs several API instances with no session affinity, and streamable HTTP sessions are per instance by default. Starlette does not run the lifespans of mounted sub-apps, so each server's session manager must be started by the host app.
3. The hard rule that the LLM never calls write tools needs one place that says which tools are writes, which both the servers and the agent can read.

## Decision

- Pin `mcp>=1.30,<2` and use `mcp.server.fastmcp.FastMCP`. Move to 2.x when `langchain-mcp-adapters` supports it.
- Every server is **stateless** with JSON responses (`stateless_http=True`, `json_response=True`), mounted at `/mcp/<server>/`. `McpServers.run()` enters all session managers inside the FastAPI lifespan. Host/Origin (DNS-rebinding) checks are off when mounted, since the API owns that; `homehelper mcp serve` turns them back on for a standalone localhost server. An optional `MCP_AUTH_TOKEN` requires a bearer token on `/mcp/*`.
- `homehelper.mcp_servers.registry` lists every tool with its access level (`read` / `write`) and whether the LLM may call it. Servers register tools only through `mcp_tool()`, which reads the registry (an unregistered tool fails at startup) and stamps it on the MCP `annotations` (`readOnlyHint`) and `_meta.homehelper`. A test keeps the registry equal to the journey DSL's `MCP_READ_TOOLS` / `MCP_WRITE_TOOLS`.

## Consequences

- No server-side session state: any instance can answer any request, and the servers cannot use server-to-client features (sampling, elicitation, notifications). None are needed.
- We stay one major version behind the SDK until the adapter catches up.
- The agent can filter tools by name (registry) or by listing (`_meta`), and both are tested against the same source.

## Alternatives considered

- **mcp 2.x and a hand-written LangChain tool wrapper:** drops `langchain-mcp-adapters`, which spec §12.1 relies on, for little gain.
- **Stateful sessions:** needs sticky sessions or a shared event store on Cloud Run; nothing here benefits from sessions.
- **Write-tool flags only in the journey DSL:** the servers could not mark their tools, and a new write tool could be added without the agent noticing.
