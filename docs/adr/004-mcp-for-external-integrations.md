# ADR-004: MCP for external integrations

- **Status:** Accepted
- **Date:** 2026-10-21
- **Spec:** §12

## Context

The agent needs user profile and appliance data, a parts catalog, tutorial videos, technician booking, and whitelisted web search. None of these are real B2B systems in this project. v1 scraped Amazon and YouTube pages, which violates their terms and breaks when layouts change. Evals need deterministic, inspectable tool behavior.

## Decision

- Each integration is an **MCP server** built with the official Python SDK (FastMCP): `user_profile`, `parts_catalog`, `tutorials`, `service_booking`, `web_search`. Each has a `real | mock` mode; evals always use mock mode and assert on recorded tool calls.
- The agent loads tools with `langchain-mcp-adapters` and exposes only the current step's `tools_allowed`, which contains **read-only** tools.
- **Write tools** (`book`, `add_*`) are called only by code in step actions (for example, after the user picks a slot on a booking card), never by the LLM.
- Servers are mounted as streamable-HTTP ASGI sub-apps inside the API service, both locally and on Cloud Run, so there is one code path. A server can still be run on its own for debugging.

## Consequences

- One standard interface for all integrations, swappable between mock and real without agent changes.
- Tool allowlists per step plus no LLM-callable writes sharply limit the damage of a prompt injection.
- MCP adds protocol overhead compared to calling Python functions directly; mounting in-process keeps latency low.

## Alternatives considered

- **Plain Python functions as LangChain tools:** simpler, but the integrations would not be reusable outside this agent and there would be no standard boundary for mocking.
- **Separate Cloud Run service per MCP server:** cleaner isolation, but more services, more cold starts, and more cost for a portfolio deployment.
