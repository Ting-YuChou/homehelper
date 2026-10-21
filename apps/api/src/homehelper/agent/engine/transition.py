"""Journey Engine (spec §7.4, ADR-002): `transition()` is a pure function of catalog, state, input.

One call handles one user turn:

1. Detect hazards (keywords OR NLU), attach fixed safety templates (spec §8.1).
2. `route()`: keep, start, switch (pausing one level), or resume a journey; or answer a side
   question / off-topic message without changing the step.
3. Apply the input: slot updates, then step effects (confirm/deny, plan item feedback, booking).
4. Journey guardrails, which override step transitions when they fire.
5. Otherwise the current step's transitions, first match wins.

Entering a step follows state-driven transitions eagerly (with the input already consumed) and stops
at a step that waits for the user, an `end` step, or a step with actions. Actions are returned for
the `act` node; after a `system` step's actions ran, call `transition(catalog, state, None)` to
continue from it.
"""

from typing import Literal

from pydantic import BaseModel, Field

from homehelper.agent.engine.loader import JourneyCatalog, slot_values
from homehelper.agent.engine.predicates import (
    PREDICATES,
    PredicateContext,
    unconfirmed_low_confidence,
)
from homehelper.agent.engine.schema import Journey, Step, StepType
from homehelper.agent.engine.signals import TurnInput, TurnSignals, signals_from_input
from homehelper.agent.guardrails.hazards import HazardHit, detect_hazards
from homehelper.agent.guardrails.rules import HAZARD_RULES, MAX_FRUSTRATED_TURNS
from homehelper.agent.guardrails.templates import (
    SCOPE_SIDE_REPLY,
    STEP_TEMPLATES,
    FixedReply,
    safety_reply,
)
from homehelper.agent.state import (
    AgentState,
    Decision,
    DecisionKind,
    PausedJourney,
    PlanItemStatus,
    SlotValue,
)

# Conversation-level appliance context, carried into the next journey on the same appliance.
APPLIANCE_SLOTS = ("appliance_category", "brand", "model_number")
CATEGORY_SLOT = "appliance_category"
# Once a journey works on an appliance, naming another one is a switch, not a correction.
SWITCH_STEP_TYPES: frozenset[StepType] = frozenset({"guide", "inform", "handoff"})

FEEDBACK_STATUS: dict[str, PlanItemStatus] = {
    "fixed": "fixed",
    "not_fixed": "done_not_fixed",
    "cannot_do": "skipped",
}
GUARDRAIL_RULE_IDS = {"max_failed_steps_reached": "G-LOOP-01"}

NOTICE_OFFER_HANDOFF = "G-LOOP-01"  # responder offers a referral
NOTICE_RESUME_PAUSED = "resume_paused"  # responder offers to return to the paused journey

RouteKind = Literal["stay", "start", "switch", "resume", "side_question", "scope_side", "none"]


class Route(BaseModel):
    kind: RouteKind
    journey: str | None = None
    carry_slots: bool = True
    reason: str


class TransitionResult(BaseModel):
    state: AgentState
    actions: list[str] = Field(default_factory=list)  # for the `act` node, in order
    decisions: list[Decision] = Field(default_factory=list)  # also appended to state.decision_log
    fixed_replies: list[FixedReply] = Field(default_factory=list)
    hazards: list[HazardHit] = Field(default_factory=list)
    side_question: bool = False  # answer via inform without changing the step (spec §7.4)
    notices: list[str] = Field(default_factory=list)
    continue_after_actions: bool = False  # run `act`, then call transition(catalog, state, None)

    @property
    def skip_respond(self) -> bool:
        """A fixed template is the whole reply; the LLM responder must not run."""
        return any(reply.replaces_response for reply in self.fixed_replies)


def transition(
    catalog: JourneyCatalog, state: AgentState, turn: TurnInput | None
) -> TransitionResult:
    """Advance the conversation by one turn (or, with `turn=None`, after a system step's actions).

    Pure: the input `state` is not mutated; the new state is in the result.
    """
    run = _Run(catalog, state.model_copy(deep=True))
    if turn is None:
        run.on_continue()
    else:
        run.on_turn(turn)
    return run.result()


def is_ended(journey: Journey, state: AgentState) -> bool:
    return state.step_id is not None and journey.step(state.step_id).type == "end"


def route(catalog: JourneyCatalog, state: AgentState, signals: TurnSignals) -> Route:
    """Decide which journey handles this turn. Pure; `transition` applies the result."""
    active = catalog.journeys.get(state.active_journey) if state.active_journey else None
    target = catalog.for_intent(signals.intent)

    if active is not None and not is_ended(active, state):
        step_type = active.step(state.step_id).type if state.step_id else None
        current = state.slots.get(CATEGORY_SLOT)
        new_category = _category_update(signals)
        if (
            current is not None
            and new_category is not None
            and new_category != current.value
            and step_type in SWITCH_STEP_TYPES
        ):
            return Route(
                kind="switch",
                journey=(target or active).id,
                carry_slots=False,
                reason=f"appliance changed from {current.value} to {new_category}",
            )
        if signals.escalating_hazards and not _has_hazard_guardrail(active):
            return Route(
                kind="switch",
                journey=catalog.hazard_journey,
                reason=f"hazard in {active.id}, which has no hazard guardrail",
            )
        if signals.intent == "out_of_scope" and not signals.escalating_hazards:
            return Route(kind="scope_side", journey=active.id, reason="off-topic during a journey")
        if target is not None and target.id != active.id:
            if signals.intent == "ask_how_to":
                return Route(
                    kind="side_question",
                    journey=active.id,
                    reason=f"how-to question during {active.id}",
                )
            return Route(
                kind="switch",
                journey=target.id,
                reason=f"intent {signals.intent} starts {target.id}",
            )
        return Route(kind="stay", journey=active.id, reason="continue the active journey")

    if signals.escalating_hazards:
        journey = target if target and _has_hazard_guardrail(target) else None
        hazard_journey = journey or catalog[catalog.hazard_journey]
        return Route(
            kind="start", journey=hazard_journey.id, reason="hazard with no running journey"
        )
    if signals.intent == "confirm" and state.paused_journey is not None:
        return Route(
            kind="resume",
            journey=state.paused_journey.journey,
            reason="user agreed to return to the paused journey",
        )
    if target is not None:
        return Route(kind="start", journey=target.id, reason=f"intent {signals.intent}")
    return Route(kind="none", reason=f"no journey handles intent {signals.intent}")


def _has_hazard_guardrail(journey: Journey) -> bool:
    return any(guard.when == "hazard_detected" for guard in journey.guardrails)


def _normalize_enum(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _category_update(signals: TurnSignals) -> str | None:
    for update in signals.slot_updates:
        if update.name == CATEGORY_SLOT:
            return _normalize_enum(update.value)
    return None


class _Run:
    """Mutable working copy for one `transition` call; never escapes it."""

    def __init__(self, catalog: JourneyCatalog, state: AgentState) -> None:
        self.catalog = catalog
        self.state = state
        self.actions: list[str] = []
        self.decisions: list[Decision] = []
        self.fixed_replies: list[FixedReply] = []
        self.hazards: list[HazardHit] = []
        self.side_question = False
        self.notices: list[str] = []

    # --- entry points ---------------------------------------------------------------------

    def on_turn(self, turn: TurnInput) -> None:
        signals = signals_from_input(turn)
        if signals.rejected_action:
            self._log("route", f"ignored card action: {signals.rejected_action}")
        signals = self._detect_hazards(turn, signals)
        if turn.nlu is not None:
            frustrated = turn.nlu.user_sentiment == "frustrated"
            self.state.frustrated_turns = self.state.frustrated_turns + 1 if frustrated else 0

        decided = route(self.catalog, self.state, signals)
        self._apply_route(decided)
        journey = self._journey()
        if decided.kind != "none" and journey is not None:
            self._apply_slot_updates(journey, signals)
            if decided.kind == "stay":
                self._apply_step_effects(journey, signals)
            if not self._guardrails(journey, signals):
                if decided.kind in ("start", "switch"):
                    self._enter(journey, journey.entry_step)
                elif decided.kind == "stay":
                    self._step_transitions(journey, signals)
        self._add_notices()

    def on_continue(self) -> None:
        journey = self._journey()
        if journey is None or self.state.step_id is None or is_ended(journey, self.state):
            return
        if not self._guardrails(journey, None):
            self._step_transitions(journey, None)

    def result(self) -> TransitionResult:
        self.state.decision_log.extend(self.decisions)
        journey = self._journey()
        step = self._current_step(journey)
        return TransitionResult(
            state=self.state,
            actions=self.actions,
            decisions=self.decisions,
            fixed_replies=self.fixed_replies,
            hazards=self.hazards,
            side_question=self.side_question,
            notices=self.notices,
            continue_after_actions=bool(self.actions)
            and step is not None
            and step.type == "system",
        )

    # --- helpers --------------------------------------------------------------------------

    def _journey(self) -> Journey | None:
        if self.state.active_journey is None:
            return None
        return self.catalog[self.state.active_journey]

    def _current_step(self, journey: Journey | None) -> Step | None:
        if journey is None or self.state.step_id is None:
            return None
        return journey.step(self.state.step_id)

    def _log(self, kind: DecisionKind, reason: str, **fields: str | None) -> None:
        self.decisions.append(
            Decision(kind=kind, journey=self.state.active_journey, reason=reason, **fields)
        )

    def _holds(self, journey: Journey, name: str, signals: TurnSignals | None) -> bool:
        return PREDICATES.evaluate(name, PredicateContext(journey, self.state, signals))

    # --- hazards and routing --------------------------------------------------------------

    def _detect_hazards(self, turn: TurnInput, signals: TurnSignals) -> TurnSignals:
        current = self.state.slots.get(CATEGORY_SLOT)
        category = _category_update(signals) or (current.value if current else None)
        nlu_signals = turn.nlu.hazard_signals if turn.nlu else None
        self.hazards = detect_hazards(turn.text, nlu_signals, category=category)
        replied_rules: set[str] = set()
        for hit in self.hazards:
            rule_id = HAZARD_RULES[hit.signal]
            if hit.signal not in self.state.hazard_flags:
                self.state.hazard_flags.append(hit.signal)
            self._log("guardrail", f"{hit.signal} detected ({hit.source})", rule_id=rule_id)
            if rule_id not in replied_rules:
                replied_rules.add(rule_id)
                self.fixed_replies.append(safety_reply(hit.signal))
        return signals.model_copy(update={"hazards": [hit.signal for hit in self.hazards]})

    def _apply_route(self, decided: Route) -> None:
        state = self.state
        match decided.kind:
            case "stay":
                return
            case "none":
                if state.active_journey is None:
                    self._log("route", decided.reason)
                return
            case "side_question":
                self.side_question = True
                self._log("route", decided.reason, from_step=state.step_id, to_step=state.step_id)
                return
            case "scope_side":
                self.fixed_replies.append(SCOPE_SIDE_REPLY)
                self._log("guardrail", decided.reason, rule_id="G-SCOPE-01")
                return
            case "resume":
                paused = state.paused_journey
                assert paused is not None
                state.active_journey = paused.journey
                state.step_id = paused.step_id
                state.slots = paused.slots
                state.plan = paused.plan
                state.plan_cursor = paused.plan_cursor
                state.step_attempts = {}
                state.paused_journey = None
                state.outcome = None
                state.selected_booking_slot = None
                self._log("route", decided.reason, to_step=state.step_id)
                return
            case "switch":
                assert state.active_journey is not None
                if state.paused_journey is not None:
                    self._log("route", f"dropped paused journey {state.paused_journey.journey}")
                state.paused_journey = PausedJourney(
                    journey=state.active_journey,
                    step_id=state.step_id,
                    slots=state.slots,
                    plan=state.plan,
                    plan_cursor=state.plan_cursor,
                ).model_copy(deep=True)
                self._log("route", f"paused {state.active_journey}: {decided.reason}")
        assert decided.journey is not None
        journey = self.catalog[decided.journey]
        carried = (
            {
                name: state.slots[name]
                for name in APPLIANCE_SLOTS
                if name in state.slots and name in journey.slots
            }
            if decided.carry_slots
            else {}
        )
        state.active_journey = journey.id
        state.step_id = None
        state.slots = carried
        state.plan = []
        state.plan_cursor = 0
        state.step_attempts = {}
        state.outcome = None
        state.last_retrieval = None
        state.selected_booking_slot = None
        self._log("route", f"started {journey.id}: {decided.reason}")

    # --- input effects --------------------------------------------------------------------

    def _apply_slot_updates(self, journey: Journey, signals: TurnSignals) -> None:
        for update in signals.slot_updates:
            spec = journey.slots.get(update.name)
            if spec is None or not update.value.strip():
                continue
            value = update.value.strip()
            if spec.type == "enum":
                value = _normalize_enum(value)
                if value not in slot_values(spec.values):
                    self._log(
                        "slot", f"rejected {update.name}={update.value!r}: not an allowed value"
                    )
                    continue
            self.state.slots[update.name] = SlotValue(
                value=value, source="user", confidence=1.0, confirmed=True
            )

    def _apply_step_effects(self, journey: Journey, signals: TurnSignals) -> None:
        step = self._current_step(journey)
        if step is None:
            return
        state = self.state
        if step.type == "confirm" and signals.confirmed is not None:
            pending = unconfirmed_low_confidence(state)
            if signals.confirmed:
                for name in pending:
                    state.slots[name].confirmed = True
            elif pending:
                for name in pending:
                    del state.slots[name]
                self._log("slot", f"dropped denied slots: {', '.join(pending)}")
        elif step.type == "guide" and signals.feedback is not None:
            for item in state.plan:
                if item.status == "presented":
                    item.status = FEEDBACK_STATUS[signals.feedback]
                    break
        elif signals.booking_slot_id is not None:
            if step.type == "handoff":
                state.selected_booking_slot = signals.booking_slot_id
            else:
                self._log("route", f"ignored booking slot selection at {step.type} step {step.id}")

    # --- transitions ----------------------------------------------------------------------

    def _guardrails(self, journey: Journey, signals: TurnSignals | None) -> bool:
        """Evaluate journey guardrails; on a hit, move to its target and return True."""
        if is_ended(journey, self.state):
            return False
        for guard in journey.guardrails:
            if guard.to == self.state.step_id or not self._holds(journey, guard.when, signals):
                continue
            rule_id = GUARDRAIL_RULE_IDS.get(guard.when)
            if guard.when == "hazard_detected" and signals and signals.escalating_hazards:
                rule_id = HAZARD_RULES[signals.escalating_hazards[0]]
            self._log(
                "guardrail",
                f"guardrail {guard.when} overrides step transitions",
                from_step=self.state.step_id,
                to_step=guard.to,
                predicate=guard.when,
                rule_id=rule_id,
            )
            self._enter(journey, guard.to)
            return True
        return False

    def _step_transitions(self, journey: Journey, signals: TurnSignals | None) -> None:
        step = self._current_step(journey)
        if step is None:
            return
        for t in step.transitions:
            if self._holds(journey, t.when, signals):
                self._log(
                    "transition",
                    f"{t.when} holds",
                    from_step=step.id,
                    to_step=t.to,
                    predicate=t.when,
                )
                self._enter(journey, t.to)
                return
        if signals is not None:
            self.state.step_attempts[step.id] = self.state.step_attempts.get(step.id, 0) + 1

    def _enter(self, journey: Journey, step_id: str) -> None:
        """Enter `step_id` and follow state-driven transitions until the chain must stop."""
        for _ in range(len(journey.steps) + 1):
            step = journey.step(step_id)
            self.state.step_id = step.id
            self.state.step_attempts[step.id] = 0
            if step.skip_when and self._holds(journey, step.skip_when, None):
                target = step.transitions[0].to
                self._log(
                    "skip",
                    f"{step.skip_when} holds; skipped to {target}",
                    from_step=step.id,
                    to_step=target,
                    predicate=step.skip_when,
                )
                step_id = target
                continue
            if step.outcome is not None:
                self.state.outcome = step.outcome
            if step.type == "guide":
                self._present_next_item()
            if step.template is not None:
                self.fixed_replies.append(STEP_TEMPLATES[step.template])
            if step.actions:
                self.actions.extend(step.actions)
                return
            if step.type == "end":
                return
            nxt = next((t for t in step.transitions if self._holds(journey, t.when, None)), None)
            if nxt is None:
                return
            self._log(
                "transition",
                f"{nxt.when} holds",
                from_step=step.id,
                to_step=nxt.to,
                predicate=nxt.when,
            )
            step_id = nxt.to
        self._log("transition", f"transition chain limit reached; stopped at {self.state.step_id}")

    def _present_next_item(self) -> None:
        plan = self.state.plan
        if any(item.status == "presented" for item in plan):
            return
        for index, item in enumerate(plan):
            if item.status == "pending":
                item.status = "presented"
                self.state.plan_cursor = index
                return

    def _add_notices(self) -> None:
        journey = self._journey()
        step = self._current_step(journey)
        if step is None:
            return
        if step.type == "end":
            if self.state.paused_journey is not None:
                self.notices.append(NOTICE_RESUME_PAUSED)
        elif self.state.frustrated_turns >= MAX_FRUSTRATED_TURNS and step.type != "handoff":
            self.notices.append(NOTICE_OFFER_HANDOFF)
            self._log("guardrail", "user frustrated for consecutive turns", rule_id="G-LOOP-01")
