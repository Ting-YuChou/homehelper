"""Builders for journey-engine tests: states, NLU turns, card actions, and a fake `act` node."""

from collections.abc import Sequence

from homehelper.agent.engine import JourneyCatalog, TransitionResult, TurnInput, transition
from homehelper.agent.state import AgentState, NLUResult, PlanItem, SlotUpdate, SlotValue
from homehelper.channels.events import StructuredAction
from homehelper.knowledge.schemas import (
    CategoryId,
    ChunkMetadata,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
)


def new_state(**fields: object) -> AgentState:
    return AgentState.model_validate({"conversation_id": "c1", "release_id": "r1", **fields})


def say(
    intent: str,
    text: str | None = None,
    *,
    slots: dict[str, str] | None = None,
    **nlu: object,
) -> TurnInput:
    updates = [SlotUpdate(name=k, value=v) for k, v in (slots or {}).items()]
    result = NLUResult.model_validate({"intent": intent, "slot_updates": updates, **nlu})
    return TurnInput(text=text, nlu=result)


def press(action_type: str, value: str) -> TurnInput:
    return TurnInput(action=StructuredAction.model_validate({"type": action_type, "value": value}))


def plan(n: int, **overrides: object) -> list[PlanItem]:
    return [
        PlanItem.model_validate(
            {"id": f"p{i}", "instruction": f"Try fix {i}.", "citation_ids": [f"c{i}"], **overrides}
        )
        for i in range(1, n + 1)
    ]


def retrieval(n_chunks: int = 1) -> RetrievalResult:
    chunks = [
        RetrievedChunk(
            chunk_id=f"c{i}",
            text="...",
            score=0.9,
            metadata=ChunkMetadata(
                doc_id="d1", category=CategoryId.DISHWASHER, brand="Bosch", page_start=1, page_end=1
            ),
        )
        for i in range(1, n_chunks + 1)
    ]
    return RetrievalResult(
        query=RetrievalQuery(query_en="q"), source="manual", chunks=chunks, sufficient=bool(chunks)
    )


def vision_slot(value: str, confidence: float = 0.6) -> SlotValue:
    return SlotValue(value=value, source="vision", confidence=confidence)


def fake_act(state: AgentState, actions: Sequence[str], items: list[PlanItem]) -> AgentState:
    """Stand-in for the `act` node: retrieval and plan building only."""
    state = state.model_copy(deep=True)
    if "knowledge.search" in actions:
        state.last_retrieval = retrieval(len(items))
    if "plan.build" in actions:
        state.plan = [item.model_copy() for item in items]
        state.plan_cursor = 0
    return state


def run_turn(
    catalog: JourneyCatalog,
    state: AgentState,
    turn: TurnInput,
    items: list[PlanItem] | None = None,
) -> TransitionResult:
    """One graph turn: transition, then act + continue while a system step is pending."""
    result = transition(catalog, state, turn)
    while result.continue_after_actions:
        acted = fake_act(result.state, result.actions, items or [])
        result = transition(catalog, acted, None)
    return result


# The troubleshoot journey's `diagnose` step actions.
DIAGNOSE_ACTIONS = [
    "mcp:user_profile.get_warranty_status",
    "mcp:user_profile.list_repair_history",
    "knowledge.search",
    "plan.build",
]
