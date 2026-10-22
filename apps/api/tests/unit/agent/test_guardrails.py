import json

import pytest

from homehelper.agent.guardrails import (
    ESCALATING_HAZARDS,
    HAZARD_RULES,
    RULES,
    check_privacy,
    detect_hazards,
    keyword_hazards,
    postprocess_plan,
    safety_reply,
)
from homehelper.agent.guardrails.hazards import water_persists
from homehelper.agent.guardrails.plan import (
    POWER_OFF_INSTRUCTION,
    drop_high_risk,
    drop_uncited,
    flag_warranty,
    forbid_high_voltage_disassembly,
    insert_power_off,
)
from homehelper.agent.guardrails.privacy import personal_data_requests
from homehelper.agent.guardrails.templates import SAFETY_TEMPLATES, STEP_TEMPLATES
from homehelper.agent.state import NLUResult, PlanItem

# --- hazard detection ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I smell gas near the stove", ["gas_smell"]),
        ("there's a gas leak I think", ["gas_smell"]),
        ("it smells like rotten eggs", ["gas_smell"]),
        ("Smoke is coming out of the back", ["smoke_or_burning"]),
        ("there is a burning smell when it runs", ["smoke_or_burning"]),
        ("it smells like something melting", ["smoke_or_burning"]),
        ("I saw sparks inside", ["sparks"]),
        ("the cord caught fire", ["smoke_or_burning"]),
        ("I got a shock touching the door", ["sparks", "injury"]),
        ("water is leaking onto the power cord", ["water_near_electric"]),
        ("the outlet behind it is wet", ["water_near_electric"]),
        ("I think the refrigerant is leaking", ["refrigerant"]),
        ("how do I recharge freon in my fridge", ["refrigerant"]),
        ("can I cut the capillary tube and braze it back?", ["refrigerant"]),
        ("the compressor is dead, walk me through replacing it", ["refrigerant"]),
        ("how do I replace the compressor", ["refrigerant"]),
        ("then reseal the system", ["refrigerant"]),
        ("I punctured the evaporator while defrosting", ["refrigerant"]),
        ("how do I replace the magnetron", ["high_voltage_internal"]),
        ("can I open the microwave casing myself", ["high_voltage_internal"]),
        ("I cut my hand on the blade", ["injury"]),
        ("I can smell the gas from here", ["gas_smell"]),
        ("I smell a gas odor", ["gas_smell"]),
        ("it smells of propane", ["gas_smell"]),
        ("the grill smells like LPG", ["gas_smell"]),
        ("I think there is gas in the room", ["gas_smell"]),
        ("it smells like something is burning", ["smoke_or_burning"]),
        ("something's burning in there", ["smoke_or_burning"]),
        ("it's burning!", ["smoke_or_burning"]),
        ("the dryer keeps overheating", ["smoke_or_burning"]),
        ("there's a hot plastic smell", ["smoke_or_burning"]),
        ("an electrical smell from the fan", ["smoke_or_burning"]),
        ("the plastic around the plug melted", ["smoke_or_burning"]),
        ("how do I take the cover off my microwave", ["high_voltage_internal"]),
        ("can I dismantle the microwave", ["high_voltage_internal"]),
        ("I want to crack open the microwave", ["high_voltage_internal"]),
        ("water near the fuse box", ["water_near_electric"]),
        ("the electric panel is wet", ["water_near_electric"]),
        ("the breaker is dripping", ["water_near_electric"]),
        ("water everywhere and the electricity is still on", ["water_near_electric"]),
        ("there is water on the floor.\nIt runs right up to the outlet", ["water_near_electric"]),
        ("the microwave\nI want to take apart", ["high_voltage_internal"]),
        ("my son got burned by the steam", ["injury"]),
    ],
)
def test_keyword_hazards(text: str, expected: list[str]) -> None:
    assert keyword_hazards(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "My dishwasher won't drain",
        "water is leaking from the drain plug",
        "the sparkling water setting doesn't work",
        "my gas dryer won't heat up",
        "the coffee tastes burnt",
        "the dryer won't fire up",
        "the shock absorbers seem worn",
        "the ice in my freezer is melting",
        "the microwave door won't open",
        "how do I remove the turntable from the microwave",
        "my gas dryer is leaking water",
        "the gas stove ignites slowly",
        "the compressor is noisy at night",
        "the door seal is torn",
        "",
        None,
    ],
)
def test_benign_messages_have_no_keyword_hazard(text: str | None) -> None:
    assert keyword_hazards(text) == []


def test_high_voltage_category_rule() -> None:
    text = "how do I remove the back cover?"
    assert keyword_hazards(text) == []
    assert keyword_hazards(text, category="television") == ["high_voltage_internal"]
    assert keyword_hazards(text, category="dishwasher") == []


def test_detect_hazards_unions_both_layers() -> None:
    hits = detect_hazards("there is smoke", ["smoke_or_burning", "injury"])
    assert [(h.signal, h.source) for h in hits] == [
        ("smoke_or_burning", "both"),
        ("injury", "nlu"),
    ]
    assert [h.source for h in detect_hazards("sparks!", None)] == ["keywords"]
    assert detect_hazards(None) == []


def test_rule_table_covers_every_hazard() -> None:
    assert set(HAZARD_RULES) == set(SAFETY_TEMPLATES)
    assert set(HAZARD_RULES.values()) <= set(RULES)
    assert "water_near_electric" not in ESCALATING_HAZARDS
    for rule_id in ["G-SAFE-06", "G-WARR-01", "G-SCOPE-01", "G-LOOP-01", "G-PRIV-01"]:
        assert rule_id in RULES


def test_safety_replies_are_fixed_templates_with_cards() -> None:
    for hazard, template in SAFETY_TEMPLATES.items():
        reply = safety_reply(hazard)
        assert reply.text == template.text
        assert reply.card is not None and reply.card.hazard == hazard
        assert reply.card.instructions == list(template.instructions)
        assert reply.rule_id == HAZARD_RULES[hazard]
        assert reply.replaces_response == (hazard != "water_near_electric")
    assert STEP_TEMPLATES["out_of_scope"].rule_id == "G-SCOPE-01"


# --- plan post-processing ------------------------------------------------------------------


def item(id: str, **fields: object) -> PlanItem:
    return PlanItem.model_validate({"id": id, "instruction": id, "citation_ids": ["c"], **fields})


def test_postprocess_plan_applies_all_rules() -> None:
    items = [
        item("check"),
        item("uncited", citation_ids=[]),
        item("risky", risk_level="high"),
        item("open1", requires_disassembly=True),
        item("open2", requires_disassembly=True),
        item("test"),
        item("open3", requires_disassembly=True),
    ]
    result = postprocess_plan(items, category="dishwasher", in_warranty=True)
    assert [i.id for i in result.items] == [
        "check",
        "power-off-1",
        "open1",
        "open2",
        "test",
        "power-off-2",
        "open3",
    ]
    power_off = result.items[1]
    assert (power_off.instruction, power_off.safety_rule) == (POWER_OFF_INSTRUCTION, "G-SAFE-06")
    assert [i.warranty_warning for i in result.items if i.requires_disassembly] == [True] * 3
    reasons = [d.reason for d in result.decisions]
    assert "dropped uncited: no citation" in reasons
    assert "dropped risky: risk_level=high" in reasons
    assert all(d.kind == "plan" for d in result.decisions)


def test_postprocess_drops_items_not_in_english() -> None:
    french = item(
        "fr",
        instruction="Vérifiez que les portes du réfrigérateur et du congélateur se ferment bien.",
    )
    english = item("en", instruction="Check that the fridge and freezer doors close properly.")
    result = postprocess_plan([french, english], category="refrigerator")
    assert [i.id for i in result.items] == ["en"]
    assert [(d.reason, d.rule_id) for d in result.decisions] == [
        ("dropped fr: not in English", "G-INJ-01")
    ]


def test_postprocess_caps_and_forbids_high_voltage_disassembly() -> None:
    items = [*(item(f"p{i}") for i in range(1, 8)), item("open", requires_disassembly=True)]
    result = postprocess_plan(items, category="microwave")
    assert [i.id for i in result.items] == ["p1", "p2", "p3", "p4", "p5", "p6"]
    assert result.decisions[0].rule_id == "G-SAFE-03"
    assert "capped at 6" in result.decisions[-1].reason


def test_plan_helpers_individually() -> None:
    assert drop_uncited([item("s", citation_ids=[], safety_rule="G-SAFE-06")]).items
    assert drop_high_risk([item("a", risk_level="medium")]).decisions == []
    assert forbid_high_voltage_disassembly([item("a", requires_disassembly=True)], None).items
    flagged = flag_warranty([item("a", requires_disassembly=True)], in_warranty=False)
    assert not flagged.items[0].warranty_warning
    # an existing power-off item is not duplicated
    edit = insert_power_off(
        [item("off", safety_rule="G-SAFE-06"), item("a", requires_disassembly=True)]
    )
    assert [i.id for i in edit.items] == ["off", "a"]


# --- privacy -------------------------------------------------------------------------------


def test_privacy_flags_personal_data_requests() -> None:
    assert check_privacy("What's your home address?") == ["address"]
    assert check_privacy("Could you share your phone number and email?") == ["email", "phone"]
    assert check_privacy("Please provide your credit card.", booking_in_progress=True) == [
        "payment"
    ]
    assert check_privacy("What is your home address?", booking_in_progress=True) == []
    assert personal_data_requests("We never store your phone number.") == []
    assert personal_data_requests("Is the filter clean?") == []


# --- NLU schema ----------------------------------------------------------------------------


def test_nlu_schema_has_no_free_form_maps() -> None:
    schema = json.dumps(NLUResult.model_json_schema())
    assert "additionalProperties" not in schema
    parsed = NLUResult.model_validate_json(
        '{"intent": "report_problem", "slot_updates": [{"name": "symptom", "value": "leaks"}]}'
    )
    assert parsed.slot_updates[0].name == "symptom"
    assert parsed.user_sentiment == "neutral"


@pytest.mark.parametrize(
    ("text", "persists"),
    [
        ("I switched off the breaker but the outlet is still wet", True),
        ("There's still water on the floor and the power strip is still in it.", True),
        ("It's still dripping onto the outlet, so I'm worried.", True),
        (
            "The hose is fine, but the water and the power strip are still there.",
            True,
        ),
        ("Water keeps pooling around the power strip", True),
        ("The puddle around the plug hasn't gone away", True),
        ("Water still hasn't stopped dripping onto the outlet", True),
        ("The leak onto the power strip never stopped", True),
        ("Now water is spraying all over the outlet", True),
        ("The water hasn\N{RIGHT SINGLE QUOTATION MARK}t stopped dripping on the outlet", True),
        ("water won\N{RIGHT SINGLE QUOTATION MARK}t stop leaking near the outlet", True),
        ("It's dripping onto the outlet and it has not stopped", True),
        ("The water around the cord is spreading", True),
        ("The water stopped and the outlet is dry", False),
        ("OK, I turned the breaker off and mopped up the water", False),
        ("Breaker is off, the floor is dry now, water is gone", False),
        (
            "I dried the outlet, but the dishwasher still won't drain the water.",
            False,
        ),
        ("I unplugged the cord, but there's still standing water in the tub.", False),
        ("The power is still off and the water near the plug is cleaned up.", False),
        ("I unplugged the plug, but it's still leaking from the hose.", False),
        (None, False),
    ],
)
def test_water_persists_needs_cue_water_and_electricity_in_one_clause(
    text: str | None, persists: bool
) -> None:
    assert water_persists(text) is persists
