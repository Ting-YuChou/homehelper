import pytest
from pydantic import ValidationError

from homehelper.agent.engine import (
    JourneyCatalog,
    TurnInput,
    default_catalog,
    parse_journey,
    route,
    signals_from_input,
    transition,
)
from homehelper.agent.engine.transition import (
    NOTICE_OFFER_HANDOFF,
    NOTICE_RESUME_PAUSED,
    NOTICE_RESUMED_ISSUE,
)
from homehelper.agent.guardrails.rules import MAX_FAILED_STEPS
from homehelper.agent.guardrails.templates import WATER_REMINDER_REPLY
from homehelper.agent.state import AgentState, OfferedSlot, PausedIssue, UserContext
from homehelper.channels.events import InboundMessage, StructuredAction
from tests.unit.agent.helpers import (
    DIAGNOSE_ACTIONS,
    new_state,
    plan,
    press,
    run_turn,
    say,
    vision_slot,
)

DISHWASHER = {"appliance_category": "dishwasher", "symptom": "won't drain"}


@pytest.fixture
def catalog() -> JourneyCatalog:
    return default_catalog()


def start_guide(catalog: JourneyCatalog, n_items: int = 3) -> AgentState:
    result = run_turn(
        catalog,
        new_state(),
        say("report_problem", "My dishwasher won't drain", slots=DISHWASHER),
        plan(n_items),
    )
    assert result.state.step_id == "guide"
    return result.state


# --- main paths ---------------------------------------------------------------------------


def test_fixed_path_walks_gather_to_resolved(catalog: JourneyCatalog) -> None:
    first = transition(
        catalog, new_state(), say("report_problem", "My dishwasher won't drain", slots=DISHWASHER)
    )
    assert first.state.active_journey == "troubleshoot"
    assert first.state.step_id == "diagnose"
    assert first.actions == DIAGNOSE_ACTIONS
    assert first.continue_after_actions
    steps = [(d.from_step, d.to_step, d.predicate) for d in first.decisions if d.kind != "route"]
    assert steps == [
        ("gather", "confirm_appliance", "required_slots_filled"),
        ("confirm_appliance", "diagnose", "no_unconfirmed_low_confidence_slots"),
    ]
    assert first.decisions[1].kind == "transition"
    assert first.decisions[2].kind == "skip"

    state = start_guide(catalog)
    assert [item.status for item in state.plan] == ["presented", "pending", "pending"]

    result = transition(catalog, state, press("step_result", "not_fixed"))
    assert result.state.step_id == "guide"
    assert result.state.plan_cursor == 1
    assert [item.status for item in result.state.plan] == ["done_not_fixed", "presented", "pending"]

    result = transition(
        catalog, result.state, say("step_feedback", "That did it!", step_feedback="fixed")
    )
    assert result.state.step_id == "resolved"
    assert result.state.outcome == "resolved"
    assert result.actions == ["mcp:user_profile.add_repair_record"]
    assert not result.continue_after_actions
    assert result.state.plan[1].status == "fixed"
    last = result.state.decision_log[-1]
    assert (last.from_step, last.to_step, last.predicate) == (
        "guide",
        "resolved",
        "user_reports_fixed",
    )


def test_plan_exhausted_escalates_then_booking_ends(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog, n_items=2)
    state = transition(catalog, state, press("step_result", "not_fixed")).state
    result = transition(catalog, state, press("step_result", "cannot_do"))
    assert result.state.step_id == "escalate"
    assert result.state.outcome == "escalated"
    assert [item.status for item in result.state.plan] == ["done_not_fixed", "skipped"]
    assert result.decisions[-1].predicate == "plan_exhausted"

    assert result.actions == ["mcp:service_booking.list_slots"]

    # Only an offered slot (set by code from `list_slots`) can be booked.
    stale = transition(catalog, result.state, press("select_booking_slot", "slot-42"))
    assert stale.state.step_id == "escalate"
    assert stale.state.selected_booking_slot is None
    assert "not one of the offered slots" in stale.decisions[0].reason
    result.state.offered_slots = [
        OfferedSlot(slot_id="slot-42", starts_at="2026-10-21T09:00:00Z", technician="Ann (Fix Co)")
    ]
    booked = transition(catalog, result.state, press("select_booking_slot", "slot-42"))
    assert booked.state.step_id == "escalated_end"
    assert booked.state.selected_booking_slot == "slot-42"
    assert booked.actions == ["mcp:service_booking.book"]
    assert booked.state.outcome == "escalated"


def test_hazard_in_first_message_escalates_at_once(catalog: JourneyCatalog) -> None:
    result = transition(
        catalog,
        new_state(),
        say(
            "report_problem",
            "There's smoke coming out of my dryer",
            slots={"appliance_category": "dryer"},
        ),
    )
    assert result.state.active_journey == "troubleshoot"
    assert result.state.step_id == "escalate"
    assert result.state.outcome == "escalated"
    assert result.state.hazard_flags == ["smoke_or_burning"]
    assert result.skip_respond
    assert [r.rule_id for r in result.fixed_replies] == ["G-SAFE-02"]
    assert result.fixed_replies[0].card is not None
    guard = next(d for d in result.decisions if d.predicate == "hazard_detected")
    assert (guard.kind, guard.to_step, guard.rule_id) == ("guardrail", "escalate", "G-SAFE-02")
    assert "gather" not in {d.to_step for d in result.decisions}


def test_nlu_hazard_signal_alone_escalates_mid_guide(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    result = transition(
        catalog,
        state,
        say("other", "it smells weird near the back", hazard_signals=["gas_smell"]),
    )
    assert result.state.step_id == "escalate"
    assert result.hazards[0].source == "nlu"
    assert result.fixed_replies[0].rule_id == "G-SAFE-01"


def test_user_denies_confirmation_returns_to_gather(catalog: JourneyCatalog) -> None:
    state = new_state(slots={"appliance_category": vision_slot("washing_machine")})
    result = transition(
        catalog, state, say("report_problem", "It won't spin", slots={"symptom": "won't spin"})
    )
    # a vision candidate set before any journey started is carried into it
    assert result.state.step_id == "confirm_appliance"

    state = new_state(
        active_journey="troubleshoot",
        step_id="gather",
        slots={"appliance_category": vision_slot("washing_machine")},
    )
    result = transition(
        catalog, state, say("report_problem", "It won't spin", slots={"symptom": "won't spin"})
    )
    assert result.state.step_id == "confirm_appliance"
    assert not result.actions

    denied = transition(catalog, result.state, press("confirm_appliance", "no"))
    assert denied.state.step_id == "gather"
    assert "appliance_category" not in denied.state.slots
    assert denied.decisions[0].kind == "slot"
    assert denied.decisions[-1].predicate == "user_denied"

    corrected = transition(
        catalog, denied.state, say("other", "It's a dryer", slots={"appliance_category": "Dryer"})
    )
    assert corrected.state.step_id == "diagnose"
    assert corrected.state.slots["appliance_category"].value == "dryer"


def test_user_confirms_low_confidence_slot(catalog: JourneyCatalog) -> None:
    state = new_state(
        active_journey="troubleshoot",
        step_id="confirm_appliance",
        slots={"appliance_category": vision_slot("dryer"), "symptom": vision_slot("noisy", 1.0)},
    )
    result = transition(catalog, state, say("confirm", "yes that's right"))
    assert result.state.step_id == "diagnose"
    assert result.state.slots["appliance_category"].confirmed


def test_correction_at_confirm_step_moves_on(catalog: JourneyCatalog) -> None:
    state = new_state(
        active_journey="troubleshoot",
        step_id="confirm_appliance",
        slots={"appliance_category": vision_slot("dryer"), "symptom": vision_slot("noisy", 1.0)},
    )
    result = transition(
        catalog, state, say("other", slots={"appliance_category": "washing machine"})
    )
    assert result.state.step_id == "diagnose"
    assert result.decisions[-1].predicate == "no_unconfirmed_low_confidence_slots"


# --- guardrails ---------------------------------------------------------------------------


def test_max_failed_steps_overrides_step_transition(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog, n_items=MAX_FAILED_STEPS + 1)
    for _ in range(MAX_FAILED_STEPS - 1):
        state = transition(catalog, state, press("step_result", "not_fixed")).state
        assert state.step_id == "guide"
    result = transition(catalog, state, press("step_result", "not_fixed"))
    assert result.state.step_id == "escalate"
    guard = result.decisions[-1]
    assert (guard.kind, guard.predicate, guard.rule_id) == (
        "guardrail",
        "max_failed_steps_reached",
        "G-LOOP-01",
    )


def test_user_asks_for_technician(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    result = transition(catalog, state, say("book_technician", "just send someone"))
    assert result.state.step_id == "escalate"
    # already escalated: the guardrail does not re-enter its own target
    again = transition(catalog, result.state, say("book_technician", "please"))
    assert again.state.step_id == "escalate"
    assert not again.decisions


def test_water_near_electric_prefixes_reply_and_continues(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    result = transition(
        catalog,
        state,
        say("step_feedback", "There's water pooling near the outlet", step_feedback="not_fixed"),
    )
    assert result.state.step_id == "guide"
    assert result.state.hazard_flags == ["water_near_electric"]
    assert [r.rule_id for r in result.fixed_replies] == ["G-SAFE-05"]
    assert not result.skip_respond
    # Water still reaching the outlet after the warning: the hazard persists, so DIY stops.
    again = transition(
        catalog,
        result.state,
        say("step_feedback", "I switched off the breaker but the outlet is still wet"),
    )
    (reply,) = again.fixed_replies
    assert (reply.rule_id, reply.replaces_response) == ("G-SAFE-05", True)
    assert "stop the repair" in reply.text
    assert again.state.step_id == "escalate"
    assert again.state.outcome == "escalated"
    assert any(
        d.reason == "water_near_electric persists after the warning" for d in again.decisions
    )


@pytest.mark.parametrize(
    "text",
    [
        "OK, I turned the breaker off and mopped up the water",
        "Done. The cord is unplugged and I wiped the water up. What next?",
    ],
)
def test_following_the_water_warning_does_not_escalate(catalog: JourneyCatalog, text: str) -> None:
    state = start_guide(catalog)
    warned = transition(catalog, state, say("other", "Water is dripping near the outlet"))
    assert [r.rule_id for r in warned.fixed_replies] == ["G-SAFE-05"]
    after = transition(catalog, warned.state, say("other", text))
    # A one-line reminder instead of the whole warning, and the step goes on.
    assert after.fixed_replies == [WATER_REMINDER_REPLY]
    assert not after.skip_respond
    assert after.state.step_id == "guide"


def test_water_warning_in_the_first_message_counts_for_its_journey(
    catalog: JourneyCatalog,
) -> None:
    first = transition(
        catalog,
        new_state(),
        say("report_problem", "My washer leaks water onto the outlet", slots=DISHWASHER),
    )
    assert [r.rule_id for r in first.fixed_replies] == ["G-SAFE-05"]
    assert first.state.water_warning_given
    later = transition(
        catalog, first.state, say("other", "The outlet near the washer is still wet")
    )
    assert later.state.step_id == "escalate"


def test_a_new_problem_gets_its_own_water_warning(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    warned = transition(catalog, state, say("other", "Water is dripping near the outlet"))
    warned.state.step_id, warned.state.outcome = "resolved", "resolved"
    new = transition(
        catalog,
        warned.state,
        say(
            "report_problem",
            "Now my fridge is still leaking water near the power strip",
            slots={"appliance_category": "refrigerator", "symptom": "leaking"},
        ),
    )
    (reply,) = new.fixed_replies
    assert not reply.replaces_response  # the first warning for this problem, not escalation
    assert new.state.step_id != "escalate"


def test_another_appliance_mid_journey_gets_its_own_water_warning(
    catalog: JourneyCatalog,
) -> None:
    state = start_guide(catalog)
    warned = transition(catalog, state, say("other", "Water is dripping near the outlet"))
    switched = transition(
        catalog,
        warned.state,
        say(
            "report_problem",
            "Also my fridge is still leaking water near the power strip",
            slots={"appliance_category": "refrigerator", "symptom": "leaking"},
        ),
    )
    (reply,) = switched.fixed_replies
    assert not reply.replaces_response  # the fridge's first warning, not an escalation
    assert switched.state.active_journey == "troubleshoot"
    assert switched.state.step_id != "escalate"


def test_repeated_hazard_rule_gets_one_template(catalog: JourneyCatalog) -> None:
    result = transition(catalog, new_state(), say("report_problem", "smoke and sparks everywhere"))
    assert [h.signal for h in result.hazards] == ["smoke_or_burning", "sparks"]
    assert [r.rule_id for r in result.fixed_replies] == ["G-SAFE-02"]


def test_frustration_notice_after_two_turns(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    first = transition(catalog, state, say("other", "ugh", user_sentiment="frustrated"))
    assert NOTICE_OFFER_HANDOFF not in first.notices
    second = transition(catalog, first.state, say("other", "ugh!!", user_sentiment="frustrated"))
    assert NOTICE_OFFER_HANDOFF in second.notices
    assert second.decisions[-1].rule_id == "G-LOOP-01"
    calm = transition(catalog, second.state, say("other", "ok"))
    assert calm.state.frustrated_turns == 0
    pressed = transition(catalog, second.state, press("step_result", "not_fixed"))
    assert pressed.state.frustrated_turns == 0
    assert NOTICE_OFFER_HANDOFF not in pressed.notices


def test_unsupported_appliance_mid_journey_stays_on_step(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    result = transition(
        catalog,
        state,
        say("report_problem", "my oven is also broken", slots={"appliance_category": "oven"}),
    )
    assert not result.state.paused_issues
    assert result.state.step_id == "guide"
    assert result.state.plan == state.plan
    assert result.state.slots["appliance_category"].value == "dishwasher"
    assert [r.rule_id for r in result.fixed_replies] == ["G-SCOPE-01"]
    assert not result.skip_respond
    assert "no manuals for oven" in result.decisions[0].reason


def test_fixed_replies_are_immutable(catalog: JourneyCatalog) -> None:
    result = transition(catalog, new_state(), say("out_of_scope", "tell me a joke"))
    with pytest.raises(ValidationError):
        result.fixed_replies[0].text = "changed"


def test_hazard_in_journey_without_hazard_guardrail_switches(catalog: JourneyCatalog) -> None:
    quiet = parse_journey(
        {
            "id": "chat",
            "version": 1,
            "goal": "Chat.",
            "entry_intents": ["small_talk"],
            "steps": [
                {
                    "id": "talk",
                    "type": "inform",
                    "transitions": [{"when": "user_satisfied", "to": "bye"}],
                },
                {"id": "bye", "type": "end", "outcome": "resolved"},
            ],
        }
    )
    custom = JourneyCatalog.from_journeys([*catalog.journeys.values(), quiet])
    state = transition(custom, new_state(), say("small_talk", "hi")).state
    assert state.step_id == "talk"
    result = transition(custom, state, say("small_talk", "oh no, sparks!"))
    assert result.state.active_journey == "troubleshoot"
    assert result.state.step_id == "escalate"
    # Sparks on an unknown appliance end DIY help everywhere: the set-aside chat is closed too.
    assert result.state.paused_issues == []
    assert [(r.journey, r.outcome) for r in result.state.issues] == [
        ("chat", "escalated"),
        ("troubleshoot", None),
    ]


# --- routing ------------------------------------------------------------------------------


def test_how_to_question_mid_guide_is_a_side_question(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    result = transition(catalog, state, say("ask_how_to", "How do I open the filter cover?"))
    assert result.side_question
    assert result.state.step_id == "guide"
    assert result.state.plan_cursor == state.plan_cursor
    assert result.state.plan == state.plan
    assert result.decisions[0].kind == "route"


def test_off_topic_mid_journey_gets_side_reply(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    result = transition(catalog, state, say("out_of_scope", "Who won the game last night?"))
    assert result.state.step_id == "guide"
    assert [r.rule_id for r in result.fixed_replies] == ["G-SCOPE-01"]
    assert not result.skip_respond


def test_off_topic_without_journey_ends_out_of_scope(catalog: JourneyCatalog) -> None:
    result = transition(catalog, new_state(), say("out_of_scope", "Write me a poem"))
    assert result.state.active_journey == "out_of_scope"
    assert result.state.step_id == "decline"
    assert result.state.outcome == "out_of_scope"
    assert result.skip_respond
    assert result.fixed_replies[0].rule_id == "G-SCOPE-01"

    back = transition(catalog, result.state, say("report_problem", slots=DISHWASHER))
    assert back.state.active_journey == "troubleshoot"
    assert back.state.outcome is None


def test_switching_appliance_pauses_and_resumes(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    switched = transition(
        catalog,
        state,
        say("report_problem", "Also my dryer is loud", slots={"appliance_category": "dryer"}),
    )
    [paused] = switched.state.paused_issues
    assert (paused.issue_id, paused.journey, paused.step_id) == ("iss_1", "troubleshoot", "guide")
    assert paused.slots["appliance_category"].value == "dishwasher"
    assert paused.summary == "dishwasher: won't drain"
    assert len(paused.plan) == 3
    assert switched.state.active_issue_id == "iss_2"
    assert switched.state.slots["appliance_category"].value == "dryer"
    assert "symptom" not in switched.state.slots  # nothing carried across appliances
    assert switched.state.step_id == "gather"

    state = run_turn(
        catalog, switched.state, say("report_problem", slots={"symptom": "loud"}), plan(1)
    ).state
    done = transition(catalog, state, press("step_result", "fixed"))
    assert done.state.step_id == "resolved"
    assert NOTICE_RESUME_PAUSED in done.notices
    assert done.state.outcome is None  # the dishwasher is still open
    assert [(r.issue_id, r.outcome) for r in done.state.issues] == [
        ("iss_1", None),
        ("iss_2", "resolved"),
    ]

    done.state.water_warning_given = True  # given for the dryer
    resumed = transition(catalog, done.state, say("confirm", "yes, back to the dishwasher"))
    assert not resumed.state.water_warning_given  # the dishwasher gets its own warning
    assert resumed.state.step_id == "guide"
    assert resumed.state.active_issue_id == "iss_1"
    assert resumed.state.slots["appliance_category"].value == "dishwasher"
    assert resumed.state.plan[0].status == "presented"
    assert not resumed.state.paused_issues
    assert resumed.state.outcome is None
    assert NOTICE_RESUMED_ISSUE in resumed.notices

    fixed = transition(catalog, resumed.state, press("step_result", "fixed"))
    assert fixed.state.outcome == "resolved"


def test_category_change_during_gather_is_a_correction(catalog: JourneyCatalog) -> None:
    state = new_state(
        active_journey="troubleshoot",
        step_id="gather",
        slots={"appliance_category": vision_slot("dryer", 1.0)},
    )
    result = transition(
        catalog, state, say("report_problem", slots={"appliance_category": "vacuum"})
    )
    assert not result.state.paused_issues
    assert result.state.slots["appliance_category"].value == "vacuum"


def test_how_to_use_journey_and_switch_to_troubleshoot(catalog: JourneyCatalog) -> None:
    result = transition(
        catalog,
        new_state(),
        say("ask_how_to", slots={"appliance_category": "coffee_maker", "question": "descale"}),
    )
    assert result.state.active_journey == "how_to_use"
    assert result.state.step_id == "retrieve"
    assert result.actions == ["knowledge.search"]

    answered = transition(catalog, result.state, None)
    assert answered.state.step_id == "answer"
    assert answered.state.outcome == "resolved"

    followup = transition(catalog, answered.state, say("ask_how_to", "And how often?"))
    assert followup.state.step_id == "retrieve"
    state = transition(catalog, followup.state, None).state

    problem = transition(
        catalog, state, say("report_problem", "it now leaks", slots={"symptom": "leaks"})
    )
    assert problem.state.active_journey == "troubleshoot"
    assert problem.state.slots["appliance_category"].value == "coffee_maker"  # carried
    assert problem.state.step_id == "diagnose"
    # The how-to question was answered, so it is closed rather than kept for later.
    assert not problem.state.paused_issues
    assert [(r.journey, r.outcome) for r in problem.state.issues] == [
        ("how_to_use", "resolved"),
        ("troubleshoot", None),
    ]

    thanks = transition(catalog, state, say("confirm", "thanks, that's all"))
    assert thanks.state.step_id == "done"


def test_new_journey_after_end_carries_appliance_slots(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    state = transition(catalog, state, press("step_result", "fixed")).state
    result = transition(catalog, state, say("ask_how_to", slots={"question": "eco mode?"}))
    assert result.state.active_journey == "how_to_use"
    assert result.state.slots["appliance_category"].value == "dishwasher"
    assert "symptom" not in result.state.slots
    assert result.state.step_id == "retrieve"


def test_intent_without_journey_is_logged(catalog: JourneyCatalog) -> None:
    result = transition(catalog, new_state(), say("small_talk", "hi there"))
    assert result.state.active_journey is None
    assert result.decisions[0].reason == "no journey handles intent small_talk"
    assert not result.actions


def test_route_is_pure_and_reports_kind(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    signals = signals_from_input(say("report_problem", slots={"appliance_category": "dryer"}))
    decided = route(catalog, state, signals)
    assert (decided.kind, decided.journey, decided.carry_slots) == ("switch", "troubleshoot", False)
    assert not state.paused_issues


# --- inputs and edge cases ----------------------------------------------------------------


def test_transition_does_not_mutate_input_state(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    before = state.model_dump()
    transition(catalog, state, press("step_result", "not_fixed"))
    assert state.model_dump() == before


def test_decisions_are_appended_to_the_log(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    result = transition(catalog, state, press("step_result", "not_fixed"))
    assert result.state.decision_log[-len(result.decisions) :] == result.decisions
    assert len(result.state.decision_log) == len(state.decision_log) + len(result.decisions)


def test_rejected_card_action_changes_nothing(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    result = transition(catalog, state, press("step_result", "maybe"))
    assert result.state.step_id == "guide"
    assert result.decisions[0].reason.startswith("ignored card action")
    assert result.state.step_attempts["guide"] == 1


def test_unclear_feedback_stays_on_step(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    result = transition(catalog, state, say("step_feedback", "hmm", step_feedback="unclear"))
    assert result.state.step_id == "guide"
    assert result.state.plan[0].status == "presented"


def test_invalid_enum_slot_is_rejected(catalog: JourneyCatalog) -> None:
    result = transition(
        catalog,
        new_state(),
        say("report_problem", slots={"appliance_category": "oven", "symptom": "cold"}),
    )
    assert result.state.step_id == "gather"
    assert "appliance_category" not in result.state.slots
    assert any(d.kind == "slot" and "oven" in d.reason for d in result.decisions)


def test_unknown_and_blank_slot_updates_are_ignored(catalog: JourneyCatalog) -> None:
    result = transition(
        catalog, new_state(), say("report_problem", slots={"color": "red", "symptom": "  "})
    )
    assert result.state.slots == {}


def test_booking_selection_outside_handoff_is_ignored(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    result = transition(catalog, state, press("select_booking_slot", "slot-1"))
    assert result.state.step_id == "guide"
    assert result.state.selected_booking_slot is None
    assert "ignored booking slot" in result.decisions[0].reason


def test_continue_is_a_no_op_without_pending_system_step(catalog: JourneyCatalog) -> None:
    assert transition(catalog, new_state(), None).decisions == []
    state = start_guide(catalog)
    ended = transition(catalog, state, press("step_result", "fixed")).state
    assert transition(catalog, ended, None).state.step_id == "resolved"


def test_empty_plan_escalates(catalog: JourneyCatalog) -> None:
    result = run_turn(catalog, new_state(), say("report_problem", slots=DISHWASHER), [])
    assert result.state.step_id == "escalate"
    assert result.decisions[-1].predicate == "plan_unavailable"


def test_turn_input_from_message() -> None:
    message = InboundMessage(
        conversation_id="c1", action=StructuredAction(type="confirm_appliance", value="Yes")
    )
    turn = TurnInput.from_message(message)
    signals = signals_from_input(turn)
    assert (signals.intent, signals.confirmed) == ("confirm", True)


def test_card_action_bypasses_nlu() -> None:
    turn = TurnInput(
        nlu=say("deny").nlu, action=StructuredAction(type="step_result", value="fixed")
    )
    signals = signals_from_input(turn)
    assert signals.feedback == "fixed"
    assert signals.intent is None
    assert signals_from_input(TurnInput()).intent is None
    denied = signals_from_input(press("confirm_appliance", "no"))
    assert denied.confirmed is False


def test_transition_chain_limit_stops_cycles() -> None:
    looping = parse_journey(
        {
            "id": "troubleshoot",
            "version": 1,
            "goal": "Loop.",
            "entry_intents": ["report_problem"],
            "guardrails": [{"when": "hazard_detected", "to": "out"}],
            "steps": [
                {"id": "a", "type": "collect", "transitions": [{"when": "always", "to": "b"}]},
                {
                    "id": "b",
                    "type": "collect",
                    "transitions": [
                        {"when": "always", "to": "a"},
                        {"when": "user_confirmed", "to": "out"},
                    ],
                },
                {"id": "out", "type": "end", "outcome": "escalated"},
            ],
        }
    )
    result = transition(JourneyCatalog.from_journeys([looping]), new_state(), say("report_problem"))
    assert "chain limit" in result.decisions[-1].reason


def test_resume_requires_paused_issue(catalog: JourneyCatalog) -> None:
    state = new_state(
        active_journey="troubleshoot",
        step_id="resolved",
        paused_issues=[
            PausedIssue(issue_id="iss_9", journey="how_to_use", summary="x", step_id="answer")
        ],
    )
    result = transition(catalog, state, say("confirm", "yes"))
    assert (result.state.active_journey, result.state.step_id) == ("how_to_use", "answer")


def test_a_side_question_does_not_change_the_active_issue(catalog: JourneyCatalog) -> None:
    state = start_guide(catalog)
    before = dict(state.slots)
    parts = say("ask_parts", "do Whirlpool filters fit?", slots={"brand": "Whirlpool"})
    result = transition(catalog, state, parts)
    assert result.side_question
    assert result.state.slots == before


def test_a_tool_question_about_another_appliance_stays_on_the_side(
    catalog: JourneyCatalog,
) -> None:
    state = start_guide(catalog)
    state.profile = UserContext(zip_code="94110")
    warranty = say(
        "my_appliances", "is my dryer under warranty?", slots={"appliance_category": "dryer"}
    )
    result = transition(catalog, state, warranty)
    assert result.side_question
    assert (result.state.active_issue_id, result.state.step_id) == ("iss_1", "guide")
    assert result.state.paused_issues == []
    # A guest has no appliances to ask about: the my_appliances journey answers (sign in).
    state.profile = None
    guest = transition(catalog, state, warranty)
    assert guest.state.active_journey == "my_appliances"


def test_a_side_question_while_collecting_still_corrects_details(catalog: JourneyCatalog) -> None:
    state = transition(
        catalog,
        new_state(),
        say("report_problem", "my dishwasher", slots={"appliance_category": "dishwasher"}),
    ).state
    assert state.step_id == "gather"
    parts = say("ask_parts", "it leaks, do I need a new pump?", slots={"symptom": "leaks"})
    result = transition(catalog, state, parts)
    assert result.state.slots["symptom"].value == "leaks"


def test_asking_for_a_technician_first_escalates(catalog: JourneyCatalog) -> None:
    ask = say("book_technician", "send a technician", slots={"appliance_category": "dishwasher"})
    result = transition(catalog, new_state(), ask)
    assert (result.state.active_journey, result.state.step_id) == ("troubleshoot", "escalate")


def test_asking_for_a_technician_mid_how_to_escalates_there(catalog: JourneyCatalog) -> None:
    how_to = say("ask_how_to", slots={"appliance_category": "coffee_maker", "question": "descale"})
    state = transition(catalog, transition(catalog, new_state(), how_to).state, None).state
    assert state.step_id == "answer"
    result = transition(catalog, state, say("book_technician", "just send someone"))
    assert (result.state.active_journey, result.state.step_id) == ("how_to_use", "escalate")
    assert result.state.paused_issues == []


def test_a_side_question_while_collecting_keeps_the_appliance(catalog: JourneyCatalog) -> None:
    state = transition(
        catalog, new_state(), say("report_problem", slots={"appliance_category": "dishwasher"})
    ).state
    state.profile = UserContext(zip_code="94110")
    warranty = say("my_appliances", slots={"appliance_category": "dryer", "brand": "LG"})
    result = transition(catalog, state, warranty)
    assert result.side_question
    assert result.state.slots["appliance_category"].value == "dishwasher"
    assert "brand" not in result.state.slots


def test_a_side_question_about_another_appliance_leaves_the_topic(
    catalog: JourneyCatalog,
) -> None:
    state = transition(
        catalog, new_state(), say("report_problem", slots={"appliance_category": "dishwasher"})
    ).state
    state.profile = UserContext(zip_code="94110")
    parts = say("ask_parts", slots={"appliance_category": "dryer", "symptom": "won't heat"})
    result = transition(catalog, state, parts)
    assert result.side_question
    assert "symptom" not in result.state.slots


def test_a_side_question_about_the_same_appliance_fills_the_topic(
    catalog: JourneyCatalog,
) -> None:
    state = transition(
        catalog, new_state(), say("report_problem", slots={"appliance_category": "dishwasher"})
    ).state
    parts = say("ask_parts", slots={"appliance_category": "dishwasher", "symptom": "leaks"})
    result = transition(catalog, state, parts)
    assert result.state.slots["symptom"].value == "leaks"
