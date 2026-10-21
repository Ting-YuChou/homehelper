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
        ("I got a shock touching the door", ["sparks"]),
        ("water is leaking onto the power cord", ["water_near_electric"]),
        ("the outlet behind it is wet", ["water_near_electric"]),
        ("I think the refrigerant is leaking", ["refrigerant"]),
        ("how do I recharge freon in my fridge", ["refrigerant"]),
        ("how do I replace the magnetron", ["high_voltage_internal"]),
        ("can I open the microwave casing myself", ["high_voltage_internal"]),
        ("I cut my hand on the blade", ["injury"]),
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
