"""`understand` (M3-03): structured NLU for free text. Card buttons skip it (spec §7.3).

A message that is only a photo or video still gets NLU when the media could be analyzed: it reads
what the image model saw (issues, error codes), never the appliance's identity (M6-02).
"""

from typing import Any

from homehelper.agent import prompts
from homehelper.agent.deps import AgentDeps, presented_item, slot_values
from homehelper.agent.state import NLUResult, SlotUpdate
from homehelper.agent.turn import MAX_TRANSCRIPT_LINES, GraphState
from homehelper.knowledge.features import TRAIT_SLOT_PREFIX, ManualIndex, trait_slot
from homehelper.knowledge.schemas import CategoryId
from homehelper.llm import LLMError, Message
from homehelper.media.schemas import VisionResult

CATEGORIES = [category.value for category in CategoryId]
# Intents whose search query describes the user's problem or question (kept across turns).
QUERY_INTENTS = frozenset({"report_problem", "ask_how_to"})
# What NLU reads for a message that is only a photo or video.
MEDIA_ONLY_TEXT = "(The user sent a photo or video without any text.)"


def media_notes(state: GraphState) -> list[str]:
    """What the turn's photos and video show and sound like, for NLU: never the appliance's
    identity (brand, model, nameplate), which reaches the engine only as perceived slots."""
    results: list[VisionResult] = []
    notes: list[str] = []
    for observation in state.turn.media:
        if observation.vision is not None and observation.vision not in results:
            results.append(observation.vision)
            if observation.vision.displayed_error_code:
                notes.append(f"the display shows {observation.vision.displayed_error_code}")
            notes.extend(observation.vision.visible_issues)
        if observation.video is not None:
            video = observation.video
            if video.symptom_description:
                notes.append(f"the video shows: {video.symptom_description}")
            notes.extend(f"it sounds like: {cue}" for cue in video.audio_cues)
            notes.extend(f"the display shows {code}" for code in video.visible_error_codes)
    return notes


def trait_choices(state: GraphState, deps: AgentDeps) -> list[dict[str, object]]:
    """What NLU may record about the appliance's look (ADR-013): the traits of its category, or
    of every category while it is unknown; none outside troubleshooting."""
    agent = state.state
    if deps.manuals is None or agent.active_journey not in (None, "troubleshoot"):
        return []
    category = agent.slots.get("appliance_category")
    categories = deps.manuals.features.categories
    wanted = [CategoryId(category.value)] if category and category.value in categories else None
    return [
        {"slot": trait_slot(name), "values": list(trait.values)}
        for cat, vocabulary in categories.items()
        if wanted is None or cat in wanted
        for name, trait in vocabulary.traits.items()
    ]


def valid_traits(nlu: NLUResult, category: str | None, manuals: ManualIndex | None) -> NLUResult:
    """Trait updates whose value the category's vocabulary has; any other is dropped."""

    def keep(update: SlotUpdate) -> bool:
        if not update.name.startswith(TRAIT_SLOT_PREFIX):
            return True
        named = next((u.value for u in nlu.slot_updates if u.name == "appliance_category"), None)
        value = (named or category or "").strip().lower().replace(" ", "_")
        if manuals is None or value not in {c.value for c in CategoryId}:
            return False
        trait = manuals.trait(CategoryId(value), update.name.removeprefix(TRAIT_SLOT_PREFIX))
        return trait is not None and update.value.strip() in trait.values

    kept = [u for u in nlu.slot_updates if keep(u)]
    return (
        nlu if len(kept) == len(nlu.slot_updates) else nlu.model_copy(update={"slot_updates": kept})
    )


def known_model(nlu: NLUResult, manuals: ManualIndex | None) -> NLUResult:
    """A model number without a digit ("BVMC-HC", "whapsro") is kept only when a manual's model
    pattern matches it, in capitals; otherwise words like "MISSING" or "SAMSUNG" would pass."""
    if manuals is None:
        return nlu
    kept: list[SlotUpdate] = []
    for update in nlu.slot_updates:
        value = update.value.strip()
        if update.name != "model_number" or any(c.isdigit() for c in value):
            kept.append(update)
        elif manuals.model_manuals(value, None):
            kept.append(update.model_copy(update={"value": value.upper()}))
    if kept == nlu.slot_updates:
        return nlu
    return nlu.model_copy(update={"slot_updates": kept})


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
        traits=trait_choices(state, deps),
    )
    return [Message(role="user", content=prompt)]


async def understand(state: GraphState, deps: AgentDeps) -> dict[str, Any]:
    message = state.turn.message
    assert message is not None
    text = (message.text or "").strip()
    if message.action is not None and (message.action.type != "step_result" or not text):
        return {}  # a button; words typed with a step result may name the model (ADR-013)
    if not text:
        if not any(o.vision is not None or o.video is not None for o in state.turn.media):
            return {}
        text = MEDIA_ONLY_TEXT
    try:
        nlu = await deps.llm.structured("nlu", nlu_messages(state, deps, text), NLUResult)
    except LLMError:
        if message.action is None:
            raise
        return {}  # the button alone still counts

    category = state.state.slots.get("appliance_category")
    nlu = valid_traits(nlu, category.value if category else None, deps.manuals)
    nlu = known_model(nlu, deps.manuals)
    update: dict[str, Any] = {"turn": state.turn.model_copy(update={"nlu": nlu})}
    if nlu.search_query_en and nlu.intent in QUERY_INTENTS and message.action is None:
        update["search_query"] = nlu.search_query_en
    return update
