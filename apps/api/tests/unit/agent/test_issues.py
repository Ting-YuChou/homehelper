"""Multi-issue tracking (spec §7.4, ADR-007): pausing, resuming, closing and reminders."""

import pytest

from homehelper.agent.engine import JourneyCatalog, TurnInput, default_catalog, transition
from homehelper.agent.engine.issues import (
    MAX_PAUSED_ISSUES,
    MAX_SUMMARY_CHARS,
    issue_summary,
    summary_outcome,
)
from homehelper.agent.engine.transition import (
    NOTICE_REMIND_PAUSED,
    NOTICE_RESUME_PAUSED,
    NOTICE_RESUMED_ISSUE,
)
from homehelper.agent.guardrails.templates import WATER_REMINDER_REPLY, safety_reply
from homehelper.agent.state import AgentState, IssueRecord, PausedIssue, SlotValue
from homehelper.channels.events import StructuredAction
from tests.unit.agent.helpers import new_state, plan, press, run_turn, say

APPLIANCES = ["dishwasher", "dryer", "microwave", "vacuum", "television"]


@pytest.fixture
def catalog() -> JourneyCatalog:
    return default_catalog()


def guide(
    catalog: JourneyCatalog, state: AgentState, category: str, symptom: str = "broken"
) -> AgentState:
    """Report a problem on `category` and run until its first step is presented."""
    slots = {"appliance_category": category, "symptom": symptom}
    result = run_turn(catalog, state, say("report_problem", slots=slots), plan(3))
    assert result.state.step_id == "guide"
    return result.state


def two_issues(catalog: JourneyCatalog) -> AgentState:
    """Dishwasher at its second step, paused; dryer active at its first step."""
    state = guide(catalog, new_state(), "dishwasher", "won't drain")
    state = transition(catalog, state, press("step_result", "not_fixed")).state
    return guide(catalog, state, "dryer", "squeaks")


def mention(category: str, intent: str = "report_problem", **slots: str) -> TurnInput:
    return say(intent, f"back to the {category}", slots={"appliance_category": category, **slots})


# --- summaries and outcomes ---------------------------------------------------------------


def test_summary_is_built_from_slots() -> None:
    def slot(value: str) -> SlotValue:
        return SlotValue(value=value, source="user", confidence=1.0)

    slots = {
        "appliance_category": slot("washing_machine"),
        "brand": slot("Bosch"),
        "symptom": slot("not draining"),
    }
    assert issue_summary(slots) == "Bosch washing machine: not draining"
    assert issue_summary({"question": slot("eco mode?")}) == "appliance: eco mode?"
    long = issue_summary({"symptom": slot("x" * 100)})
    assert len(long) == MAX_SUMMARY_CHARS and long.endswith("…")


def test_summary_outcome_ranks_issues() -> None:
    def record(issue_id: str, outcome: str | None) -> IssueRecord:
        return IssueRecord.model_validate(
            {"issue_id": issue_id, "journey": "t", "outcome": outcome}
        )

    state = new_state(issues=[record("iss_1", "resolved"), record("iss_2", "escalated")])
    assert summary_outcome(state, None) == "escalated"
    state.active_journey = "troubleshoot"
    assert summary_outcome(state, None) is None  # the active issue has no outcome yet
    assert summary_outcome(state, "resolved") == "escalated"
    state.paused_issues = [PausedIssue(issue_id="iss_3", journey="t", summary="", step_id=None)]
    assert summary_outcome(state, "resolved") is None
    assert summary_outcome(new_state(), None) is None


def test_single_issue_behaves_as_before(catalog: JourneyCatalog) -> None:
    state = guide(catalog, new_state(), "dishwasher")
    assert (state.active_issue_id, [r.issue_id for r in state.issues]) == ("iss_1", ["iss_1"])
    assert state.issues[0].summary == "dishwasher: broken"
    done = transition(catalog, state, press("step_result", "fixed"))
    assert done.state.outcome == "resolved"
    assert done.state.issues[0].outcome == "resolved"
    assert not done.notices


def test_out_of_scope_decline_is_not_an_issue(catalog: JourneyCatalog) -> None:
    result = transition(catalog, new_state(), say("out_of_scope", "tell me a joke"))
    assert result.state.active_issue_id is None
    assert not result.state.issues
    assert result.state.outcome == "out_of_scope"


def test_handoff_switch_closes_the_issue_as_escalated(catalog: JourneyCatalog) -> None:
    state = guide(catalog, new_state(), "dishwasher")
    state = transition(catalog, state, say("book_technician", "just send someone")).state
    assert state.step_id == "escalate" and state.outcome == "escalated"
    switched = transition(catalog, state, mention("dryer", symptom="squeaks"))
    assert not switched.state.paused_issues
    assert switched.state.issues[0].outcome == "escalated"
    assert any("closed iss_1 (escalated)" in d.reason for d in switched.decisions)


def test_legacy_state_gets_an_issue_id(catalog: JourneyCatalog) -> None:
    legacy = {
        "conversation_id": "c1",
        "release_id": "r1",
        "active_journey": "troubleshoot",
        "step_id": "guide",
        "paused_journey": {"journey": "how_to_use", "step_id": "answer"},  # pre-ADR-007 field
        "plan": [item.model_dump() for item in plan(2)],
    }
    state = AgentState.model_validate(legacy)
    result = transition(catalog, state, press("step_result", "not_fixed"))
    assert result.state.active_issue_id == "iss_1"
    assert result.state.issues[0].journey == "troubleshoot"

    ended = AgentState.model_validate({**legacy, "step_id": "resolved"})
    after = transition(catalog, ended, say("small_talk", "thanks"))
    assert after.state.issues[0].outcome == "resolved"


# --- resuming by appliance ----------------------------------------------------------------


def test_naming_a_paused_appliance_resumes_it(catalog: JourneyCatalog) -> None:
    state = two_issues(catalog)
    result = transition(catalog, state, mention("dishwasher"))
    resumed = result.state
    assert resumed.active_issue_id == "iss_1"
    assert resumed.step_id == "guide"
    assert [i.status for i in resumed.plan] == ["done_not_fixed", "presented", "pending"]
    assert resumed.last_retrieval is not None
    assert [p.issue_id for p in resumed.paused_issues] == ["iss_2"]
    assert NOTICE_RESUMED_ISSUE in result.notices
    assert any(d.reason.startswith("resumed iss_1") for d in result.decisions)


def test_a_new_symptom_on_a_paused_appliance_is_a_new_issue(catalog: JourneyCatalog) -> None:
    state = two_issues(catalog)
    result = transition(catalog, state, mention("dishwasher", symptom="it smells"))
    assert result.state.active_issue_id == "iss_3"
    assert [p.issue_id for p in result.state.paused_issues] == ["iss_1", "iss_2"]


def test_a_question_or_another_journey_does_not_resume(catalog: JourneyCatalog) -> None:
    state = two_issues(catalog)
    question = transition(catalog, state, mention("dishwasher", "ask_how_to", question="eco?"))
    assert question.state.active_journey == "how_to_use"
    assert question.state.active_issue_id == "iss_3"
    other = transition(catalog, state, mention("dishwasher", "ask_how_to"))
    assert other.state.active_journey == "how_to_use"


def test_going_back_while_collecting_drops_the_new_issue(catalog: JourneyCatalog) -> None:
    state = guide(catalog, new_state(), "dishwasher")
    # A new dryer problem with no symptom yet waits in `gather`.
    state = transition(catalog, state, say("report_problem", slots={"appliance_category": "dryer"}))
    assert state.state.step_id == "gather"
    back = transition(catalog, state.state, mention("dishwasher"))
    assert back.state.active_issue_id == "iss_1"
    assert back.state.step_id == "guide"
    assert not back.state.paused_issues
    assert back.state.issues[1].outcome == "abandoned"


def test_resume_into_collect_moves_on_when_details_are_complete(catalog: JourneyCatalog) -> None:
    state = guide(catalog, new_state(), "dishwasher")
    gather = PausedIssue(
        issue_id="iss_9",
        journey="troubleshoot",
        summary="dryer",
        step_id="gather",
        slots={
            "appliance_category": SlotValue(value="dryer", source="user", confidence=1.0),
            "symptom": SlotValue(value="squeaks", source="user", confidence=1.0),
        },
    )
    state.paused_issues.append(gather)
    result = transition(catalog, state, mention("dryer"))
    assert result.state.active_issue_id == "iss_9"
    assert result.state.step_id == "diagnose"
    assert result.actions == ["knowledge.search", "plan.build"]


def test_a_hazard_on_a_paused_appliance_escalates_that_issue(catalog: JourneyCatalog) -> None:
    state = two_issues(catalog)
    smoke = say(
        "report_problem",
        "the dishwasher is smoking now",
        slots={"appliance_category": "dishwasher", "symptom": "smoke"},
    )
    result = transition(catalog, state, smoke)
    assert result.state.active_issue_id == "iss_1"
    assert result.state.step_id == "escalate"
    assert result.skip_respond
    assert NOTICE_RESUME_PAUSED not in result.notices


def test_a_hazard_after_an_end_resumes_the_matching_issue(catalog: JourneyCatalog) -> None:
    state = two_issues(catalog)
    state = transition(catalog, state, press("step_result", "fixed")).state  # dryer resolved
    smoke = say("report_problem", "smoke from it", slots={"appliance_category": "dishwasher"})
    result = transition(catalog, state, smoke)
    assert (result.state.active_issue_id, result.state.step_id) == ("iss_1", "escalate")
    assert result.state.outcome == "escalated"


def test_a_hazard_closes_the_other_paused_issues_on_that_appliance(
    catalog: JourneyCatalog,
) -> None:
    state = guide(catalog, two_issues(catalog), "dishwasher", "leaking")  # iss_3; dryer paused
    smoke = say(
        "report_problem",
        "now the dishwasher is smoking",
        slots={"appliance_category": "dishwasher"},
    )
    result = transition(catalog, state, smoke)
    assert (result.state.active_issue_id, result.state.step_id) == ("iss_3", "escalate")
    # The paused drain problem can no longer come back with DIY steps; the dryer is another
    # appliance.
    assert [p.issue_id for p in result.state.paused_issues] == ["iss_2"]
    assert result.state.issues[0].outcome == "escalated"


def test_a_gas_smell_closes_every_paused_issue(catalog: JourneyCatalog) -> None:
    result = transition(catalog, two_issues(catalog), say("report_problem", "I smell gas"))
    assert result.state.paused_issues == []
    assert result.state.issues[0].outcome == "escalated"


def test_oldest_paused_issue_is_closed_when_full(catalog: JourneyCatalog) -> None:
    state = new_state()
    for category in APPLIANCES:
        state = guide(catalog, state, category)
    assert [p.issue_id for p in state.paused_issues] == ["iss_2", "iss_3", "iss_4"]
    assert len(state.paused_issues) == MAX_PAUSED_ISSUES
    assert state.issues[0].outcome == "abandoned"
    assert any("closed iss_1 (abandoned)" in d.reason for d in state.decision_log)

    # With the list full, resuming one never evicts it.
    result = transition(catalog, state, mention("dryer"))
    assert result.state.active_issue_id == "iss_2"
    assert [p.issue_id for p in result.state.paused_issues] == ["iss_3", "iss_4", "iss_5"]


# --- the issues card and reminders --------------------------------------------------------


def test_offer_comes_only_on_the_turn_an_issue_ends(catalog: JourneyCatalog) -> None:
    state = two_issues(catalog)
    done = transition(catalog, state, press("step_result", "fixed"))
    assert NOTICE_RESUME_PAUSED in done.notices
    later = transition(catalog, done.state, say("other", "hmm"))
    assert NOTICE_RESUME_PAUSED not in later.notices


def test_card_resume_and_close(catalog: JourneyCatalog) -> None:
    state = transition(catalog, two_issues(catalog), press("step_result", "fixed")).state

    resumed = transition(catalog, state, press("resume_issue", "iss_1"))
    assert (resumed.state.active_issue_id, resumed.state.step_id) == ("iss_1", "guide")
    named = transition(catalog, state, mention("dishwasher"))
    assert (named.state.active_issue_id, named.state.step_id) == ("iss_1", "guide")

    closed = transition(catalog, state, press("close_issue", "iss_1"))
    assert not closed.state.paused_issues
    assert closed.state.issues[0].outcome == "abandoned"
    assert closed.state.outcome == "resolved"  # the dryer was fixed; nothing is open


def test_closing_one_offers_the_rest(catalog: JourneyCatalog) -> None:
    state = guide(catalog, two_issues(catalog), "microwave")
    state = transition(catalog, state, press("step_result", "fixed")).state
    closed = transition(catalog, state, press("close_issue", "iss_1"))
    assert [p.issue_id for p in closed.state.paused_issues] == ["iss_2"]
    assert NOTICE_RESUME_PAUSED in closed.notices


def test_stale_card_press_changes_nothing(catalog: JourneyCatalog) -> None:
    state = two_issues(catalog)
    result = transition(catalog, state, press("resume_issue", "iss_7"))
    assert result.state.active_issue_id == "iss_2"
    assert result.state.step_attempts == state.step_attempts
    assert result.decisions[0].reason == "ignored card action: issue iss_7 is not paused"
    empty = transition(catalog, state, press("close_issue", " "))
    assert "ignored card action" in empty.decisions[0].reason


def test_closing_reminder_comes_once(catalog: JourneyCatalog) -> None:
    state = transition(catalog, two_issues(catalog), press("step_result", "fixed")).state
    bye = transition(catalog, state, say("small_talk", "thanks, bye"))
    assert NOTICE_REMIND_PAUSED in bye.notices
    again = transition(catalog, bye.state, say("small_talk", "bye!"))
    assert NOTICE_REMIND_PAUSED not in again.notices


def test_no_reminder_during_an_unfinished_issue(catalog: JourneyCatalog) -> None:
    result = transition(catalog, two_issues(catalog), say("small_talk", "thanks"))
    assert NOTICE_REMIND_PAUSED not in result.notices


def test_deny_uses_up_the_reminder(catalog: JourneyCatalog) -> None:
    state = transition(catalog, two_issues(catalog), press("step_result", "fixed")).state
    denied = transition(catalog, state, say("deny", "no thanks"))
    assert [p.issue_id for p in denied.state.paused_issues] == ["iss_1"]
    assert denied.state.paused_reminder_used
    bye = transition(catalog, denied.state, say("small_talk", "bye"))
    assert NOTICE_REMIND_PAUSED not in bye.notices


def test_turning_down_a_paused_appliance_by_name_closes_it(catalog: JourneyCatalog) -> None:
    state = transition(catalog, two_issues(catalog), press("step_result", "fixed")).state
    forget = mention("dishwasher", "deny")
    closed = transition(catalog, state, forget)
    assert closed.state.paused_issues == []
    assert closed.state.issues[0].outcome == "abandoned"
    # Mid-journey "no, I meant the dishwasher" is ambiguous: it goes back to it, as before.
    meant = transition(catalog, two_issues(catalog), forget)
    assert meant.state.active_issue_id == "iss_1"


def test_a_step_answer_naming_a_paused_appliance_is_not_dropping_it(
    catalog: JourneyCatalog,
) -> None:
    state = transition(catalog, two_issues(catalog), press("step_result", "fixed")).state
    answer = say(
        "deny",
        "no, the dishwasher still doesn't drain",
        slots={"appliance_category": "dishwasher"},
        step_feedback="not_fixed",
    )
    result = transition(catalog, state, answer)
    assert result.state.issues[0].outcome is None


def test_a_stale_confirm_button_does_not_answer_the_offer(catalog: JourneyCatalog) -> None:
    state = transition(catalog, two_issues(catalog), press("step_result", "fixed")).state
    yes = transition(catalog, state, press("confirm_appliance", "yes"))
    assert yes.state.active_issue_id == "iss_2"
    assert [p.issue_id for p in yes.state.paused_issues] == ["iss_1"]
    no = transition(catalog, state, press("confirm_appliance", "no"))
    assert not no.state.paused_reminder_used


def test_water_mentioned_while_resuming_gets_the_full_warning(catalog: JourneyCatalog) -> None:
    state = two_issues(catalog)
    state.water_warning_given = True  # given for the dryer
    turn = TurnInput(
        text="there is water near the outlet",
        action=StructuredAction(type="resume_issue", value="iss_1"),
    )
    result = transition(catalog, state, turn)
    assert result.state.active_issue_id == "iss_1"
    assert result.fixed_replies == [safety_reply("water_near_electric")]
    assert WATER_REMINDER_REPLY not in result.fixed_replies


def test_a_hazard_on_a_card_resume_ends_diy_for_every_paused_issue(
    catalog: JourneyCatalog,
) -> None:
    # Card turns skip the NLU, so the smoking appliance is unknown: none may resume with steps.
    turn = TurnInput(
        text="the dryer is smoking",
        action=StructuredAction(type="resume_issue", value="iss_1"),
    )
    result = transition(catalog, two_issues(catalog), turn)
    assert (result.state.active_issue_id, result.state.step_id) == ("iss_1", "escalate")
    assert result.state.paused_issues == []
    assert result.state.issues[1].outcome == "escalated"


def test_a_close_card_still_closes_on_a_hazard_turn(catalog: JourneyCatalog) -> None:
    state = guide(catalog, two_issues(catalog), "microwave")  # dishwasher and dryer paused
    turn = TurnInput(
        text="sparks coming out", action=StructuredAction(type="close_issue", value="iss_1")
    )
    result = transition(catalog, state, turn)
    assert result.state.step_id == "escalate"
    assert result.state.issues[0].outcome == "abandoned"
    assert result.state.paused_issues == []  # the hazard ended DIY help for the dryer too


def test_saying_goodbye_does_not_resume_a_paused_issue(catalog: JourneyCatalog) -> None:
    state = transition(catalog, two_issues(catalog), press("step_result", "fixed")).state
    bye = transition(catalog, state, mention("dishwasher", "small_talk"))
    assert [p.issue_id for p in bye.state.paused_issues] == ["iss_1"]
    assert NOTICE_REMIND_PAUSED in bye.notices


def test_a_hazard_with_a_stale_card_still_escalates(catalog: JourneyCatalog) -> None:
    turn = TurnInput(
        text="I smell gas", action=StructuredAction(type="resume_issue", value="iss_9")
    )
    result = transition(catalog, two_issues(catalog), turn)
    assert result.state.step_id == "escalate"
    assert result.state.paused_issues == []


def test_water_still_there_with_a_stale_card_escalates(catalog: JourneyCatalog) -> None:
    state = two_issues(catalog)
    state.water_warning_given = True
    turn = TurnInput(
        text="water is still dripping on the outlet",
        action=StructuredAction(type="resume_issue", value="iss_9"),
    )
    result = transition(catalog, state, turn)
    assert result.state.step_id == "escalate"


def test_a_hazard_with_a_step_result_is_about_the_active_appliance(
    catalog: JourneyCatalog,
) -> None:
    turn = TurnInput(
        text="it's smoking now", action=StructuredAction(type="step_result", value="not_fixed")
    )
    result = transition(catalog, two_issues(catalog), turn)
    assert result.state.step_id == "escalate"
    assert [p.issue_id for p in result.state.paused_issues] == ["iss_1"]  # the dishwasher
