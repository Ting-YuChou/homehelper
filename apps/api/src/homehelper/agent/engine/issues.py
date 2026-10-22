"""Issues (spec §7.4, ADR-007): every problem the user raises is tracked until it ends.

Each journey run on a problem is an issue with a stable id. At most one is active (its progress
lives in the flat `AgentState` fields) and up to `MAX_PAUSED_ISSUES` wait in `paused_issues`.
These helpers only edit the working copy of the state inside `transition()`; the routing rules
that call them live in `transition.py`.
"""

from homehelper.agent.engine.schema import Journey
from homehelper.agent.protocol import Outcome
from homehelper.agent.state import AgentState, IssueRecord, PausedIssue, SlotValue

MAX_PAUSED_ISSUES = 3
MAX_SUMMARY_CHARS = 60
# The conversation outcome is the most significant outcome among its issues.
OUTCOME_PRIORITY: tuple[Outcome, ...] = ("escalated", "resolved", "out_of_scope", "abandoned")
TOPIC_SLOTS = ("symptom", "question")


def is_issue_journey(journey: Journey) -> bool:
    """A journey that ends on entry (the out-of-scope decline) is a reply, not a problem."""
    return journey.step(journey.entry_step).type != "end"


def issue_summary(slots: dict[str, SlotValue]) -> str:
    """A short label for cards and prompts, from slots only (never from the LLM)."""

    def value(name: str) -> str | None:
        slot = slots.get(name)
        return slot.value.strip() if slot and slot.value.strip() else None

    category = value("appliance_category")
    parts = (value("brand"), category.replace("_", " ") if category else None)
    appliance = " ".join(p for p in parts if p) or "appliance"
    topic = next((v for v in map(value, TOPIC_SLOTS) if v), None)
    text = f"{appliance}: {topic}" if topic else appliance
    if len(text) > MAX_SUMMARY_CHARS:
        text = text[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    return text


def find_record(state: AgentState, issue_id: str) -> IssueRecord | None:
    return next((r for r in state.issues if r.issue_id == issue_id), None)


def find_paused(state: AgentState, issue_id: str) -> PausedIssue | None:
    return next((p for p in state.paused_issues if p.issue_id == issue_id), None)


def open_issue(state: AgentState, journey: str) -> str:
    issue_id = f"iss_{len(state.issues) + 1}"
    state.issues.append(IssueRecord(issue_id=issue_id, journey=journey))
    state.active_issue_id = issue_id
    return issue_id


def sync_active_record(state: AgentState) -> None:
    """Keep the active issue's summary in step with its slots while it is open."""
    record = find_record(state, state.active_issue_id) if state.active_issue_id else None
    if record is None or record.outcome is not None:
        return
    record.summary = issue_summary(state.slots)
    category = state.slots.get("appliance_category")
    record.appliance_category = category.value if category else None


def close_issue(state: AgentState, issue_id: str, outcome: Outcome) -> None:
    record = find_record(state, issue_id)
    if record is not None and record.outcome is None:
        record.outcome = outcome


def close_paused(state: AgentState, category: str | None, outcome: Outcome) -> list[str]:
    """Close the paused issues about `category` (all of them when it is None). Returns their ids."""
    closing = [
        p
        for p in state.paused_issues
        if category is None
        or (
            p.slots.get("appliance_category") is not None
            and p.slots["appliance_category"].value == category
        )
    ]
    for paused in closing:
        state.paused_issues.remove(paused)
        close_issue(state, paused.issue_id, outcome)
    return [p.issue_id for p in closing]


def pause_active(state: AgentState) -> list[str]:
    """Move the active issue to the end of `paused_issues`. Returns the ids of the oldest issues
    closed as `abandoned` to stay within `MAX_PAUSED_ISSUES`."""
    assert state.active_issue_id is not None and state.active_journey is not None
    sync_active_record(state)
    record = find_record(state, state.active_issue_id)
    state.paused_issues.append(
        PausedIssue(
            issue_id=state.active_issue_id,
            journey=state.active_journey,
            summary=record.summary if record else issue_summary(state.slots),
            step_id=state.step_id,
            slots=state.slots,
            plan=state.plan,
            plan_cursor=state.plan_cursor,
            step_attempts=state.step_attempts,
            last_retrieval=state.last_retrieval,
            appliance_id=state.appliance_id,
        ).model_copy(deep=True)
    )
    dropped: list[str] = []
    while len(state.paused_issues) > MAX_PAUSED_ISSUES:
        oldest = state.paused_issues.pop(0)
        close_issue(state, oldest.issue_id, "abandoned")
        dropped.append(oldest.issue_id)
    return dropped


def take_paused(state: AgentState, issue_id: str) -> PausedIssue:
    paused = find_paused(state, issue_id)
    assert paused is not None
    state.paused_issues.remove(paused)
    return paused


def restore(state: AgentState, paused: PausedIssue) -> None:
    state.active_issue_id = paused.issue_id
    state.active_journey = paused.journey
    state.step_id = paused.step_id
    state.slots = paused.slots
    state.plan = paused.plan
    state.plan_cursor = paused.plan_cursor
    state.step_attempts = paused.step_attempts
    state.last_retrieval = paused.last_retrieval
    state.appliance_id = paused.appliance_id
    state.selected_booking_slot = None


def paused_for_category(state: AgentState, category: str) -> PausedIssue | None:
    """The most recently paused issue about this appliance, if any."""
    for paused in reversed(state.paused_issues):
        slot = paused.slots.get("appliance_category")
        if slot is not None and slot.value == category:
            return paused
    return None


def summary_outcome(state: AgentState, current: Outcome | None) -> Outcome | None:
    """The conversation outcome (spec §7.4). `current` is the active journey's step outcome:
    final at an `end` step, provisional at a `handoff` or `inform` step.

    `None` while an issue is paused or the active one has no outcome yet; otherwise the most
    significant outcome of all issues. With a single issue this is just that issue's outcome.
    """
    if state.paused_issues:
        return None
    if state.active_journey is not None and current is None:
        return None
    outcomes: list[Outcome] = [r.outcome for r in state.issues if r.outcome is not None]
    if current is not None:
        outcomes.append(current)
    return min(outcomes, key=OUTCOME_PRIORITY.index) if outcomes else None
