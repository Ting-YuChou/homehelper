"""Linking an issue to a profile appliance and prefilling its slots (pure, spec §12.2)."""

from homehelper.agent.engine import default_catalog
from homehelper.agent.engine.issues import pause_active, restore, take_paused
from homehelper.agent.engine.profile import link_profile_appliance
from homehelper.agent.state import AgentState, ProfileAppliance, SlotValue, UserContext

TROUBLESHOOT = default_catalog()["troubleshoot"]
WASHER = ProfileAppliance(
    appliance_id="apl_washer", category="washing_machine", brand="LG", model_number="WM4000HWA"
)
DRYER = ProfileAppliance(
    appliance_id="apl_dryer", category="dryer", brand="Samsung", model_number="DVE45B6300W"
)


def user(value: str) -> SlotValue:
    return SlotValue(value=value, source="user", confidence=1.0, confirmed=True)


def state(*appliances: ProfileAppliance, **slots: str) -> AgentState:
    return AgentState(
        conversation_id="c",
        release_id="dev",
        user_id="demo",
        profile=UserContext(zip_code="94110", appliances=list(appliances)),
        active_journey="troubleshoot",
        active_issue_id="iss_1",
        slots={name: user(value) for name, value in slots.items()},
    )


def test_a_single_matching_appliance_is_linked_and_prefills_slots() -> None:
    s = state(WASHER, DRYER, appliance_category="washing_machine", symptom="not draining")
    decision = link_profile_appliance(s, TROUBLESHOOT)
    assert s.appliance_id == "apl_washer"
    assert (s.slots["brand"].value, s.slots["brand"].source) == ("LG", "profile")
    assert s.slots["model_number"].value == "WM4000HWA"
    assert decision is not None
    assert decision.reason == "linked apl_washer from the profile; prefilled brand, model_number"


def test_user_details_are_kept_and_must_agree_with_the_profile() -> None:
    s = state(WASHER, appliance_category="washing_machine", brand="lg", model_number="wm-4000hwa")
    assert link_profile_appliance(s, TROUBLESHOOT) is not None
    assert s.slots["brand"].value == "lg"  # what the user said stays
    conflicting = state(WASHER, appliance_category="washing_machine", brand="Samsung")
    assert link_profile_appliance(conflicting, TROUBLESHOOT) is None
    assert conflicting.appliance_id is None
    assert "model_number" not in conflicting.slots


def test_no_link_without_a_profile_a_category_or_a_unique_match() -> None:
    other = WASHER.model_copy(update={"appliance_id": "apl_washer_2", "model_number": "X1"})
    assert (
        link_profile_appliance(
            state(WASHER, other, appliance_category="washing_machine"), TROUBLESHOOT
        )
        is None
    )
    assert link_profile_appliance(state(WASHER), TROUBLESHOOT) is None
    guest = state(appliance_category="washing_machine")
    guest.profile = None
    assert link_profile_appliance(guest, TROUBLESHOOT) is None


def test_an_issue_is_linked_once() -> None:
    s = state(WASHER, appliance_category="washing_machine")
    s.appliance_id = "apl_other"
    assert link_profile_appliance(s, TROUBLESHOOT) is None
    assert s.appliance_id == "apl_other"


def test_a_paused_issue_keeps_its_appliance() -> None:
    s = state(WASHER, appliance_category="washing_machine")
    link_profile_appliance(s, TROUBLESHOOT)
    s.step_id = "guide"
    pause_active(s)
    s.appliance_id = None
    restore(s, take_paused(s, "iss_1"))
    assert s.appliance_id == "apl_washer"
