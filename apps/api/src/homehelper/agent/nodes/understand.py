"""`understand` (M3-03): structured NLU for free text. Card buttons skip it (spec §7.3).

A message that is only a photo or video still gets NLU when the media could be analyzed: it reads
what the image model saw (issues, error codes), never the appliance's identity (M6-02).
"""

from typing import Any

from homehelper.agent import prompts
from homehelper.agent.deps import AgentDeps, presented_item, slot_values
from homehelper.agent.state import NLUResult
from homehelper.agent.turn import MAX_TRANSCRIPT_LINES, GraphState
from homehelper.knowledge.schemas import CategoryId
from homehelper.llm import Message
from homehelper.media.schemas import VisionResult

CATEGORIES = [category.value for category in CategoryId]
# Intents whose search query describes the user's problem or question (kept across turns).
QUERY_INTENTS = frozenset({"report_problem", "ask_how_to"})
# What NLU reads for a message that is only a photo or video.
MEDIA_ONLY_TEXT = "(The user sent a photo or video without any text.)"


def media_notes(state: GraphState) -> list[str]:
    """Visible problems and displayed codes from the turn's media, for NLU."""
    results: list[VisionResult] = []
    for observation in state.turn.media:
        if observation.vision is not None and observation.vision not in results:
            results.append(observation.vision)
    notes: list[str] = []
    for result in results:
        if result.displayed_error_code:
            notes.append(f"the display shows {result.displayed_error_code}")
        notes.extend(result.visible_issues)
    return notes


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
        media_notes=media_notes(state),
    )
    return [Message(role="user", content=prompt)]


async def understand(state: GraphState, deps: AgentDeps) -> dict[str, Any]:
    message = state.turn.message
    assert message is not None
    if message.action is not None:
        return {}
    text = (message.text or "").strip()
    if not text:
        if not any(o.vision is not None for o in state.turn.media):
            return {}
        text = MEDIA_ONLY_TEXT
    nlu = await deps.llm.structured("nlu", nlu_messages(state, deps, text), NLUResult)
    update: dict[str, Any] = {"turn": state.turn.model_copy(update={"nlu": nlu})}
    if nlu.search_query_en and nlu.intent in QUERY_INTENTS:
        update["search_query"] = nlu.search_query_en
    return update
