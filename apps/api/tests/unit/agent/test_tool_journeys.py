"""`my_appliances` and `parts_and_tutorials` (spec §7.5) and side questions that use tools."""

import pytest

from homehelper.agent.engine import JourneyCatalog, default_catalog, transition
from homehelper.agent.state import UserContext
from tests.unit.agent.helpers import new_state, plan, run_turn, say

DISHWASHER = {"appliance_category": "dishwasher", "symptom": "won't drain"}


@pytest.fixture
def catalog() -> JourneyCatalog:
    return default_catalog()


def test_my_appliances_answers_from_the_profile(catalog: JourneyCatalog) -> None:
    state = new_state(user_id="demo_alex", profile=UserContext(zip_code="94110"))
    result = transition(catalog, state, say("my_appliances", "Is my dryer under warranty?"))
    assert (result.state.active_journey, result.state.step_id) == ("my_appliances", "answer")
    assert not result.fixed_replies
    done = transition(catalog, result.state, say("confirm", "yes thanks"))
    assert (done.state.step_id, done.state.outcome) == ("done", "resolved")


def test_my_appliances_for_a_guest_is_a_fixed_sign_in_reply(catalog: JourneyCatalog) -> None:
    result = transition(catalog, new_state(user_id="guest_1"), say("my_appliances", "my stuff?"))
    assert result.state.step_id == "sign_in"
    (reply,) = result.fixed_replies
    assert reply.replaces_response and "signed in" in reply.text
    assert result.state.outcome == "resolved"


def test_parts_journey_looks_up_parts_and_videos_once_details_are_in(
    catalog: JourneyCatalog,
) -> None:
    first = transition(catalog, new_state(), say("ask_parts", "I need a part"))
    assert (first.state.active_journey, first.state.step_id) == ("parts_and_tutorials", "gather")
    second = transition(catalog, first.state, say("ask_parts", slots=DISHWASHER))
    assert second.state.step_id == "recommend"
    assert second.actions == ["mcp:parts_catalog.search_parts", "mcp:tutorials.search_videos"]
    assert not second.continue_after_actions  # an inform step waits for the user


@pytest.mark.parametrize("intent", ["ask_parts", "my_appliances", "ask_how_to"])
def test_tool_questions_during_troubleshooting_keep_the_step(
    catalog: JourneyCatalog, intent: str
) -> None:
    started = run_turn(
        catalog, new_state(), say("report_problem", "dishwasher", slots=DISHWASHER), plan(2)
    )
    assert started.state.step_id == "guide"
    side = transition(catalog, started.state, say(intent, "which part do I need?"))
    assert side.side_question
    assert (side.state.active_journey, side.state.step_id) == ("troubleshoot", "guide")
    assert side.state.paused_issues == []
