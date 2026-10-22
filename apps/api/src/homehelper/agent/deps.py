"""What the journey agent's nodes need from the outside world, injected once per agent."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from homehelper.agent.engine import JourneyCatalog, default_catalog
from homehelper.agent.engine.schema import Journey, Step
from homehelper.agent.state import AgentState, PlanItem
from homehelper.agent.tools import Toolbox
from homehelper.core.tracing import Tracer
from homehelper.knowledge.schemas import RetrievalQuery, RetrievalResult
from homehelper.llm import LLMClient


class Retriever(Protocol):
    """`KnowledgeRetriever.search`, or anything shaped like it."""

    async def search(self, query: RetrievalQuery) -> RetrievalResult: ...


@dataclass(frozen=True)
class AgentDeps:
    llm: LLMClient
    retriever: Retriever
    catalog: JourneyCatalog
    release_id: str = "dev"
    tracer: Tracer | None = None  # Langfuse spans per node (M3-11); None in evals and tests
    tools: Toolbox | None = None  # MCP tools (M5-07); None runs without them

    @classmethod
    def default(
        cls,
        llm: LLMClient,
        retriever: Retriever,
        release_id: str = "dev",
        tracer: Tracer | None = None,
        tools: Toolbox | None = None,
    ) -> "AgentDeps":
        return cls(
            llm=llm,
            retriever=retriever,
            catalog=default_catalog(),
            release_id=release_id,
            tracer=tracer,
            tools=tools,
        )

    @contextmanager
    def span(self, name: str, *, input: Any = None, tags: list[str] | None = None) -> Iterator[Any]:
        """A Langfuse span, or None without a tracer. Update it with `record(span, ...)`."""
        if self.tracer is None:
            yield None
            return
        with self.tracer.span(name, input=input, tags=tags) as span:
            yield span

    def journey(self, state: AgentState) -> Journey | None:
        return self.catalog[state.active_journey] if state.active_journey else None

    def step(self, state: AgentState) -> Step | None:
        journey = self.journey(state)
        if journey is None or state.step_id is None:
            return None
        return journey.step(state.step_id)


def presented_item(state: AgentState) -> PlanItem | None:
    return next((item for item in state.plan if item.status == "presented"), None)


def slot_values(state: AgentState) -> dict[str, str]:
    return {name: slot.value for name, slot in state.slots.items()}


def record(span: Any, **fields: Any) -> None:
    """`span.update(...)` that tolerates a disabled tracer."""
    if span is not None:
        span.update(**fields)
