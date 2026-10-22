"""Plain-text views of a conversation: for the simulator and judge prompts, and for human review."""

from homehelper.channels.events import (
    ApplianceConfirmCard,
    BookingSlotsCard,
    Card,
    CitationCard,
    HandoffCard,
    IssuesCard,
    PartCard,
    SafetyCard,
    StepCard,
    VideoCard,
)
from homehelper_evals.cases import EvalCase
from homehelper_evals.transcript import AgentTurn, Transcript, UserTurn


def render_card(card: Card) -> str:
    match card:
        case StepCard():
            buttons = " / ".join(card.actions)
            return f"[Step {card.index}/{card.total}] {card.instruction} (buttons: {buttons})"
        case SafetyCard():
            return f"[Safety: {card.hazard}] " + " ".join(card.instructions)
        case HandoffCard():
            booking = "booking available" if card.booking_available else "no booking"
            return f"[Handoff: {card.reason}; {booking}]"
        case BookingSlotsCard():
            slots = ", ".join(f"{s.slot_id} at {s.starts_at} ({s.technician})" for s in card.slots)
            return f"[Booking slots: {slots}]"
        case ApplianceConfirmCard():
            fields = [card.brand, card.category, card.model_number]
            return "[Confirm appliance: " + " ".join(f for f in fields if f) + "]"
        case CitationCard():
            return f"[Source: {card.title}, page {card.citation.page}]"
        case PartCard():
            return f"[Part: {card.name}]"
        case VideoCard():
            return f"[Video: {card.title}]"
        case IssuesCard():
            issues = "; ".join(f"{i.issue_id}: {i.summary}" for i in card.issues)
            return f"[Open problems: {issues} (buttons per problem: resume_issue / close_issue)]"


def render_agent_turn(turn: AgentTurn) -> str:
    parts = [turn.text.strip()] if turn.text.strip() else []
    parts.extend(render_card(card) for card in turn.cards)
    if turn.error:
        parts.append(f"[Error: {turn.error}]")
    return "\n".join(parts) or "(no reply)"


def render_user_turn(turn: UserTurn) -> str:
    parts = []
    if turn.action is not None:
        parts.append(f"[pressed {turn.action.type}: {turn.action.value}]")
    if turn.text:
        parts.append(turn.text)
    return " ".join(parts) or "(empty)"


def render_dialogue(turns: list[UserTurn | AgentTurn], *, user: str, agent: str) -> str:
    lines = []
    for turn in turns:
        if isinstance(turn, UserTurn):
            lines.append(f"{user}: {render_user_turn(turn)}")
        else:
            lines.append(f"{agent}: {render_agent_turn(turn)}")
    return "\n\n".join(lines)


def render_markdown(case: EvalCase, transcript: Transcript, grades: dict | None = None) -> str:
    """One conversation as Markdown, for manual review (M2-03)."""
    header = [
        f"### {case.id} (trial {transcript.trial})",
        "",
        f"- kind: {case.kind}; persona: {case.persona}; category: {case.category}",
        f"- scenario: {case.scenario}",
    ]
    if case.root_cause_text:
        header.append(f"- root cause (step {case.root_cause_step}): {case.root_cause_text}")
    header.append(
        f"- end: {transcript.end_reason}; outcome: {transcript.outcome}; "
        f"expected: {', '.join(case.expected_outcomes)}"
    )
    if grades is not None:
        header.append(f"- grades: {grades}")
    body = render_dialogue(transcript.turns, user="**User**", agent="**Agent**")
    return "\n".join(header) + "\n\n" + body + "\n"
