"""Building the journey agent for the API (`AGENT_RUNTIME=journey`).

The agent needs the database (KB version, checkpointer pool), so it is built in the app's
lifespan. `DeferredAgent` stands in for it until then, because the conversation service is
wired when the app is created.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine

from homehelper.agent.checkpoint import postgres_checkpointer
from homehelper.agent.deps import AgentDeps
from homehelper.agent.protocol import AgentRuntime, AgentSnapshot
from homehelper.agent.runtime import JourneyAgent
from homehelper.agent.tools import McpToolbox
from homehelper.channels.events import AgentEvent, InboundMessage
from homehelper.core.config import Settings
from homehelper.core.tracing import Tracer
from homehelper.knowledge.backends import build_retriever
from homehelper.knowledge.retriever import ResultCache
from homehelper.knowledge.web import build_web_fallback
from homehelper.llm import ModelRegistry, build_llm_client
from homehelper.mcp_servers.factory import McpServers


class DeferredAgent:
    """An `AgentRuntime` that delegates to an agent attached later (at app startup)."""

    def __init__(self) -> None:
        self._agent: AgentRuntime | None = None

    def attach(self, agent: AgentRuntime | None) -> None:
        self._agent = agent

    def _require(self) -> AgentRuntime:
        if self._agent is None:
            raise RuntimeError("the agent is not ready: the app lifespan has not started it")
        return self._agent

    def handle(self, message: InboundMessage) -> AsyncIterator[AgentEvent]:
        return self._require().handle(message)

    async def snapshot(self, conversation_id: str) -> AgentSnapshot:
        return await self._require().snapshot(conversation_id)


@asynccontextmanager
async def journey_agent(
    settings: Settings,
    engine: AsyncEngine,
    *,
    tracer: Tracer | None = None,
    cache: ResultCache | None = None,
    registry: ModelRegistry | None = None,
    mcp: McpServers | None = None,
) -> AsyncIterator[JourneyAgent]:
    """`registry` is the release's model mapping (`app.state.model_registry`, M7-03); without it
    both the LLM client and the retriever use plain `models.yaml`."""
    llm = build_llm_client(settings, tracer=tracer, registry=registry)
    retriever, backend = await build_retriever(
        settings, engine, cache=cache, web=build_web_fallback(settings, llm), registry=registry
    )
    try:
        async with postgres_checkpointer(settings.database_url) as checkpointer:
            tools = McpToolbox(mcp) if mcp is not None else None
            deps = AgentDeps.default(
                llm, retriever, settings.release_id, tracer=tracer, tools=tools
            )
            yield JourneyAgent(deps, checkpointer)
    finally:
        await backend.close()
