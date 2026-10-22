"""`emit` (spec §7.3 `persist_and_emit`): turn the checked reply and the state into events.

Cards come from state, never from the LLM: the step card from the presented plan item, safety
cards from fixed templates, the handoff card at a handoff step, part and video cards from this
turn's tool results. The transcript the graph keeps
for NLU and the responder is updated here; the checkpointer persists it with the rest of the
state (the API writes `messages` from these events, spec v0.8).
"""

import uuid
from collections.abc import Callable
from typing import Any

from homehelper.agent.deps import AgentDeps, presented_item
from homehelper.agent.engine.transition import NOTICE_REMIND_PAUSED, NOTICE_RESUME_PAUSED
from homehelper.agent.nodes.respond import HANDOFF_REASONS, user_text
from homehelper.agent.tools import ToolOutcome
from homehelper.agent.turn import GraphState, TranscriptLine
from homehelper.channels.events import (
    AgentEvent,
    BookingSlot,
    BookingSlotsCard,
    Card,
    CardEvent,
    HandoffCard,
    IssueOption,
    IssuesCard,
    MessageCompletedEvent,
    MessageDeltaEvent,
    PartCard,
    StepCard,
    VideoCard,
)
from homehelper.knowledge.schemas import Citation

KEEP_TRANSCRIPT_LINES = 60
MAX_RESULT_CARDS = 3  # per kind (parts, videos)

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


def _records(outcome: ToolOutcome) -> list[dict[str, Any]]:
    data = outcome.data
    items = data if isinstance(data, list) else [data]
    return [item for item in items if isinstance(item, dict)]


def result_cards(outcomes: list[ToolOutcome]) -> list[Card]:
    """Part and video cards from the tools' structured results (never from the reply text)."""
    parts: dict[str, PartCard] = {}
    videos: dict[str, VideoCard] = {}
    for outcome in outcomes:
        if not outcome.ok:
            continue
        for record in _records(outcome):
            if outcome.tool in ("parts_catalog.search_parts", "parts_catalog.get_part"):
                parts.setdefault(
                    record["part_id"],
                    PartCard(
                        part_id=record["part_id"],
                        name=record["name"],
                        price_usd=record.get("price_usd"),
                        image_url=record.get("image_url"),
                    ),
                )
            elif outcome.tool == "tutorials.search_videos":
                videos.setdefault(
                    record["url"],
                    VideoCard(
                        title=record["title"],
                        url=record["url"],
                        thumbnail_url=record.get("thumbnail_url"),
                    ),
                )
    return [*list(parts.values())[:MAX_RESULT_CARDS], *list(videos.values())[:MAX_RESULT_CARDS]]


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
                    issue_id=state.active_issue_id,
                )
            )
            citations.extend(item_citations)
    if step is not None and step.type == "handoff":
        offered = state.offered_slots
        cards.append(
            HandoffCard(reason=_handoff_card_reason(graph), booking_available=bool(offered))
        )
        just_listed = any(o.tool == "service_booking.list_slots" for o in turn.tool_results)
        if offered and just_listed:
            cards.append(
                BookingSlotsCard(
                    slots=[
                        BookingSlot(
                            slot_id=s.slot_id, starts_at=s.starts_at, technician=s.technician
                        )
                        for s in offered
                    ]
                )
            )
    if not replacing and not blocked:
        cards.extend(result_cards(turn.tool_results))
    offer = NOTICE_RESUME_PAUSED in turn.notices or NOTICE_REMIND_PAUSED in turn.notices
    if offer and state.paused_issues and not replacing:
        options = [
            IssueOption(issue_id=p.issue_id, summary=p.summary)
            for p in reversed(state.paused_issues)
        ]
        cards.append(IssuesCard(issues=options))
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
    shown = text
    for card in cards:
        if isinstance(card, StepCard):
            shown += f"\n[Step {card.index}/{card.total}: {card.instruction}]"
        elif isinstance(card, IssuesCard):
            # So NLU can resolve "yes, the dryer" on the next turn.
            shown += "\n[Open problems: " + "; ".join(o.summary for o in card.issues) + "]"
    transcript = [
        *graph.transcript,
        TranscriptLine(role="user", text=user_text(graph)),
        TranscriptLine(role="assistant", text=shown),
    ]
    return {"transcript": transcript[-KEEP_TRANSCRIPT_LINES:]}
