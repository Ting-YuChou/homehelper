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
from urllib.parse import urlparse

from homehelper.agent.deps import AgentDeps, presented_item, step_position
from homehelper.agent.engine.predicates import unconfirmed_low_confidence
from homehelper.agent.engine.transition import NOTICE_REMIND_PAUSED, NOTICE_RESUME_PAUSED
from homehelper.agent.nodes.mcp_actions import BOOKING_CONFIRMED
from homehelper.agent.nodes.respond import HANDOFF_REASONS, user_text
from homehelper.agent.tools import ToolOutcome
from homehelper.agent.turn import GraphState, TranscriptLine
from homehelper.channels.events import (
    AgentEvent,
    ApplianceConfirmCard,
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
    WebSource,
)
from homehelper.knowledge.schemas import Citation, RetrievalResult

KEEP_TRANSCRIPT_LINES = 60
MAX_RESULT_CARDS = 3  # per kind (parts, videos)

HANDOFF_CARD_REASONS = {
    "only_powered_steps_left": "The remaining steps need the power on, which isn't safe now",
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


def web_sources(citation_ids: list[str], retrieval: RetrievalResult | None) -> list[WebSource]:
    """The unofficial pages a step cites, from the retrieval it was planned from."""
    cited = set(citation_ids)
    findings = retrieval.web_findings if retrieval is not None else []
    sources = {
        f.url: WebSource(url=f.url, title=f.title, domain=urlparse(f.url).hostname or f.url)
        for f in findings
        if f.id and f.id in cited
    }
    return list(sources.values())


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

    blocked = turn.verdict is not None and turn.verdict.action == "block"
    if replacing:
        # A visit booked this turn is still confirmed after a template that replaces the reply.
        booked = [r for r in prefix if r.rule_id == BOOKING_CONFIRMED]
        text = "\n\n".join(r.text for r in [*replacing, *booked])
    else:
        reply_text = turn.reply.message if turn.reply else ""
        hint = [turn.model_hint] if turn.model_hint and not blocked else []
        text = "\n\n".join([*(r.text for r in prefix), reply_text, *hint]).strip()
        if turn.reply is not None:
            citations.extend(
                graph.citations[cid] for cid in turn.reply.citation_ids if cid in graph.citations
            )

    step = deps.step(state)
    if step is not None and step.type == "guide" and not turn.side_question and not replacing:
        item = presented_item(state)
        if item is not None and not blocked:
            item_citations = [graph.citations[c] for c in item.citation_ids if c in graph.citations]
            index, total = step_position(state, item)
            cards.append(
                StepCard(
                    plan_item_id=item.id,
                    index=index,
                    total=total,
                    instruction=item.instruction,
                    citations=item_citations,
                    warranty_warning=item.warranty_warning,
                    issue_id=state.active_issue_id,
                    web_sources=web_sources(item.citation_ids, state.last_retrieval),
                    general=item.general,
                )
            )
            citations.extend(item_citations)
    pending = unconfirmed_low_confidence(state)
    if step is not None and step.type == "confirm" and pending and not replacing:
        # "Looks like an LG washer (WM3400CW): is that right?" with Yes / No buttons (§11.2).
        def value(name: str) -> str | None:
            slot = state.slots.get(name)
            return slot.value if slot else None

        cards.append(
            ApplianceConfirmCard(
                category=value("appliance_category"),
                brand=value("brand"),
                model_number=value("model_number"),
                confidence=min(state.slots[name].confidence for name in pending),
            )
        )
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
