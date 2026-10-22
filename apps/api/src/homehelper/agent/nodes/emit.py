"""`emit` (spec §7.3 `persist_and_emit`): turn the checked reply and the state into events.

Cards come from state, never from the LLM: the step card from the presented plan item, safety
cards from fixed templates, the handoff card at a handoff step. The transcript the graph keeps
for NLU and the responder is updated here; the checkpointer persists it with the rest of the
state (the API writes `messages` from these events, spec v0.8).
"""

import uuid
from collections.abc import Callable
from typing import Any

from homehelper.agent.deps import AgentDeps, presented_item
from homehelper.agent.nodes.respond import HANDOFF_REASONS, user_text
from homehelper.agent.turn import GraphState, TranscriptLine
from homehelper.channels.events import (
    AgentEvent,
    Card,
    CardEvent,
    HandoffCard,
    MessageCompletedEvent,
    MessageDeltaEvent,
    StepCard,
)
from homehelper.knowledge.schemas import Citation

KEEP_TRANSCRIPT_LINES = 60

HANDOFF_CARD_REASONS = {
    "hazard_detected": "Safety hazard",
    "max_failed_steps_reached": "The troubleshooting steps did not fix it",
    "plan_exhausted": "The troubleshooting steps did not fix it",
    "plan_unavailable": "The manual does not cover this problem",
    "user_requested_technician": "You asked for a technician",
}


def _handoff_card_reason(graph: GraphState) -> str:
    state = graph.state
    for decision in reversed(state.decision_log):
        if decision.to_step == state.step_id and decision.predicate in HANDOFF_REASONS:
            return HANDOFF_CARD_REASONS[decision.predicate]
    return "Professional help recommended"


def compose(graph: GraphState, deps: AgentDeps) -> tuple[str, list[Card], list[Citation]]:
    turn = graph.turn
    state = graph.state
    replacing = [r for r in turn.fixed_replies if r.replaces_response]
    prefix = [r for r in turn.fixed_replies if not r.replaces_response]
    cards: list[Card] = [r.card for r in [*replacing, *prefix] if r.card is not None]
    citations: list[Citation] = []

    if replacing:
        text = "\n\n".join(r.text for r in replacing)
    else:
        reply_text = turn.reply.message if turn.reply else ""
        text = "\n\n".join([*(r.text for r in prefix), reply_text]).strip()
        if turn.reply is not None:
            citations.extend(
                graph.citations[cid] for cid in turn.reply.citation_ids if cid in graph.citations
            )

    step = deps.step(state)
    blocked = turn.verdict is not None and turn.verdict.action == "block"
    if step is not None and step.type == "guide" and not turn.side_question and not replacing:
        item = presented_item(state)
        if item is not None and not blocked:
            item_citations = [graph.citations[c] for c in item.citation_ids if c in graph.citations]
            cards.append(
                StepCard(
                    plan_item_id=item.id,
                    index=state.plan.index(item) + 1,
                    total=len(state.plan),
                    instruction=item.instruction,
                    citations=item_citations,
                    warranty_warning=item.warranty_warning,
                )
            )
            citations.extend(item_citations)
    if step is not None and step.type == "handoff":
        cards.append(HandoffCard(reason=_handoff_card_reason(graph), booking_available=False))
    return text, cards, list({c.chunk_id: c for c in citations}.values())


def emit(graph: GraphState, deps: AgentDeps, write: Callable[[AgentEvent], None]) -> dict[str, Any]:
    text, cards, citations = compose(graph, deps)
    state = graph.state
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    write(MessageDeltaEvent(message_id=message_id, text=text))
    for card in cards:
        write(CardEvent(message_id=message_id, card=card))
    write(
        MessageCompletedEvent(
            message_id=message_id,
            citations=citations,
            journey=state.active_journey,
            step=state.step_id,
        )
    )
    shown = text + "".join(
        f"\n[Step {c.index}/{c.total}: {c.instruction}]" for c in cards if isinstance(c, StepCard)
    )
    transcript = [
        *graph.transcript,
        TranscriptLine(role="user", text=user_text(graph)),
        TranscriptLine(role="assistant", text=shown),
    ]
    return {"transcript": transcript[-KEEP_TRANSCRIPT_LINES:]}
