"""What the journey agent's nodes need from the outside world, injected once per agent."""

from dataclasses import dataclass
from typing import Protocol

from homehelper.agent.engine import JourneyCatalog, default_catalog
from homehelper.agent.engine.schema import Journey, Step
from homehelper.agent.state import AgentState, PlanItem
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

    @classmethod
    def default(cls, llm: LLMClient, retriever: Retriever, release_id: str = "dev") -> "AgentDeps":
        return cls(llm=llm, retriever=retriever, catalog=default_catalog(), release_id=release_id)

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
