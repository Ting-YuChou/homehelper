"""Named predicates referenced from journey YAML (spec §7.1). YAML holds names, never expressions.

A predicate is a pure function of `PredicateContext`. `signals` is None once the turn's input has
been consumed by a transition, so input-driven predicates fire at most once per turn while
state-driven ones (e.g. `required_slots_filled`) keep chaining through steps.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from homehelper.agent.engine.perception import LOW_CONFIDENCE
from homehelper.agent.engine.schema import Journey
from homehelper.agent.engine.signals import TurnSignals
from homehelper.agent.guardrails.plan import POWER_OFF_RULE
from homehelper.agent.guardrails.rules import MAX_FAILED_STEPS
from homehelper.agent.state import AgentState, SlotValue
from homehelper.knowledge.features import BADGE_SLOT, TRAIT_SLOT_PREFIX
from homehelper.knowledge.model_numbers import normalize_model


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


def has_open_item(state: AgentState) -> bool:
    """A step still to try, or the one shown and not answered yet (a diagnosis repeated
    midway keeps it)."""
    return any(item.status in ("pending", "presented") for item in state.plan)


def failed_step_count(state: AgentState) -> int:
    return sum(
        1
        for item in state.plan
        if item.status in ("done_not_fixed", "skipped") and item.safety_rule is None
    )


def slot_traits(state: AgentState) -> dict[str, str]:
    """What the user says the appliance looks like, by trait name (`trait_<name>` slots)."""
    return {
        name.removeprefix(TRAIT_SLOT_PREFIX): slot.value
        for name, slot in state.slots.items()
        if name.startswith(TRAIT_SLOT_PREFIX)
    }


def usable_model(slot: SlotValue | None) -> str | None:
    """A model number the user gave, or one a photo showed clearly enough."""
    if slot is None or (not slot.confirmed and slot.confidence < LOW_CONFIDENCE):
        return None
    return slot.value


def identification_changed_since_plan(state: AgentState) -> bool:
    """The details that tell manuals apart differ from those the plan was built on: a new model
    number, or (without one) a new trait or badge."""
    basis = state.plan_basis
    if basis is None:
        return False
    model = usable_model(state.slots.get("model_number"))
    if model is not None and normalize_model(model) != normalize_model(basis.model_number or ""):
        return True
    if basis.scope == "model":
        return False
    brand = state.slots.get("brand")
    if (brand.value.strip().lower() if brand else None) != (basis.brand or None):
        return True  # a brand given or corrected: other candidates
    badge = state.slots.get(BADGE_SLOT)
    return slot_traits(state) != basis.traits or (badge.value if badge else None) != basis.badge


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
    """A yes that settled everything; details that arrived with it are asked about next."""
    return (
        ctx.signals is not None
        and ctx.signals.confirmed is True
        and not unconfirmed_low_confidence(ctx.state)
    )


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
    return has_open_item(ctx.state)


@predicate("plan_unavailable")
def plan_unavailable(ctx: PredicateContext) -> bool:
    """No usable plan: nothing retrieved, or post-processing removed every item."""
    return not has_open_item(ctx.state)


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


@predicate("only_powered_steps_left")
def only_powered_steps_left(ctx: PredicateContext) -> bool:
    """G-SAFE-08: nothing left to try, and some steps were skipped because they need the power
    the user was told to keep off. The handoff says so instead of "the steps didn't help"."""
    plan = ctx.state.plan
    return (
        bool(plan)
        and not any(item.status in ("pending", "presented") for item in plan)
        and any(item.safety_rule == POWER_OFF_RULE for item in plan)
    )


@predicate("plan_exhausted")
def plan_exhausted(ctx: PredicateContext) -> bool:
    """Every item was tried (or skipped) and none fixed the problem."""
    plan = ctx.state.plan
    return bool(plan) and all(item.status in ("done_not_fixed", "skipped") for item in plan)


@predicate("booking_confirmed")
def booking_confirmed(ctx: PredicateContext) -> bool:
    """The user picked one of the offered slots on a BookingSlots card; code (not the LLM) then
    calls `book`. A stale or made-up slot id is not a booking."""
    if ctx.signals is None or ctx.signals.booking_slot_id is None:
        return False
    return ctx.signals.booking_slot_id in {slot.slot_id for slot in ctx.state.offered_slots}


@predicate("user_satisfied")
def user_satisfied(ctx: PredicateContext) -> bool:
    signals = ctx.signals
    return signals is not None and (signals.feedback == "fixed" or signals.intent == "confirm")


@predicate("no_profile")
def no_profile(ctx: PredicateContext) -> bool:
    """A guest, or the profile could not be read: nothing to look up for this user."""
    return ctx.state.profile is None


@predicate("user_asked_followup")
def user_asked_followup(ctx: PredicateContext) -> bool:
    return ctx.signals is not None and ctx.signals.intent == "ask_how_to"


@predicate("identification_changed")
def identification_changed(ctx: PredicateContext) -> bool:
    """This turn told the manuals apart better than the plan's basis (ADR-013): diagnose again,
    keeping the steps already tried."""
    return ctx.signals is not None and identification_changed_since_plan(ctx.state)


@predicate("identification_changed_after_no_plan")
def identification_changed_after_no_plan(ctx: PredicateContext) -> bool:
    """As `identification_changed`, at a handoff that came only from having no plan: the
    model's own manual may cover the problem. A hazard (ever, in this conversation), failed
    steps or a request for a technician keep the handoff."""
    signals = ctx.signals
    if not identification_changed(ctx) or signals is None:
        return False
    if ctx.state.hazard_flags or signals.hazards or signals.intent == "book_technician":
        return False
    state = ctx.state
    into = next((d for d in reversed(state.decision_log) if d.to_step == state.step_id), None)
    return into is not None and into.predicate == "plan_unavailable"
