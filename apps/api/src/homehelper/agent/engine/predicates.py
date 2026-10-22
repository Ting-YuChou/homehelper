"""Named predicates referenced from journey YAML (spec §7.1). YAML holds names, never expressions.

A predicate is a pure function of `PredicateContext`. `signals` is None once the turn's input has
been consumed by a transition, so input-driven predicates fire at most once per turn while
state-driven ones (e.g. `required_slots_filled`) keep chaining through steps.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from homehelper.agent.engine.schema import Journey
from homehelper.agent.engine.signals import TurnSignals
from homehelper.agent.guardrails.rules import MAX_FAILED_STEPS
from homehelper.agent.state import AgentState

LOW_CONFIDENCE = 0.8  # slots below this need user confirmation unless already confirmed


@dataclass(frozen=True)
class PredicateContext:
    journey: Journey
    state: AgentState
    signals: TurnSignals | None = None


Predicate = Callable[[PredicateContext], bool]


class PredicateRegistry:
    def __init__(self) -> None:
        self._predicates: dict[str, Predicate] = {}

    def register(self, name: str) -> Callable[[Predicate], Predicate]:
        def decorator(fn: Predicate) -> Predicate:
            if name in self._predicates:
                raise ValueError(f"predicate {name!r} is already registered")
            self._predicates[name] = fn
            return fn

        return decorator

    def __contains__(self, name: object) -> bool:
        return name in self._predicates

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._predicates))

    def evaluate(self, name: str, ctx: PredicateContext) -> bool:
        return self._predicates[name](ctx)


PREDICATES = PredicateRegistry()
predicate = PREDICATES.register


# --- helpers --------------------------------------------------------------------------------


def has_pending_item(state: AgentState) -> bool:
    return any(item.status == "pending" for item in state.plan)


def failed_step_count(state: AgentState) -> int:
    return sum(
        1
        for item in state.plan
        if item.status in ("done_not_fixed", "skipped") and item.safety_rule is None
    )


def unconfirmed_low_confidence(state: AgentState) -> list[str]:
    return [
        name
        for name, slot in state.slots.items()
        if not slot.confirmed and slot.confidence < LOW_CONFIDENCE
    ]


# --- predicates -----------------------------------------------------------------------------


@predicate("always")
def always(ctx: PredicateContext) -> bool:
    return True


@predicate("hazard_detected")
def hazard_detected(ctx: PredicateContext) -> bool:
    """An escalating hazard was detected this turn. G-SAFE-05 (water near electricity) escalates
    only when it is reported again after its warning."""
    return ctx.signals is not None and bool(ctx.signals.escalating_hazards)


@predicate("max_failed_steps_reached")
def max_failed_steps_reached(ctx: PredicateContext) -> bool:
    return failed_step_count(ctx.state) >= MAX_FAILED_STEPS


@predicate("user_requested_technician")
def user_requested_technician(ctx: PredicateContext) -> bool:
    return ctx.signals is not None and ctx.signals.intent == "book_technician"


@predicate("required_slots_filled")
def required_slots_filled(ctx: PredicateContext) -> bool:
    return all(name in ctx.state.slots for name in ctx.journey.required_slots())


@predicate("no_unconfirmed_low_confidence_slots")
def no_unconfirmed_low_confidence_slots(ctx: PredicateContext) -> bool:
    return not unconfirmed_low_confidence(ctx.state)


@predicate("user_confirmed")
def user_confirmed(ctx: PredicateContext) -> bool:
    return ctx.signals is not None and ctx.signals.confirmed is True


@predicate("user_denied")
def user_denied(ctx: PredicateContext) -> bool:
    return ctx.signals is not None and ctx.signals.confirmed is False


@predicate("knowledge_available")
def knowledge_available(ctx: PredicateContext) -> bool:
    retrieval = ctx.state.last_retrieval
    return retrieval is not None and bool(retrieval.chunks or retrieval.web_findings)


@predicate("no_relevant_knowledge")
def no_relevant_knowledge(ctx: PredicateContext) -> bool:
    return not knowledge_available(ctx)


@predicate("plan_available")
def plan_available(ctx: PredicateContext) -> bool:
    return has_pending_item(ctx.state)


@predicate("plan_unavailable")
def plan_unavailable(ctx: PredicateContext) -> bool:
    """No usable plan: nothing retrieved, or post-processing removed every item."""
    return not has_pending_item(ctx.state)


@predicate("user_reports_fixed")
def user_reports_fixed(ctx: PredicateContext) -> bool:
    return ctx.signals is not None and ctx.signals.feedback == "fixed"


@predicate("user_reports_not_fixed_and_plan_has_next")
def user_reports_not_fixed_and_plan_has_next(ctx: PredicateContext) -> bool:
    return (
        ctx.signals is not None
        and ctx.signals.feedback in ("not_fixed", "cannot_do")
        and has_pending_item(ctx.state)
    )


@predicate("plan_exhausted")
def plan_exhausted(ctx: PredicateContext) -> bool:
    """Every item was tried (or skipped) and none fixed the problem."""
    plan = ctx.state.plan
    return bool(plan) and all(item.status in ("done_not_fixed", "skipped") for item in plan)


@predicate("booking_confirmed")
def booking_confirmed(ctx: PredicateContext) -> bool:
    """The user picked a slot on a BookingSlots card; code (not the LLM) then calls `book`."""
    return ctx.signals is not None and ctx.signals.booking_slot_id is not None


@predicate("user_satisfied")
def user_satisfied(ctx: PredicateContext) -> bool:
    signals = ctx.signals
    return signals is not None and (signals.feedback == "fixed" or signals.intent == "confirm")


@predicate("user_asked_followup")
def user_asked_followup(ctx: PredicateContext) -> bool:
    return ctx.signals is not None and ctx.signals.intent == "ask_how_to"
