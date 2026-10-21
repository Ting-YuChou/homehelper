"""`understand` (M3-03): structured NLU for free text. Card buttons skip it (spec §7.3)."""

from homehelper.agent import prompts
from homehelper.agent.deps import AgentDeps, presented_item, slot_values
from homehelper.agent.state import NLUResult
from homehelper.agent.turn import MAX_TRANSCRIPT_LINES, GraphState
from homehelper.knowledge.schemas import CategoryId
from homehelper.llm import Message

CATEGORIES = [category.value for category in CategoryId]
# Intents whose search query describes the user's problem or question (kept across turns).
QUERY_INTENTS = frozenset({"report_problem", "ask_how_to"})


def nlu_messages(state: GraphState, deps: AgentDeps, user_text: str) -> list[Message]:
    agent = state.state
    step = deps.step(agent)
    item = presented_item(agent)
    prompt = prompts.render(
        "nlu",
        journey=agent.active_journey,
        step=step.id if step else None,
        step_goal=step.goal if step else None,
        slots=slot_values(agent),
        presented_step=item.instruction if item else None,
        categories=CATEGORIES,
        transcript=state.transcript[-MAX_TRANSCRIPT_LINES:],
        user_text=user_text,
    )
    return [Message(role="user", content=prompt)]


async def understand(state: GraphState, deps: AgentDeps) -> dict[str, object]:
    message = state.turn.message
    assert message is not None
    if message.action is not None or not (message.text or "").strip():
        return {}
    nlu = await deps.llm.structured("nlu", nlu_messages(state, deps, message.text or ""), NLUResult)
    update: dict[str, object] = {"turn": state.turn.model_copy(update={"nlu": nlu})}
    if nlu.search_query_en and nlu.intent in QUERY_INTENTS:
        update["search_query"] = nlu.search_query_en
    return update
