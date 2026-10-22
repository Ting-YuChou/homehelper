"""Journey Engine (spec §7.4, ADR-002): `transition()` is a pure function of catalog, state, input.

One call handles one user turn:

1. Detect hazards (keywords OR NLU), attach fixed safety templates (spec §8.1).
2. `route()`: keep, start, switch (setting the active issue aside), or resume a paused issue; or
   answer a side question / off-topic message without changing the step. Issues (ADR-007) are
   tracked in `issues.py`.
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

from homehelper.agent.engine.issues import (
    TOPIC_SLOTS,
    close_issue,
    close_paused,
    find_paused,
    is_issue_journey,
    open_issue,
    pause_active,
    paused_for_category,
    restore,
    summary_outcome,
    sync_active_record,
    take_paused,
)
from homehelper.agent.engine.loader import JourneyCatalog, slot_values
from homehelper.agent.engine.perception import PerceivedSlot
from homehelper.agent.engine.predicates import (
    LOW_CONFIDENCE,
    PREDICATES,
    PredicateContext,
    unconfirmed_low_confidence,
)
from homehelper.agent.engine.profile import link_profile_appliance
from homehelper.agent.engine.schema import Journey, Step, StepType
from homehelper.agent.engine.signals import TurnInput, TurnSignals, signals_from_input
from homehelper.agent.guardrails.hazards import HazardHit, detect_hazards, water_persists
from homehelper.agent.guardrails.rules import (
    ESCALATING_HAZARDS,
    HAZARD_RULES,
    MAX_FRUSTRATED_TURNS,
)
from homehelper.agent.guardrails.templates import (
    MEDIA_UNAVAILABLE_NOTE,
    MEDIA_UNAVAILABLE_REPLY,
    PERSISTING_WATER_REPLY,
    SCOPE_SIDE_REPLY,
    STEP_TEMPLATES,
    UNSUPPORTED_APPLIANCE_REPLY,
    WATER_REMINDER_REPLY,
    FixedReply,
    safety_reply,
)
from homehelper.agent.protocol import Outcome
from homehelper.agent.state import (
    AgentState,
    Decision,
    DecisionKind,
    HazardSignal,
    PausedIssue,
    PlanItemStatus,
    SlotValue,
)
from homehelper.knowledge.schemas import CategoryId

# Conversation-level appliance context, carried into the next journey on the same appliance.
APPLIANCE_SLOTS = ("appliance_category", "brand", "model_number")
CATEGORY_SLOT = "appliance_category"
CATEGORY_VALUES = frozenset(category.value for category in CategoryId)
# Once a journey works on an appliance, naming another one is a switch, not a correction.
SWITCH_STEP_TYPES: frozenset[StepType] = frozenset({"guide", "inform", "handoff"})
# Steps still collecting details: an issue set aside here has barely started.
COLLECT_STEP_TYPES: frozenset[StepType] = frozenset({"collect", "confirm"})
# Questions answered on the side during another journey, without leaving its step (spec §7.4).
SIDE_INTENTS = frozenset({"ask_how_to", "my_appliances", "ask_parts"})
# Side questions answered with tools: they may name another appliance ("is my dryer still under
# warranty?") and still stay on the side. A how-to about another appliance needs its manuals, so
# it starts its own journey.
TOOL_SIDE_INTENTS = frozenset({"my_appliances", "ask_parts"})
# What a side question may fill in while the active issue's details are collected.
SIDE_QUESTION_SLOTS = frozenset({*TOPIC_SLOTS, "error_code"})

FEEDBACK_STATUS: dict[str, PlanItemStatus] = {
    "fixed": "fixed",
    "not_fixed": "done_not_fixed",
    "cannot_do": "skipped",
}
GUARDRAIL_RULE_IDS = {"max_failed_steps_reached": "G-LOOP-01"}

NOTICE_OFFER_HANDOFF = "G-LOOP-01"  # responder offers a referral
NOTICE_RESUME_PAUSED = "resume_paused"  # an issue ended; offer the paused ones (IssuesCard)
NOTICE_REMIND_PAUSED = "remind_paused"  # the user is wrapping up; mention the paused ones once
NOTICE_RESUMED_ISSUE = "resumed_issue"  # back to a paused issue: say where we left off

RouteKind = Literal[
    "stay",
    "start",
    "switch",
    "resume",
    "close",
    "decline",
    "ignore",
    "side_question",
    "scope_side",
    "unsupported_appliance",
    "none",
]


class Route(BaseModel):
    kind: RouteKind
    journey: str | None = None
    issue_id: str | None = None  # for resume / close
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
    run.ensure_active_issue()
    if turn is None:
        run.on_continue()
    else:
        run.on_turn(turn)
    return run.result()


def is_ended(journey: Journey, state: AgentState) -> bool:
    return state.step_id is not None and journey.step(state.step_id).type == "end"


def route(catalog: JourneyCatalog, state: AgentState, signals: TurnSignals) -> Route:
    """Decide which journey (and issue) handles this turn. Pure; `transition` applies the result."""
    active = catalog.journeys.get(state.active_journey) if state.active_journey else None
    target = catalog.for_intent(signals.intent)

    card = _issue_card_route(state, signals)
    if card is not None:
        return card

    if active is not None and not is_ended(active, state):
        step_type = active.step(state.step_id).type if state.step_id else None
        current = state.slots.get(CATEGORY_SLOT)
        new_category = _category_update(signals)
        changed = current is not None and new_category is not None and new_category != current.value
        # Guests have no profile: their `my_appliances` journey answers with the sign-in template.
        tool_side = (
            signals.intent in TOOL_SIDE_INTENTS
            and not signals.escalating_hazards
            and state.profile is not None
        )
        if changed and tool_side and target is not None and target.id != active.id:
            return Route(
                kind="side_question",
                journey=active.id,
                reason=f"{signals.intent} question about the {new_category} during {active.id}",
            )
        if changed and step_type in SWITCH_STEP_TYPES:
            assert current is not None and new_category is not None
            if new_category not in CATEGORY_VALUES:
                return Route(
                    kind="unsupported_appliance",
                    journey=active.id,
                    reason=f"no manuals for {new_category}; staying on {active.id}",
                )
            paused = _resumable(catalog, state, signals, target, new_category)
            if paused is not None:
                return _resume(paused, f"appliance changed back to {new_category}")
            return Route(
                kind="switch",
                journey=(target or active).id,
                carry_slots=False,
                reason=f"appliance changed from {current.value} to {new_category}",
            )
        if changed and step_type in COLLECT_STEP_TYPES:
            assert new_category is not None
            paused = _resumable(catalog, state, signals, target, new_category)
            if paused is not None:
                return _resume(paused, f"the user went back to the {new_category}")
            # Otherwise the new category is a correction of the one being collected.
        if signals.escalating_hazards and not _has_hazard_guardrail(active):
            return Route(
                kind="switch",
                journey=catalog.hazard_journey,
                reason=f"hazard in {active.id}, which has no hazard guardrail",
            )
        if signals.intent == "out_of_scope" and not signals.escalating_hazards:
            return Route(kind="scope_side", journey=active.id, reason="off-topic during a journey")
        if signals.intent == "book_technician" and _has_guardrail(
            active, "user_requested_technician"
        ):
            return Route(kind="stay", journey=active.id, reason="technician requested")
        if target is not None and target.id != active.id:
            if signals.intent in SIDE_INTENTS:
                return Route(
                    kind="side_question",
                    journey=active.id,
                    reason=f"{signals.intent} question during {active.id}",
                )
            return Route(
                kind="switch",
                journey=target.id,
                reason=f"intent {signals.intent} starts {target.id}",
            )
        return Route(kind="stay", journey=active.id, reason="continue the active journey")

    dropped = _dropped_by_name(state, signals)
    if dropped is not None:
        return Route(kind="close", issue_id=dropped.issue_id, reason="the user dropped it by name")
    new_category = _category_update(signals)
    # A goodbye that mentions a paused appliance is not going back to it (the reminder covers it).
    farewell = signals.intent == "small_talk" and not signals.escalating_hazards
    paused = (
        _resumable(catalog, state, signals, target, new_category)
        if new_category and not farewell
        else None
    )
    if signals.escalating_hazards:
        if paused is not None:
            return _resume(paused, f"hazard reported on the {new_category}")
        journey = target if target and _has_hazard_guardrail(target) else None
        hazard_journey = journey or catalog[catalog.hazard_journey]
        return Route(
            kind="start", journey=hazard_journey.id, reason="hazard with no running journey"
        )
    if paused is not None:
        return _resume(paused, f"the user went back to the {new_category}")
    # Only words answer the offer: a `confirm_appliance` button belongs to an earlier question.
    if signals.intent == "confirm" and state.paused_issues and not signals.from_card:
        return _resume(state.paused_issues[-1], "user agreed to return to the paused issue")
    if signals.intent == "deny" and state.paused_issues and not signals.from_card:
        return Route(kind="decline", reason="user declined to return to the paused issues")
    if target is not None:
        return Route(kind="start", journey=target.id, reason=f"intent {signals.intent}")
    problem = catalog.for_intent("report_problem")
    if problem is not None and any(p.name == CATEGORY_SLOT for p in signals.perceived):
        # A photo of an appliance with nothing running: the user wants help with it.
        return Route(kind="start", journey=problem.id, reason="a photo of an appliance")
    return Route(kind="none", reason=f"no journey handles intent {signals.intent}")


def _issue_card_route(state: AgentState, signals: TurnSignals) -> Route | None:
    """IssuesCard buttons. A stale or unknown id changes nothing (it is not a step attempt)."""
    issue_id = signals.resume_issue or signals.close_issue
    if issue_id is None:
        return None
    paused = find_paused(state, issue_id)
    if paused is not None and signals.resume_issue:
        return _resume(paused, "chosen on the issues card")  # its guardrails see any hazard
    if signals.escalating_hazards:
        return None  # the hazard comes first: route the turn as if no card was pressed
    if paused is None:
        return Route(kind="ignore", reason=f"issue {issue_id} is not paused")
    return Route(kind="close", issue_id=issue_id, reason="closed on the issues card")


def _dropped_by_name(state: AgentState, signals: TurnSignals) -> PausedIssue | None:
    """A paused issue the user turns down by naming its appliance ("forget the dishwasher") when
    nothing else is running. Mid-journey a `deny` naming another appliance is ambiguous ("no, I
    meant the dishwasher"), so it resumes as before."""
    if signals.intent != "deny" or signals.from_card or signals.escalating_hazards:
        return None
    if signals.feedback is not None:
        return None
    category = _category_update(signals)
    return paused_for_category(state, category) if category else None


def _resume(paused: PausedIssue, reason: str) -> Route:
    return Route(kind="resume", journey=paused.journey, issue_id=paused.issue_id, reason=reason)


def _resumable(
    catalog: JourneyCatalog,
    state: AgentState,
    signals: TurnSignals,
    target: Journey | None,
    category: str,
) -> PausedIssue | None:
    """A paused issue this turn returns to by naming its appliance (spec §7.4).

    A new symptom or question on that appliance is a new problem, and an intent that belongs to
    another journey starts that journey; a reported hazard always goes back to the paused issue,
    so its guardrail can escalate it.
    """
    paused = paused_for_category(state, category)
    if paused is None:
        return None
    if signals.escalating_hazards:
        return paused if _has_hazard_guardrail(catalog[paused.journey]) else None
    if any(u.name in TOPIC_SLOTS and u.value.strip() for u in signals.slot_updates):
        return None
    if target is not None and target.id != paused.journey:
        return None
    return paused


def _has_hazard_guardrail(journey: Journey) -> bool:
    return _has_guardrail(journey, "hazard_detected")


def _names_other_appliance(state: AgentState, signals: TurnSignals) -> bool:
    named = _category_update(signals)
    current = state.slots.get(CATEGORY_SLOT)
    return named is not None and (current is None or named != current.value)


def _has_guardrail(journey: Journey, when: str) -> bool:
    return any(guard.when == when for guard in journey.guardrails)


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
        self.offer_paused = False  # an issue ended this turn: offer the paused ones
        self.remind_paused = False  # the user is wrapping up: remind them once
        self.hazard_category: str | None = None  # the appliance this turn's hazards are about
        # Unconfirmed slots before the turn: what a confirmation card showed.
        self.shown_for_confirmation: dict[str, SlotValue] = {}

    def ensure_active_issue(self) -> None:
        """State saved before issues existed has an active journey but no issue id."""
        state = self.state
        journey = self._journey()
        if state.active_issue_id is None and journey is not None and is_issue_journey(journey):
            issue_id = open_issue(state, journey.id)
            step = self._current_step(journey)
            if step is not None and step.type == "end" and step.outcome is not None:
                close_issue(state, issue_id, step.outcome)

    # --- entry points ---------------------------------------------------------------------

    def on_turn(self, turn: TurnInput) -> None:
        self.shown_for_confirmation = {
            name: self.state.slots[name].model_copy()
            for name in unconfirmed_low_confidence(self.state)
        }
        signals = signals_from_input(turn)
        if signals.rejected_action:
            self._log("route", f"ignored card action: {signals.rejected_action}")
        signals = self._detect_hazards(turn, signals)
        self._media_failures(turn)
        if turn.action is not None:  # a button press breaks a run of frustrated messages
            self.state.frustrated_turns = 0
        elif turn.nlu is not None:
            frustrated = turn.nlu.user_sentiment == "frustrated"
            self.state.frustrated_turns = self.state.frustrated_turns + 1 if frustrated else 0

        decided = route(self.catalog, self.state, signals)
        self._apply_route(decided)
        journey = self._journey()
        if decided.kind not in ("none", "close", "decline", "ignore") and journey is not None:
            # A side question's details ("do Whirlpool filters fit?") are about the question, not
            # the active issue: they must not change its appliance or its profile link. While
            # the issue's details are being collected, its topic ("it leaks") still counts.
            if decided.kind != "side_question":
                self._apply_slot_updates(journey, signals)
                self._apply_perceived(journey, signals)
                self.decisions.extend(link_profile_appliance(self.state, journey))
            elif self._step_type(journey) in COLLECT_STEP_TYPES and not _names_other_appliance(
                self.state, signals
            ):
                topic = [u for u in signals.slot_updates if u.name in SIDE_QUESTION_SLOTS]
                self._apply_slot_updates(
                    journey, signals.model_copy(update={"slot_updates": topic})
                )
            if decided.kind == "stay":
                self._apply_step_effects(journey, signals)
            if not self._guardrails(journey, signals):
                if decided.kind in ("start", "switch"):
                    self._enter(journey, journey.entry_step)
                elif decided.kind == "stay":
                    self._step_transitions(journey, signals)
                elif decided.kind == "resume" and self._step_type(journey) in COLLECT_STEP_TYPES:
                    # The details may be complete now; move on as a fresh turn would.
                    self._step_transitions(journey, None)
        if signals.escalating_hazards:
            if signals.close_issue and find_paused(self.state, signals.close_issue):
                # The hazard was routed first; the close the user pressed still applies.
                take_paused(self.state, signals.close_issue)
                close_issue(self.state, signals.close_issue, "abandoned")
                self._log("route", f"closed {signals.close_issue} (abandoned): issues card")
            self._close_paused_after_hazard(signals)
        if signals.intent == "small_talk":
            step_type = self._step_type(journey)
            self.remind_paused = step_type is None or step_type == "end"
        self._add_notices()

    def on_continue(self) -> None:
        journey = self._journey()
        if journey is None or self.state.step_id is None or is_ended(journey, self.state):
            return
        if not self._guardrails(journey, None):
            self._step_transitions(journey, None)

    def result(self) -> TransitionResult:
        state = self.state
        journey = self._journey()
        step = self._current_step(journey)
        sync_active_record(state)
        state.outcome = summary_outcome(state, step.outcome if step else None)
        replaced = any(reply.replaces_response for reply in self.fixed_replies)
        if state.paused_issues and not replaced:
            if self.offer_paused:
                self.notices.append(NOTICE_RESUME_PAUSED)
            elif self.remind_paused and not state.paused_reminder_used:
                self.notices.append(NOTICE_REMIND_PAUSED)
                state.paused_reminder_used = True
        state.decision_log.extend(self.decisions)
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

    def _step_type(self, journey: Journey | None) -> StepType | None:
        step = self._current_step(journey)
        return step.type if step else None

    def _log(self, kind: DecisionKind, reason: str, **fields: str | None) -> None:
        self.decisions.append(
            Decision(kind=kind, journey=self.state.active_journey, reason=reason, **fields)
        )

    def _holds(self, journey: Journey, name: str, signals: TurnSignals | None) -> bool:
        return PREDICATES.evaluate(name, PredicateContext(journey, self.state, signals))

    # --- hazards and routing --------------------------------------------------------------

    def _detect_hazards(self, turn: TurnInput, signals: TurnSignals) -> TurnSignals:
        current = self.state.slots.get(CATEGORY_SLOT)
        # On a card resume the turn is about the resumed issue's appliance.
        resumed = find_paused(self.state, signals.resume_issue) if signals.resume_issue else None
        about = (resumed.slots.get(CATEGORY_SLOT) if resumed else None) or current
        category = _category_update(signals) or (about.value if about else None)
        nlu_signals = turn.nlu.hazard_signals if turn.nlu else None
        media_signals = turn.media.hazard_signals if turn.media else None
        self.hazards = detect_hazards(
            turn.text, nlu_signals, category=category, media_signals=media_signals
        )
        self.hazard_category = category
        replied_rules: set[str] = set()
        persisting: list[HazardSignal] = []
        for hit in self.hazards:
            rule_id = HAZARD_RULES[hit.signal]
            if hit.signal not in self.state.hazard_flags:
                self.state.hazard_flags.append(hit.signal)
            self._log("guardrail", f"{hit.signal} detected ({hit.source})", rule_id=rule_id)
            reply = safety_reply(hit.signal)
            if hit.signal not in ESCALATING_HAZARDS:
                # G-SAFE-05: the power-off warning is given once per problem; users keep
                # mentioning the water and the cord while they follow it, so later mentions get
                # a one-line reminder. Water that is *still* reaching electricity after the
                # warning means the hazard persists: DIY stops and the journey escalates.
                # Escalating hazards answer every time.
                journey = self._journey()
                switched = (
                    category is not None and current is not None and category != current.value
                ) or resumed is not None
                # Another appliance mid-journey is a new problem: it gets its own warning.
                ongoing = journey is not None and not is_ended(journey, self.state) and not switched
                if not (self.state.water_warning_given and ongoing):
                    self.state.water_warning_given = True
                elif water_persists(turn.text):
                    persisting.append(hit.signal)
                    reply = PERSISTING_WATER_REPLY
                    self._log(
                        "guardrail", f"{hit.signal} persists after the warning", rule_id=rule_id
                    )
                else:
                    reply = WATER_REMINDER_REPLY
            if rule_id not in replied_rules:
                replied_rules.add(rule_id)
                self.fixed_replies.append(reply)
        return signals.model_copy(
            update={"hazards": [hit.signal for hit in self.hazards], "persisting": persisting}
        )

    def _close_paused_after_hazard(self, signals: TurnSignals) -> None:
        """DIY help has ended for that appliance: its paused issues must not come back with
        steps. A gas smell, or a hazard on an unknown appliance, ends all of them."""
        # An issues-card turn has no NLU and moves between issues, so a hazard typed with it may
        # be about any appliance. (A step-result card is about the active one.)
        switching_card = bool(signals.resume_issue or signals.close_issue)
        unknown = "gas_smell" in signals.escalating_hazards or switching_card
        category = None if unknown else self.hazard_category
        for issue_id in close_paused(self.state, category, "escalated"):
            self._log(
                "route", f"closed {issue_id} (escalated): hazard {signals.escalating_hazards[0]}"
            )

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
            case "unsupported_appliance":
                self.fixed_replies.append(UNSUPPORTED_APPLIANCE_REPLY)
                self._log("guardrail", decided.reason, rule_id="G-SCOPE-01")
                return
            case "ignore":
                self._log("route", f"ignored card action: {decided.reason}")
                return
            case "decline":
                state.paused_reminder_used = True
                self._log("route", decided.reason)
                return
            case "close":
                assert decided.issue_id is not None
                take_paused(state, decided.issue_id)
                close_issue(state, decided.issue_id, "abandoned")
                self._log("route", f"closed {decided.issue_id} (abandoned): {decided.reason}")
                journey = self._journey()
                if journey is None or is_ended(journey, state):
                    self.offer_paused = True  # offer the ones still paused
                return
            case "resume":
                assert decided.issue_id is not None
                # Take it out first, so setting the active issue aside cannot evict it.
                paused = take_paused(state, decided.issue_id)
                self._set_aside(f"back to {paused.issue_id}")
                restore(state, paused)
                state.paused_reminder_used = False
                # The paused problem's warning was not saved: warn again rather than assume.
                state.water_warning_given = any(
                    h.signal == "water_near_electric" for h in self.hazards
                )
                self.notices.append(NOTICE_RESUMED_ISSUE)
                self._log(
                    "route", f"resumed {paused.issue_id}: {decided.reason}", to_step=state.step_id
                )
                return
            case "switch":
                assert state.active_journey is not None
                self._set_aside(decided.reason)
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
        state.active_issue_id = open_issue(state, journey.id) if is_issue_journey(journey) else None
        state.step_id = None
        state.slots = carried
        state.plan = []
        state.plan_cursor = 0
        state.step_attempts = {}
        state.last_retrieval = None
        if "appliance_category" not in carried:
            state.appliance_id = None  # the same appliance keeps its link across journeys
        state.selected_booking_slot = None
        state.offered_slots = []
        # A new problem gets its own warning (hazards are detected before routing, so a warning
        # given on this very turn counts for the journey it starts).
        state.water_warning_given = any(h.signal == "water_near_electric" for h in self.hazards)
        issue = f" as {state.active_issue_id}" if state.active_issue_id else ""
        self._log("route", f"started {journey.id}{issue}: {decided.reason}")

    def _set_aside(self, reason: str) -> None:
        """Make room for another issue (spec §7.4). An unfinished issue is paused; one that
        already has its answer (an `inform` or `handoff` step) is closed with that outcome; one
        still collecting details is closed as `abandoned`."""
        state = self.state
        journey = self._journey()
        step = self._current_step(journey)
        issue_id = state.active_issue_id
        if journey is None or issue_id is None or step is None or step.type == "end":
            return
        if step.outcome is not None or step.type in COLLECT_STEP_TYPES:
            outcome = step.outcome or "abandoned"
            sync_active_record(state)
            close_issue(state, issue_id, outcome)
            self._log("route", f"closed {issue_id} ({outcome}): {reason}")
            return
        for dropped in pause_active(state):
            self._log("route", f"closed {dropped} (abandoned): too many paused issues")
        self._log("route", f"paused {issue_id}: {reason}")

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

    def _media_failures(self, turn: TurnInput) -> None:
        """M-MEDIA-01: say so when a photo or video couldn't be analyzed, without blocking."""
        media = turn.media
        if media is None or not media.failures:
            return
        alone = not (turn.text or "").strip() and turn.action is None and media.analyzed == 0
        self.fixed_replies.append(MEDIA_UNAVAILABLE_REPLY if alone else MEDIA_UNAVAILABLE_NOTE)
        self._log(
            "guardrail", f"media analysis failed: {', '.join(media.failures)}", rule_id="M-MEDIA-01"
        )

    def _apply_perceived(self, journey: Journey, signals: TurnSignals) -> None:
        """Slots seen in photos and videos (spec §11.2): kept with the model's confidence and
        unconfirmed, so the `confirm` step asks about the uncertain ones."""
        typed = {u.name: u.value for u in signals.slot_updates if u.value.strip()}
        has_confirm = any(step.type == "confirm" for step in journey.steps)
        working = self._step_type(journey) in SWITCH_STEP_TYPES
        # The appliance the user means: what they typed now, what they said before, or the one
        # being worked on. A photo of another appliance says nothing about it, and doesn't
        # switch to the other one either; words do (spec §7.4).
        current = self.state.slots.get(CATEGORY_SLOT)
        meant = (
            _normalize_enum(typed[CATEGORY_SLOT])
            if CATEGORY_SLOT in typed
            else current.value
            if current is not None and (working or current.source == "user")
            else None
        )
        shown = next((p for p in signals.perceived if p.name == CATEGORY_SLOT), None)
        if shown is not None and meant is not None and _normalize_enum(shown.value) != meant:
            self._log("slot", f"ignored a photo of a {shown.value!r}: the user means the {meant}")
            return
        # Another brand than the user's: its model number belongs to some other unit.
        brand = self.state.slots.get("brand")
        user_brand = typed.get("brand") or (
            brand.value if brand is not None and brand.source == "user" else None
        )
        shown_brand = next((p.value for p in signals.perceived if p.name == "brand"), None)
        other_unit = bool(
            user_brand
            and shown_brand
            and _normalize_enum(user_brand) != _normalize_enum(shown_brand)
        )
        for seen in signals.perceived:
            if other_unit and seen.name == "model_number":
                self._log("slot", f"ignored the photo's model number: it shows a {shown_brand}")
                continue
            spec = journey.slots.get(seen.name)
            if spec is None:
                continue
            value = seen.value.strip()
            if spec.type == "enum":
                value = _normalize_enum(value)
                if value not in slot_values(spec.values):
                    self._log("slot", f"rejected {seen.name}={seen.value!r} from a photo")
                    continue
            current = self.state.slots.get(seen.name)
            if self._keep_current(seen, value, current, typed, working):
                continue
            if seen.confidence < LOW_CONFIDENCE and not has_confirm:
                self._log(
                    "slot",
                    f"dropped {seen.name} from a photo: confidence {seen.confidence:.2f} and no "
                    "confirm step",
                )
                continue
            self.state.slots[seen.name] = SlotValue(
                value=value, source=seen.source, confidence=seen.confidence, confirmed=False
            )

    def _keep_current(
        self,
        seen: PerceivedSlot,
        value: str,
        current: SlotValue | None,
        typed: dict[str, str],
        working: bool,
    ) -> bool:
        """Whether what the conversation already has wins over the photo."""
        if seen.name in typed:
            if _normalize_enum(typed[seen.name]) != _normalize_enum(value):
                self._log("slot", f"kept the typed {seen.name}; the photo showed {value!r}")
            return True
        if current is None or (current.value == value and current.source == seen.source):
            return False
        if working and seen.name in APPLIANCE_SLOTS and current.source != "profile":
            self._log("slot", f"ignored {seen.name}={value!r} from a photo during this step")
            return True
        if current.confirmed and current.source != "profile":
            # What the user said, or confirmed on a card, stands.
            if current.value != value:
                self._log("slot", f"kept the user's {seen.name}; the photo showed {value!r}")
            return True
        return False

    def _apply_step_effects(self, journey: Journey, signals: TurnSignals) -> None:
        step = self._current_step(journey)
        if step is None:
            return
        state = self.state
        if step.type == "confirm" and signals.confirmed is not None:
            # The yes or no answers the card the user saw: values that changed this turn (a new
            # photo sent with the answer) stay unconfirmed and get their own question.
            pending = [
                name
                for name, shown in self.shown_for_confirmation.items()
                if state.slots.get(name) == shown
            ]
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
            offered = {slot.slot_id for slot in state.offered_slots}
            if step.type == "handoff" and signals.booking_slot_id in offered:
                state.selected_booking_slot = signals.booking_slot_id
            else:
                self._log(
                    "route",
                    f"ignored booking slot {signals.booking_slot_id!r} at {step.type} step "
                    f"{step.id}: not one of the offered slots",
                )

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
            if step.skip_when and step.skip_to and self._holds(journey, step.skip_when, None):
                target = step.skip_to
                self._log(
                    "skip",
                    f"{step.skip_when} holds; skipped to {target}",
                    from_step=step.id,
                    to_step=target,
                    predicate=step.skip_when,
                )
                step_id = target
                continue
            if step.type == "end":
                self._end_issue(step.outcome)
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

    def _end_issue(self, outcome: Outcome | None) -> None:
        if self.state.active_issue_id is not None and outcome is not None:
            close_issue(self.state, self.state.active_issue_id, outcome)
        self.state.paused_reminder_used = False
        self.offer_paused = True

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
        if step is None or step.type == "end":
            return
        if self.state.frustrated_turns >= MAX_FRUSTRATED_TURNS and step.type != "handoff":
            self.notices.append(NOTICE_OFFER_HANDOFF)
            self._log("guardrail", "user frustrated for consecutive turns", rule_id="G-LOOP-01")
