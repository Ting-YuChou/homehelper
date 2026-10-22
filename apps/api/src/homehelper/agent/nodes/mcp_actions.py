"""MCP tools run by journey step actions (spec §7.4, §12.1): code builds the arguments from the
state, so write tools never depend on what the LLM says.

Each builder returns the arguments, or a `Skip` saying why the action cannot run now (no
signed-in user, no matching appliance, ...). A skipped or failed action is logged as a Decision
and the journey carries on: a tool outage must not stop troubleshooting.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homehelper.agent.deps import AgentDeps
from homehelper.agent.engine.schema import is_write_tool
from homehelper.agent.guardrails.templates import FixedReply
from homehelper.agent.protocol import ToolCall
from homehelper.agent.state import (
    AgentState,
    Decision,
    OfferedSlot,
    ProfileAppliance,
    UserContext,
)
from homehelper.agent.tools import ToolOutcome
from homehelper.agent.turn import AgentReply, GraphState, SupervisorVerdict, TurnScratch

GET_WARRANTY = "mcp:user_profile.get_warranty_status"
LIST_SLOTS = "mcp:service_booking.list_slots"
BOOK = "mcp:service_booking.book"
OFFERED_SLOTS = 4
LIST_REPAIRS = "mcp:user_profile.list_repair_history"
MIN_SHARED_WORD = 4  # letters; shorter words ("the", "won't") say nothing about the problem
BOOKING_CONFIRMED = "BOOKING"  # rule id of the code-built booking confirmation
BOOKING_CLOSING = "Is there anything else I can help you with?"


@dataclass(frozen=True)
class Skip:
    reason: str


ArgBuilder = Callable[[GraphState, AgentState], dict[str, Any] | Skip]


def tool_user(state: AgentState) -> str | None:
    """The user MCP tools act for: only a user with a profile (guests have none)."""
    return state.user_id if state.profile is not None else None


async def load_profile(deps: AgentDeps, user_id: str | None) -> UserContext | None:
    """The user's profile and appliances, or None for guests or when the tools are down.
    These context reads are not step actions, so they are not logged as tool calls."""
    if deps.tools is None or user_id is None:
        return None
    profile = await deps.tools.call_action("mcp:user_profile.get_profile", {}, user_id=user_id)
    if not profile.ok or not isinstance(profile.data, dict):
        return None
    listed = await deps.tools.call_action("mcp:user_profile.list_appliances", {}, user_id=user_id)
    appliances = listed.data if listed.ok and isinstance(listed.data, list) else []
    return UserContext(
        zip_code=profile.data.get("zip_code"),
        appliances=[ProfileAppliance.model_validate(a) for a in appliances],
    )


def _slot(state: AgentState, name: str) -> str | None:
    slot = state.slots.get(name)
    return slot.value if slot else None


def _video_args(graph: GraphState, state: AgentState) -> dict[str, Any] | Skip:
    query = graph.search_query or _slot(state, "question") or _slot(state, "symptom")
    if not query:
        return Skip("nothing to search videos for")
    return {
        "query": query[:200],
        "brand": _slot(state, "brand"),
        "category": _slot(state, "appliance_category"),
        "max_results": 3,
    }


def _appliance(state: AgentState) -> str | Skip:
    if tool_user(state) is None:
        return Skip("no signed-in user with a profile")
    if state.appliance_id is None:
        return Skip("the issue is not linked to an appliance in the user's profile")
    return state.appliance_id


def _appliance_args(graph: GraphState, state: AgentState) -> dict[str, Any] | Skip:
    appliance = _appliance(state)
    return appliance if isinstance(appliance, Skip) else {"appliance_id": appliance}


def _history_args(graph: GraphState, state: AgentState) -> dict[str, Any] | Skip:
    appliance = _appliance(state)
    return appliance if isinstance(appliance, Skip) else {"appliance_id": appliance, "limit": 5}


def _parts_args(graph: GraphState, state: AgentState) -> dict[str, Any] | Skip:
    return {
        "category": _slot(state, "appliance_category"),
        "brand": _slot(state, "brand"),
        "model": _slot(state, "model_number"),
        "symptom": (_slot(state, "symptom") or "")[:200] or None,
        "limit": 3,
    }


def _repair_record_args(graph: GraphState, state: AgentState) -> dict[str, Any] | Skip:
    appliance = _appliance(state)
    if isinstance(appliance, Skip):
        return appliance
    fixed = next((item for item in state.plan if item.status == "fixed"), None)
    return {
        "appliance_id": appliance,
        "issue": (_slot(state, "symptom") or _slot(state, "question") or "Troubleshooting")[:500],
        "resolution": (fixed.instruction if fixed else "Solved with HomeHelper's help")[:1000],
        "outcome": "resolved",
        "error_code": _slot(state, "error_code"),
        "performed_by": "self",
    }


def _slots_args(graph: GraphState, state: AgentState) -> dict[str, Any] | Skip:
    # Booking is for an appliance in the user's profile: `book` needs its id.
    appliance = _appliance(state)
    if isinstance(appliance, Skip):
        return appliance
    zip_code = state.profile.zip_code if state.profile else None
    category = _slot(state, "appliance_category")
    if not zip_code or not category:
        return Skip("no ZIP code or appliance category to look up visits")
    return {"zip_code": zip_code, "category": category, "limit": OFFERED_SLOTS}


def _book_args(graph: GraphState, state: AgentState) -> dict[str, Any] | Skip:
    appliance = _appliance(state)
    if isinstance(appliance, Skip):
        return appliance
    if state.selected_booking_slot is None:
        return Skip("no visit time was picked")
    issue = _slot(state, "symptom") or _slot(state, "question") or "Appliance repair"
    return {"slot_id": state.selected_booking_slot, "appliance_id": appliance, "issue": issue}


ACTION_ARGS: dict[str, ArgBuilder] = {
    "mcp:tutorials.search_videos": _video_args,
    "mcp:parts_catalog.search_parts": _parts_args,
    GET_WARRANTY: _appliance_args,
    LIST_REPAIRS: _history_args,
    "mcp:user_profile.add_repair_record": _repair_record_args,
    LIST_SLOTS: _slots_args,
    BOOK: _book_args,
}


def apply_result(state: AgentState, outcome: ToolOutcome) -> None:
    """State that later turns need from a tool result: the slots that may be booked."""
    if outcome.tool == "service_booking.list_slots":
        slots = outcome.data if outcome.ok and isinstance(outcome.data, list) else []
        state.offered_slots = [
            OfferedSlot(
                slot_id=slot["slot_id"],
                starts_at=str(slot["starts_at"]),
                technician=f"{slot['technician_name']} ({slot['company']})",
            )
            for slot in slots
        ]


def booked(outcomes: list[ToolOutcome]) -> ToolOutcome | None:
    return next((o for o in outcomes if o.tool == "service_booking.book"), None)


def _visit_time(starts_at: str) -> str:
    try:
        start = datetime.fromisoformat(starts_at)
    except ValueError:
        return starts_at
    when = f"{start:%A, %B} {start.day} at {start:%I:%M %p}".replace(" 0", " ")
    # The web card shows the time in the browser's zone: name the zone so the two can be compared.
    zone = start.tzname()
    return f"{when} ({zone})" if zone else when


def booking_confirmation(outcomes: list[ToolOutcome], state: AgentState) -> FixedReply | None:
    """The booking, stated by code: shown above the reply, so neither a failed nor a blocked LLM
    reply can hide that the visit is booked."""
    booking = booked(outcomes)
    if booking is None or not booking.ok:
        return None
    slot_id = booking.arguments.get("slot_id")
    slot = next((s for s in state.offered_slots if s.slot_id == slot_id), None)
    when = f" for {_visit_time(slot.starts_at)} with {slot.technician}" if slot else ""
    return FixedReply(
        rule_id=BOOKING_CONFIRMED,
        text=f"Your technician visit is booked{when}.",
        replaces_response=False,
    )


def warranty_active(outcomes: list[ToolOutcome]) -> bool:
    """G-WARR-01 applies when this turn's warranty check says the warranty is active."""
    return any(
        o.ok and o.tool == "user_profile.get_warranty_status" and o.data.get("status") == "active"
        for o in outcomes
        if isinstance(o.data, dict)
    )


def _words(text: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= MIN_SHARED_WORD}


def similar_repairs(outcomes: list[ToolOutcome], state: AgentState) -> list[dict[str, Any]]:
    """Earlier repairs of the same kind: the same error code, or a shared word in the issue."""
    code = (_slot(state, "error_code") or "").upper()
    symptom = _words(_slot(state, "symptom"))
    found = []
    for outcome in outcomes:
        if not (outcome.ok and outcome.tool == "user_profile.list_repair_history"):
            continue
        for record in outcome.data if isinstance(outcome.data, list) else []:
            same_code = bool(code) and (record.get("error_code") or "").upper() == code
            if same_code or symptom & _words(record.get("issue")):
                found.append(record)
    return found


def as_tool_call(outcome: ToolOutcome, source: str, issue_id: str | None) -> ToolCall:
    return ToolCall(
        name=outcome.tool,
        arguments=outcome.arguments,
        source="llm" if source == "llm" else "action",
        ok=outcome.ok,
        issue_id=issue_id,
    )


def _replayed_data(state: AgentState, done: ToolCall) -> dict[str, Any] | None:
    """What the supervisor and responder can cite about a replayed booking: the slot it took."""
    slot_id = done.arguments.get("slot_id")
    slot = next((s for s in state.offered_slots if s.slot_id == slot_id), None)
    return slot.model_dump() if slot else None


def booking_fallback(turn: TurnScratch) -> TurnScratch | None:
    """When the LLM fails after a booking, a fixed closing becomes the reply, under the booking
    confirmation and any other prefix (e.g. the G-SAFE-05 warning): the visit is booked, so the
    turn must not end in an error that hides it. The pass verdict is code's: `supervise` keeps it.
    None when nothing was booked."""
    if not any(r.rule_id == BOOKING_CONFIRMED for r in turn.fixed_replies):
        return None
    return turn.model_copy(
        update={
            "reply": AgentReply(message=BOOKING_CLOSING),
            "verdict": SupervisorVerdict(action="pass", reasons=["code-built booking closing"]),
        }
    )


def _done_write(graph: GraphState, state: AgentState, tool: str) -> ToolCall | None:
    """This write's earlier success for the active issue. A turn that failed after the write is
    rolled back but keeps the write's record (`JourneyAgent._roll_back`), so a retry finds it."""
    if state.active_issue_id is None:
        return None
    return next(
        (
            call
            for call in graph.tool_calls
            if call.name == tool and call.ok and call.issue_id == state.active_issue_id
        ),
        None,
    )


async def run_mcp_action(
    action: str, graph: GraphState, state: AgentState, deps: AgentDeps
) -> ToolOutcome | None:
    """Run one `mcp:` step action; None when it was skipped. Decisions go to `state`."""
    builder = ACTION_ARGS.get(action)
    if deps.tools is None or builder is None:
        reason = "MCP tools are not connected" if deps.tools is None else "no argument builder"
        state.decision_log.append(
            Decision(
                kind="tool", journey=state.active_journey, reason=f"skipped {action}: {reason}"
            )
        )
        return None
    done = _done_write(graph, state, action.removeprefix("mcp:")) if is_write_tool(action) else None
    if done is not None:
        state.decision_log.append(
            Decision(
                kind="tool",
                journey=state.active_journey,
                reason=f"skipped {action}: already done for {state.active_issue_id}",
            )
        )
        return ToolOutcome(
            tool=done.name,
            arguments=done.arguments,
            ok=True,
            data=_replayed_data(state, done),
            replayed=True,
        )
    arguments = builder(graph, state)
    if isinstance(arguments, Skip):
        state.decision_log.append(
            Decision(
                kind="tool",
                journey=state.active_journey,
                reason=f"skipped {action}: {arguments.reason}",
            )
        )
        return None
    with deps.span(action, input=arguments) as span:
        outcome = await deps.tools.call_action(action, arguments, user_id=tool_user(state))
        if span is not None:
            span.update(output=outcome.model_dump(exclude={"arguments"}))
    apply_result(state, outcome)
    state.decision_log.append(
        Decision(
            kind="tool",
            journey=state.active_journey,
            reason=(
                f"{outcome.tool}: ok" if outcome.ok else f"{outcome.tool} failed: {outcome.error}"
            ),
        )
    )
    return outcome
