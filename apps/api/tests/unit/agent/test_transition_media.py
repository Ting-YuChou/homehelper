"""Photos and videos in the journey engine (M6-02, spec §11.2): vision slots, the confirm step,
hazards seen in media, and what a failed analysis does to the reply."""

import pytest

from homehelper.agent.engine import JourneyCatalog, TurnInput, default_catalog, transition
from homehelper.agent.engine.perception import MediaInput, PerceivedSlot
from homehelper.agent.engine.predicates import LOW_CONFIDENCE
from homehelper.agent.state import NLUResult, ProfileAppliance, SlotValue, UserContext
from tests.unit.agent.helpers import DIAGNOSE_ACTIONS, new_state, plan, say


@pytest.fixture
def catalog() -> JourneyCatalog:
    return default_catalog()


def seen(confidence: float = 0.9, source: str = "vision", **slots: str) -> list[PerceivedSlot]:
    return [
        PerceivedSlot(name=name, value=value, source=source, confidence=confidence)  # type: ignore[arg-type]
        for name, value in slots.items()
    ]


def photo(
    *updates: PerceivedSlot,
    text: str | None = None,
    nlu: NLUResult | None = None,
    failures: list[str] | None = None,
    hazards: list[str] | None = None,
) -> TurnInput:
    media = MediaInput.model_validate(
        {
            "slot_updates": list(updates),
            "failures": failures or [],
            "hazard_signals": hazards or [],
            "analyzed": 0 if failures and not updates else 1,
        }
    )
    return TurnInput(text=text, nlu=nlu, media=media)


def user(value: str) -> SlotValue:
    return SlotValue(value=value, source="user", confidence=1.0, confirmed=True)


def test_the_confirm_threshold_is_the_spec_value() -> None:
    assert LOW_CONFIDENCE == 0.7


def test_a_photo_alone_starts_troubleshooting(catalog: JourneyCatalog) -> None:
    result = transition(
        catalog, new_state(), photo(*seen(appliance_category="washing_machine", brand="LG"))
    )
    state = result.state
    assert state.active_journey == "troubleshoot"
    assert state.step_id == "gather"  # still needs the symptom
    category = state.slots["appliance_category"]
    assert (category.value, category.source, category.confidence) == (
        "washing_machine",
        "vision",
        0.9,
    )
    assert category.confirmed is False
    assert state.slots["brand"].source == "vision"


@pytest.mark.parametrize(("confidence", "step"), [(0.69, "confirm_appliance"), (0.70, "diagnose")])
def test_low_confidence_photos_are_confirmed(
    catalog: JourneyCatalog, confidence: float, step: str
) -> None:
    turn = photo(
        *seen(confidence, appliance_category="washing_machine", model_number="WM3400CW"),
        text="it won't drain",
        nlu=say("report_problem", slots={"symptom": "won't drain"}).nlu,
    )
    result = transition(catalog, new_state(), turn)
    assert result.state.step_id == step
    if step == "diagnose":
        assert result.actions == DIAGNOSE_ACTIONS


def test_what_the_user_typed_beats_the_photo(catalog: JourneyCatalog) -> None:
    turn = photo(
        *seen(appliance_category="washing_machine", brand="LG"),
        text="my Samsung dryer is noisy",
        nlu=say("report_problem", slots={"appliance_category": "dryer", "brand": "Samsung"}).nlu,
    )
    result = transition(catalog, new_state(), turn)
    slots = result.state.slots
    assert (slots["appliance_category"].value, slots["appliance_category"].source) == (
        "dryer",
        "user",
    )
    assert (slots["brand"].value, slots["brand"].source) == ("Samsung", "user")
    assert any("photo" in d.reason and "dryer" in d.reason for d in result.decisions)


def test_a_typed_brand_beats_the_photos_brand(catalog: JourneyCatalog) -> None:
    turn = photo(
        *seen(appliance_category="dryer", brand="LG", model_number="DLEX3900W"),
        text="my Samsung dryer is noisy",
        nlu=say("report_problem", slots={"appliance_category": "dryer", "brand": "Samsung"}).nlu,
    )
    slots = transition(catalog, new_state(), turn).state.slots
    assert (slots["brand"].value, slots["brand"].source) == ("Samsung", "user")
    assert "model_number" not in slots  # an LG model number doesn't belong to a Samsung


def test_a_photo_never_overwrites_what_the_user_said(catalog: JourneyCatalog) -> None:
    state = new_state(
        active_journey="troubleshoot",
        active_issue_id="iss_1",
        step_id="gather",
        slots={"appliance_category": user("washing_machine"), "brand": user("LG")},
    )
    result = transition(catalog, state, photo(*seen(brand="Samsung", model_number="WF45")))
    slots = result.state.slots
    assert slots["brand"].value == "LG"
    assert "model_number" not in slots  # a Samsung model number isn't the user's LG
    same = transition(catalog, state, photo(*seen(brand="lg", model_number="WM3400CW")))
    assert (same.state.slots["model_number"].value, same.state.slots["model_number"].source) == (
        "WM3400CW",
        "vision",
    )


def test_a_photo_replaces_a_profile_prefill_and_unlinks_it(catalog: JourneyCatalog) -> None:
    profile = UserContext(
        appliances=[
            ProfileAppliance(
                appliance_id="app_1",
                category="washing_machine",
                brand="LG",
                model_number="WM4000HWA",
            )
        ]
    )
    state = new_state(
        profile=profile,
        active_journey="troubleshoot",
        active_issue_id="iss_1",
        step_id="gather",
        appliance_id="app_1",
        slots={
            "appliance_category": user("washing_machine"),
            "brand": SlotValue(value="LG", source="profile", confidence=1.0, confirmed=True),
            "model_number": SlotValue(
                value="WM4000HWA", source="profile", confidence=1.0, confirmed=True
            ),
        },
    )
    result = transition(
        catalog, state, photo(*seen(0.95, brand="Samsung", model_number="WF45T6000AW"))
    )
    slots = result.state.slots
    assert (slots["brand"].value, slots["brand"].source) == ("Samsung", "vision")
    assert slots["model_number"].value == "WF45T6000AW"
    assert result.state.appliance_id is None


def test_a_newer_photo_replaces_an_older_one(catalog: JourneyCatalog) -> None:
    state = new_state(
        active_journey="troubleshoot",
        active_issue_id="iss_1",
        step_id="gather",
        slots={
            "appliance_category": user("washing_machine"),
            "model_number": SlotValue(value="WM34", source="vision", confidence=0.5),
        },
    )
    result = transition(catalog, state, photo(*seen(0.9, model_number="WM3400CW")))
    slot = result.state.slots["model_number"]
    assert (slot.value, slot.confidence) == ("WM3400CW", 0.9)


def test_a_photo_does_not_switch_the_issue_mid_guide(catalog: JourneyCatalog) -> None:
    state = new_state(
        active_journey="troubleshoot",
        active_issue_id="iss_1",
        step_id="guide",
        slots={"appliance_category": user("washing_machine"), "symptom": user("won't drain")},
        plan=plan(2),
    )
    state.plan[0].status = "presented"
    result = transition(
        catalog, state, photo(*seen(appliance_category="dryer", brand="Samsung"), text="look")
    )
    assert result.state.step_id == "guide"
    assert result.state.slots["appliance_category"].value == "washing_machine"
    assert "brand" not in result.state.slots
    assert any("photo" in d.reason and "ignored" in d.reason for d in result.decisions)


def test_unknown_categories_from_a_photo_are_rejected(catalog: JourneyCatalog) -> None:
    result = transition(catalog, new_state(), photo(*seen(appliance_category="toaster_oven")))
    assert "appliance_category" not in result.state.slots
    assert any("rejected" in d.reason for d in result.decisions)


def test_low_confidence_details_are_dropped_where_nothing_confirms_them(
    catalog: JourneyCatalog,
) -> None:
    state = new_state(
        active_journey="how_to_use",
        active_issue_id="iss_1",
        step_id=catalog["how_to_use"].entry_step,
        slots={"appliance_category": user("washing_machine")},
    )
    result = transition(
        catalog, state, photo(*seen(0.4, brand="LG"), *seen(0.9, model_number="WM3400CW"))
    )
    assert "brand" not in result.state.slots
    assert result.state.slots["model_number"].value == "WM3400CW"
    assert any("brand" in d.reason and "confirm" in d.reason for d in result.decisions)


def test_a_failed_photo_alone_gets_a_fixed_reply(catalog: JourneyCatalog) -> None:
    result = transition(catalog, new_state(), photo(failures=["image"]))
    [reply] = result.fixed_replies
    assert reply.rule_id == "M-MEDIA-01"
    assert reply.replaces_response
    assert "describe" in reply.text


def test_a_failed_video_with_text_does_not_block_the_reply(catalog: JourneyCatalog) -> None:
    turn = photo(
        failures=["video"],
        text="my dishwasher won't drain",
        nlu=say("report_problem", slots={"appliance_category": "dishwasher"}).nlu,
    )
    result = transition(catalog, new_state(), turn)
    [reply] = [r for r in result.fixed_replies if r.rule_id == "M-MEDIA-01"]
    assert not reply.replaces_response
    assert result.state.active_journey == "troubleshoot"


def test_a_failure_next_to_a_good_photo_is_mentioned_not_blocking(catalog: JourneyCatalog) -> None:
    result = transition(
        catalog, new_state(), photo(*seen(appliance_category="dryer"), failures=["video"])
    )
    [reply] = [r for r in result.fixed_replies if r.rule_id == "M-MEDIA-01"]
    assert not reply.replaces_response


def test_a_hazard_seen_in_a_photo_escalates(catalog: JourneyCatalog) -> None:
    result = transition(
        catalog,
        new_state(),
        photo(*seen(appliance_category="dryer"), hazards=["smoke_or_burning"]),
    )
    assert result.state.step_id == "escalate"
    assert "smoke_or_burning" in result.state.hazard_flags
    assert any(h.source == "media" for h in result.hazards)
    assert any(r.rule_id == "G-SAFE-02" for r in result.fixed_replies)


def test_a_photo_with_a_side_question_does_not_touch_the_issue(catalog: JourneyCatalog) -> None:
    state = new_state(
        profile=UserContext(),
        active_journey="troubleshoot",
        active_issue_id="iss_1",
        step_id="gather",
        slots={"appliance_category": user("washing_machine")},
    )
    turn = photo(
        *seen(brand="Whirlpool"),
        text="what part is this?",
        nlu=say("ask_parts").nlu,
    )
    result = transition(catalog, state, turn)
    assert result.side_question
    assert "brand" not in result.state.slots


def test_a_photo_of_another_appliance_than_the_one_typed_adds_nothing(
    catalog: JourneyCatalog,
) -> None:
    turn = photo(
        *seen(appliance_category="washing_machine", brand="LG", model_number="WM4000HWA"),
        text="my dryer isn't heating",
        nlu=say("report_problem", slots={"appliance_category": "dryer"}).nlu,
    )
    result = transition(catalog, new_state(), turn)
    slots = result.state.slots
    assert slots["appliance_category"].value == "dryer"
    assert "brand" not in slots and "model_number" not in slots
    assert any("photo" in d.reason and "washing_machine" in d.reason for d in result.decisions)


def _at_confirm() -> object:
    return new_state(
        active_journey="troubleshoot",
        active_issue_id="iss_1",
        step_id="confirm_appliance",
        slots={
            "appliance_category": SlotValue(
                value="washing_machine", source="vision", confidence=0.6
            ),
            "brand": SlotValue(value="LG", source="vision", confidence=0.6),
            "symptom": user("won't drain"),
        },
    )


def test_a_yes_confirms_only_what_the_card_showed(catalog: JourneyCatalog) -> None:
    turn = photo(*seen(0.5, brand="Samsung"), text="yes", nlu=say("confirm").nlu)
    result = transition(catalog, _at_confirm(), turn)  # type: ignore[arg-type]
    slots = result.state.slots
    assert slots["appliance_category"].confirmed is True  # shown on the card, unchanged
    brand = slots["brand"]
    assert (brand.value, brand.confirmed) == ("Samsung", False)  # new: asked about next
    assert result.state.step_id == "confirm_appliance"


def test_a_no_with_the_right_photo_keeps_the_new_photo(catalog: JourneyCatalog) -> None:
    turn = photo(
        *seen(0.95, brand="Samsung", model_number="WF45T6000AW"),
        text="No, here's the right sticker",
        nlu=say("deny").nlu,
    )
    result = transition(catalog, _at_confirm(), turn)  # type: ignore[arg-type]
    slots = result.state.slots
    assert (slots["brand"].value, slots["model_number"].value) == ("Samsung", "WF45T6000AW")
    assert "appliance_category" not in slots  # the denied guess is gone


def test_a_confirmed_photo_value_is_not_overwritten_by_a_later_photo(
    catalog: JourneyCatalog,
) -> None:
    state = new_state(
        active_journey="troubleshoot",
        active_issue_id="iss_1",
        step_id="gather",
        slots={
            "appliance_category": SlotValue(
                value="washing_machine", source="vision", confidence=0.6, confirmed=True
            ),
            "brand": SlotValue(value="LG", source="vision", confidence=0.6, confirmed=True),
        },
    )
    result = transition(catalog, state, photo(*seen(0.9, brand="Samsung")))
    assert result.state.slots["brand"].value == "LG"


def test_a_photo_of_another_appliance_than_a_confirmed_one_adds_nothing(
    catalog: JourneyCatalog,
) -> None:
    state = new_state(
        active_journey="troubleshoot",
        active_issue_id="iss_1",
        step_id="gather",
        slots={
            "appliance_category": SlotValue(
                value="washing_machine", source="vision", confidence=0.6, confirmed=True
            ),
            "brand": SlotValue(value="LG", source="vision", confidence=0.6, confirmed=True),
        },
    )
    turn = photo(
        *seen(0.9, appliance_category="dryer", brand="Samsung", model_number="DVE45R6100C"),
        *seen(0.9, symptom="lint everywhere"),
    )
    slots = transition(catalog, state, turn).state.slots
    assert "model_number" not in slots and "symptom" not in slots


def test_a_yes_with_a_photo_of_the_same_value_is_not_asked_again(
    catalog: JourneyCatalog,
) -> None:
    turn = photo(*seen(0.65, brand="LG"), text="yes", nlu=say("confirm").nlu)
    result = transition(catalog, _at_confirm(), turn)  # type: ignore[arg-type]
    assert result.state.slots["brand"].confirmed is True
    assert result.state.step_id != "confirm_appliance"
