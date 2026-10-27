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
    BLADE_CAUTION,
    POWER_OFF_INSTRUCTION,
    caution_blades,
    drop_high_risk,
    drop_uncited,
    flag_warranty,
    forbid_high_voltage_disassembly,
    handles_blade,
    insert_power_off,
    needs_power,
    skip_powered,
    without_caution,
)
from homehelper.agent.guardrails.privacy import personal_data_requests
from homehelper.agent.guardrails.templates import SAFETY_TEMPLATES, STEP_TEMPLATES
from homehelper.agent.state import AgentState, NLUResult, PlanItem

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


def test_a_damaged_cord_comes_from_the_nlu_only() -> None:
    # G-SAFE-09 has no keyword rule: a reply to "check the cord" must not end the repair.
    for text in [
        "the cord is frayed",
        "Checked for a damaged cord - all good",
        "The cord looks frayed but it's just lint.",
    ]:
        assert keyword_hazards(text) == []
    hits = detect_hazards("the cord is frayed", ["damaged_cord"])
    assert [(h.signal, h.source) for h in hits] == [("damaged_cord", "nlu")]
    assert "damaged_cord" in ESCALATING_HAZARDS


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


def test_a_step_that_handles_a_blade_starts_with_the_caution() -> None:
    stuck = "Using extreme care, use a little extra force to remove the blade."
    items = [item("p1", instruction=stuck), item("p2", instruction="Check the jar base.")]
    result = postprocess_plan(items, category="blender_food_processor")
    assert [i.instruction for i in result.items] == [
        f"{BLADE_CAUTION} {stuck}",
        "Check the jar base.",
    ]
    assert [(d.reason, d.rule_id) for d in result.decisions] == [
        ("blade caution on p1", "G-SAFE-10")
    ]
    # once is enough, even if the plan is post-processed again
    assert caution_blades(result.items, "blender_food_processor").decisions == []
    assert without_caution(result.items[0].instruction) == stuck
    # other appliances' "blades" are a power plug's prongs or a fan's
    assert postprocess_plan(items, category="vacuum").items == items


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        ("Remove the gasket and blade assembly.", True),
        ("Carefully remove food from the blade.", True),
        ("Check that the blade unit is securely fastened onto the tumbler jar.", True),
        ("Unplug the blender, refit the blade assembly, then plug it back in.", True),
        ("Lower it into the jar, blades down.", True),
        ("Remove the slicing disc and clear the food wedged under it.", True),
        ("Lift out the dicing grid and the cutter assembly.", True),
        ("Remove the adjustable slicer and clear the jammed food.", True),
        ("Make sure the plug blades are not bent.", False),
        ("This blender has a polarized plug (one wide blade); it fits one way only.", False),
        ("A polarized plug has two blades with one wider than the other; reverse it.", False),
        ("Make sure the plug blades can be fully inserted into the outlet.", False),
        ("Check that the jar base is screwed on tightly.", False),
    ],
)
def test_handles_blade(instruction: str, expected: bool) -> None:
    step = PlanItem(id="p1", instruction=instruction)
    assert handles_blade(step, "blender_food_processor") is expected
    if expected:  # code-inserted safety items never get the caution
        inserted = step.model_copy(update={"safety_rule": "G-SAFE-06"})
        assert not handles_blade(inserted, "blender_food_processor")


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


# The wording rules are a backstop for the planner's `requires_power` flag: they must never
# skip a safe step (hose and water work, cleaning, levelling, parts, power-off, warnings,
# symptom clauses), and must catch wording that can't mean anything else.
SAFE_STEPS = [
    "If you notice the washer won't start a cycle, check the door latch.",
    "When you notice the oven won't start the program, check the clock setting.",
    "Check the lid switch if the washer won't start a cycle.",
    "Check the door latch when the dishwasher doesn't start a cycle.",
    "Inspect the latch, since the dishwasher cannot start a cycle with a broken latch.",
    "The washer will not start a cycle with the lid open, so check the lid switch.",
    "Never, even if the floor looks dry, turn the power back on yourself.",
    "Unplug the refrigerator, then disconnect the ice maker harness and plug it back in firmly.",
    "Run a toothpick around the program indicator lights.",
    "Select the new cycle control board that matches your model number.",
    "Select the correct cycle thermostat for your model.",
    "Check that the door seal is seated in its track.",
    "Clean the filter at the bottom of the tub.",
    "Check that the drain hose is not kinked.",
    "Use only detergent made for dishwashers.",
    "Remove and rinse the spray arms.",
    "Clean the drain outlet at the bottom of the tub.",
    "Clear any blockage from the pump outlet.",
    "Check that the water inlet and outlet hoses are not kinked.",
    "Remove the drain plug in the lower front corner and let the water out.",
    "Use a socket wrench to loosen the leveling legs.",
    "Run the drain hose up to the countertop and secure it.",
    "Let the dishwasher cool before removing the filter.",
    "Watch for kinks as you straighten the drain hose.",
    "Check whether it comes up through the air gap.",
    "Leave the door open after the cycle so the tub can dry.",
    "Use a dishwasher rinse aid.",
    "Use running water to rinse the filter.",
    "Use a soft cloth to wash the gasket.",
    "Check that the fan turns freely by hand.",
    "Plug the drain hose into the standpipe.",
    "Do a test fit of the new filter.",
    "Do not run a cycle until the floor is dry.",
    "Switch off the breaker for the dishwasher.",
    "Turn on the water supply valves.",
    "Don't run the dishwasher until the floor is dry.",
    "Do not turn the power back on until the area is dry.",
    "Do not use an extension cord.",
    "Do not turn the circuit breaker back on until the floor is dry.",
    "Do not reconnect power until a technician has checked the wiring.",
    "Never plug the washer back in while the floor is wet.",
    "You must not run the dishwasher until the floor is dry.",
    "Make sure not to run the washer until the leak is fixed.",
    "Do not plug the unit back in or turn the breaker on until it is dry.",
    "Don\u2019t run the dishwasher until the floor is dry.",
    "Do not, under any circumstances, run the dryer while it is wet.",
    "Don't forget to unplug the washer first.",
    "Disconnect the drain hose, clear the clog, and reconnect it.",
    "Reconnect the drain hose and tighten the clamp.",
    "Reconnect the water supply line to the refrigerator.",
    "Reconnect the dryer vent duct and seal it with foil tape.",
    "Reconnect the hose to the vacuum wand.",
    "Reconnect the tubing to the purifier filter head.",
    "Clean the inlet hose screens, then reconnect the hoses hand-tight.",
    "Screw the filter cap on again.",
    "Put the lid on again and wipe the reservoir.",
    "Remove the kick plate, then on the left side locate the drain hose.",
    "Wipe the gasket, then on the bottom of the door clean the drain holes.",
    "If the dishwasher drains into a garbage disposal, make sure the knockout plug is out.",
    "If the dishwasher drains through an air gap, clean the air gap.",
    "Straighten the drain hose so it runs downhill to the standpipe.",
    "Make sure the vent duct is short and it runs straight to the outside.",
    "Turn the drum by hand and check that it spins freely.",
    "Push the rack in and check that it runs smoothly on the rollers.",
    "If the refrigerator runs constantly, clean the condenser coils.",
    "If the compressor is running but the fridge is warm, check the door gasket.",
    "If the pump is running but no water drains, clean the filter.",
    "If the washer drains slowly, clean the pump filter.",
    "If it fills slowly, clean the inlet screens.",
    "Pour a cup of water into the tub and check that it drains.",
    "Mop up the water around the washer.",
    "Clean the lint filter.",
    "Rinse the dishwasher filter under running water.",
    "Check the door seal for debris.",
    "Empty the dust bin and wash the filter.",
    "Replace the water filter cartridge.",
    "Descale the coffee maker reservoir with vinegar.",
    "Wipe the microwave interior with a damp cloth.",
    "Check the inlet hose for kinks.",
    "Check the defrost drain in the freezer for ice.",
    "Clear the vacuum hose of blockages.",
    "Turn the breaker for the washer off.",
    "Switch the circuit breaker to the OFF position.",
    "Flip the breaker off before you remove the panel.",
    "Turn off the breaker.",
    "Never operate the dryer without the lint filter in place.",
    "Do not restore power until all panels are reinstalled.",
    "Never reset a breaker that trips repeatedly; call an electrician.",
    "Avoid running the dishwasher until the leak is repaired.",
    "Do not operate the washer with the lid open.",
    "Under no circumstances should you run the oven with the door removed.",
    "It is not safe to plug the TV back in until the water has evaporated.",
    "Unplug the unit and do not plug it back in until it has dried for 24 hours.",
    "You should never run the vacuum over wet surfaces.",
    "Do not attempt to start the dryer before the duct has been reattached.",
    "Never use an extension cord with the dryer.",
    "Never connect the microwave to an extension lead or power strip.",
    "Mop up the water, and never run the washer while the floor is wet.",
    "Make sure the breaker is not turned back on while you work.",
    "Ensure the power is not switched back on until the repair is done.",
    "Refrain from using the oven until it has been inspected.",
    "If it can't heat water, do not run another cycle; call for service.",
    "Keep the dishwasher off; running it now could cause a shock.",
    "Turn off the water supply valve behind the washer.",
    "Disconnect the inlet hoses and flush them in a bucket.",
    "Reconnect the ice maker supply line and open the shutoff valve.",
    "Turn the water back on and check the fittings for leaks.",
    "Plug the drain hole with the rubber stopper.",
    "Check that the drain hose runs downhill to the standpipe.",
    "Confirm that the vent duct runs straight to the outside wall.",
    "Reattach the vent hose to the dryer exhaust and secure the clamp.",
    "Open the faucet and let water run for 5 minutes to flush the filter.",
    "Pour two cups of water into the bottom of the dishwasher to check the drain.",
    "Soak the filter in warm soapy water for 10 minutes.",
    "Vacuum the condenser coils at the bottom of the refrigerator.",
    "Wash the pre-filter under running water and let it air dry.",
    "Wipe the display panel with a dry cloth; do not spray cleaner on the screen.",
    "Clean the brush roll and remove tangled hair.",
    "Fill the coffee maker reservoir with equal parts vinegar and water.",
    "Dry the drum with a towel.",
    "Adjust the front leveling legs until the washer no longer rocks.",
    "Turn the leveling legs on the range until the bubble is centered.",
    "Raise the front of the refrigerator by turning the leveling screws clockwise.",
    "Replace the thermal fuse on the blower housing.",
    "Replace the microwave's ceramic line fuse with one of the same rating.",
    "Use a multimeter to check whether the heating element works.",
    "Check that the door latch works.",
    "Close the door and listen for the latch to click.",
    "Check that the evaporator fan blade spins without rubbing.",
    "Snap the circuit board cover back on.",
    "Put the fuse box cover back on.",
    "Reconnect the wire harness to the drain pump.",
    "Inspect the power cord for cuts or scorching.",
    "Replace the light bulb with a 40 W appliance bulb.",
    "Replace the drive belt and route it around the motor pulley.",
    "Unplug the coffee maker and let it cool.",
    "Switch off the appliance at the wall socket.",
    "Unplug the TV from the wall outlet.",
    "Disconnect the power cord from the outlet.",
    "Turn off power to the range at the breaker box.",
    "Leave the refrigerator unplugged for 8 hours to defrost the evaporator.",
    "If the washer stops mid-cycle, check the lid switch.",
    "If water leaks during the cycle, inspect the door gasket.",
    "If the display shows E24, clean the drain filter.",
    "If the error code on the display is F21, clean the pump filter.",
    "If the microwave turns on by itself, unplug it immediately.",
    "If the TV turns on but there is no picture, check the HDMI cable.",
    "If the oven light comes on but the oven does not heat, replace the bake element.",
    "If the ice maker does not dispense ice, check that the ice bin is seated.",
    "If the dryer runs but does not heat, test the thermal fuse.",
    "If the coffee maker brews slowly, descale it.",
    "If the breaker trips again, leave it off and call an electrician.",
    "Close the water valve, replace the inlet hose washer, then turn it back on.",
    "Shut off the water, replace the hose washer, and turn it back on.",
    "Route the drain hose behind the dishwasher and run it on the left side of the cabinet.",
    "Tighten the hose clamp with a flat screwdriver.",
    "Lower the end of the drain hose into a bucket to let the water out.",
    "Check that the inlet hose is not crushed behind the washer.",
    "Make sure the drain hose loop is at least 20 inches above the floor.",
    "Replace the rubber washer inside the hose coupling.",
    "Open the water shutoff valve fully.",
    "Flush the supply line into a bucket for one minute.",
    "Push the drain hose no more than 6 inches into the standpipe.",
    "Wrap the threads with plumber's tape and screw the hose back on.",
    "Run a cloth over the program dial to remove grease.",
    "Wipe the control panel with a slightly damp cloth.",
    "Scrub the spray arm holes with a toothpick.",
    "Clean the condenser coils with a coil brush.",
    "Rinse the coarse filter under the tap.",
    "Soak the carafe in a vinegar solution overnight.",
    "Wipe the door gasket with diluted bleach.",
    "Clear lint from the vent hood outside.",
    "Brush the dust off the purifier pre-filter.",
    "Empty and wash the water reservoir.",
    "Level the washer by adjusting the front feet.",
    "Place a spirit level on top of the dryer and adjust the legs.",
    "Tighten the lock nuts on the leveling feet against the cabinet.",
    "Tilt the refrigerator back slightly so the doors close on their own.",
    "Mount the new thermal fuse back on the exhaust duct and reconnect the two wires.",
    "Snap the thermal fuse back on its bracket.",
    "Unplug the wire harness connectors, inspect the pins, and plug them back in.",
    "Disconnect the ice maker harness, check for corrosion, then plug it back in.",
    "Select the replacement program board that matches your model number.",
    "Install the new door gasket starting at the top corner.",
    "Swap the worn drive belt for a new one.",
    "Replace the water inlet valve with the same part number.",
    "Fit the new door switch and secure it with the two screws.",
    "Replace the charcoal filter in the range hood.",
    "Replace the vacuum's HEPA filter.",
    "Replace the remote control batteries.",
    "Switch off the dryer's breaker at the panel.",
    "Pull the plug out of the wall socket.",
    "Turn the breaker for the oven to OFF.",
    "Remove the fuse for the dishwasher circuit.",
    "Unplug the purifier before opening the filter door.",
    "Keep the washer unplugged while the floor dries.",
    "Never \u2014 even if the floor looks dry \u2014 turn the power back on yourself.",
    "Do not plug the unit back in, or turn the breaker back on, until the floor is dry.",
    "Do not touch the outlet with wet hands.",
    "Stay off the wet floor near the appliance.",
    "Keep children away from the open dishwasher door.",
    "Wear gloves; the edges of the panel are sharp.",
    "There is no need to run a cycle after cleaning the filter.",
    "Leave the breaker off until an electrician has checked the outlet.",
    "If the dishwasher won't start a cycle, check that the door latch clicks shut.",
    "If the washer doesn't start the cycle, check the lid switch.",
    "If the dishwasher will not run a cycle, check that the door is latched.",
    "If the display flashes when you press Start, check the door latch.",
    "If the breaker trips when you turn the power back on, call an electrician.",
    "If it stopped mid-program, check the drain filter for debris.",
    "If the fridge clicks every few minutes, clean the condenser coils.",
    "If water pools under the washer, check the drain hose connection.",
    "If the vacuum smells burnt, check the belt.",
    "If the microwave sparks, remove any metal and clean the waveguide cover.",
    "If the coffee maker leaks, check that the carafe is seated.",
    "If the oven fan is loud, check that nothing is touching the fan blade.",
    "If the purifier is noisy, reseat the filter.",
    "If the TV has no sound, check that the speaker cable is connected.",
]
UNMISTAKABLE_POWER_STEPS = [
    "Make sure the drum doesn't wobble and run a Spin cycle.",
    "Check that the door won't open and run a rinse cycle.",
    "If needed - turn the breaker back on.",
    "When finished, plug the dryer back in.",
    "When you run a cycle, listen for the drain pump.",
    "If the light is off, turn the circuit breaker back on.",
    "When the floor is dry, plug the dishwasher back in.",
    "Turn the circuit breaker back on.",
    "Flip the main breaker back to ON.",
    "Switch the breaker back on.",
    "Turn the power back on and wait for the display to light up.",
    "Turn on the circuit breaker.",
    "Reset the tripped circuit breaker.",
    "Reset the tripped breaker at the panel.",
    "Unplug the TV for 60 seconds, then plug it back in.",
    "Plug the refrigerator back in after the coils have thawed.",
    "Plug in the coffee maker.",
    "Reconnect power to the washer.",
    "Restore power to the refrigerator.",
    "Turn the dishwasher back on.",
    "Add a tablespoon of vegetable oil to the empty tub and run a cycle.",
    "Run a rinse cycle.",
    "Start a Rinse Only cycle to check for leaks.",
    "Run two descaling cycles with fresh water.",
    "Run the dishwasher empty with a cup of white vinegar on the top rack.",
    "Run the dryer empty.",
    "Select the Quick Wash cycle and press Start.",
    "Press Start to resume the program.",
    "Make sure not to overfill the drum, then run a Rinse & Spin cycle.",
    "Do not add detergent, and run a Normal cycle with the tub empty.",
    "Don't forget to run a rinse cycle afterwards.",
]


@pytest.mark.parametrize("instruction", SAFE_STEPS)
def test_the_wording_backstop_never_skips_a_safe_step(instruction: str) -> None:
    assert not needs_power(item("a", instruction=instruction))


@pytest.mark.parametrize("instruction", UNMISTAKABLE_POWER_STEPS)
def test_the_wording_backstop_catches_unmistakable_power_steps(instruction: str) -> None:
    assert needs_power(item("a", instruction=instruction))


def test_the_planner_flag_decides_the_rest() -> None:
    step = "Close the door and check whether the dishwasher starts."
    assert not needs_power(item("a", instruction=step))
    assert needs_power(item("a", instruction=step, requires_power=True))


def test_postprocess_skips_powered_steps_after_a_power_off_hazard() -> None:
    items = [
        item("cycle", instruction="Run a rinse cycle."),
        item("seal", instruction="Check the door seal."),
        item("flagged", instruction="Check the spray arm.", requires_power=True),
    ]
    result = postprocess_plan(items, category="dishwasher", hazards=["water_near_electric"])
    # Skipped, not removed, and last: a handoff can say why.
    assert [(i.id, i.status, i.safety_rule) for i in result.items] == [
        ("seal", "pending", None),
        ("cycle", "skipped", "G-SAFE-08"),
        ("flagged", "skipped", "G-SAFE-08"),
    ]
    assert [(d.reason, d.rule_id) for d in result.decisions] == [
        ("skipped cycle: needs power after water_near_electric", "G-SAFE-08"),
        ("skipped flagged: needs power after water_near_electric", "G-SAFE-08"),
    ]
    # No hazard, or one that doesn't cut the power: the plan is unchanged.
    assert [i.status for i in postprocess_plan(items, category="dishwasher").items] == [
        "pending"
    ] * 3
    assert not skip_powered(items, ["refrigerant"]).decisions
    # Code-inserted safety items and steps already tried are left alone.
    tried = item("cycle", instruction="Run a rinse cycle.", status="done_not_fixed")
    safety = item("off", instruction="Plug it back in.", safety_rule="G-SAFE-06")
    panel = item("panel", instruction="Remove the back panel.", requires_disassembly=True)
    assert skip_powered([tried, safety, panel], ["sparks"]).items == [tried, safety, panel]


def test_skipped_steps_stay_outside_the_plan_cap() -> None:
    items = [item("cycle", instruction="Run a cycle."), *(item(f"p{i}") for i in range(1, 7))]
    result = postprocess_plan(items, category="dishwasher", hazards=["sparks"])
    assert [i.id for i in result.items] == ["p1", "p2", "p3", "p4", "p5", "p6", "cycle"]


def test_power_off_applies_to_the_issue_its_appliance_and_gas_everywhere() -> None:
    from homehelper.agent.guardrails.hazards import issue_power_off
    from homehelper.agent.state import IssueRecord, SlotValue

    def state(issue_id: str, category: str | None) -> AgentState:
        slot = SlotValue(value=category or "", source="user", confidence=1.0)
        slots = {"appliance_category": slot} if category else {}
        return AgentState(
            conversation_id="c",
            release_id="r",
            active_issue_id=issue_id,
            slots=slots,
            issues=[
                IssueRecord(
                    issue_id="iss_1", journey="troubleshoot", appliance_category="dishwasher"
                ),
                IssueRecord(issue_id="iss_2", journey="troubleshoot", appliance_category="dryer"),
                IssueRecord(issue_id="iss_3", journey="troubleshoot", appliance_category="dryer"),
            ],
            power_off={
                "issue:iss_1": ["water_near_electric"],
                "washing_machine": ["sparks"],
                "*": ["gas_smell"],
            },
        )

    assert issue_power_off(state("iss_1", "dishwasher")) == ["gas_smell", "water_near_electric"]
    # Another issue on the dishwasher inherits iss_1's hazard; one on the dryer doesn't.
    assert issue_power_off(state("iss_4", "dishwasher")) == ["gas_smell", "water_near_electric"]
    assert issue_power_off(state("iss_2", "dryer")) == ["gas_smell"]
    # Named in the text about the washer.
    assert issue_power_off(state("iss_5", "washing_machine")) == ["gas_smell", "sparks"]
    assert issue_power_off(state("iss_6", None)) == ["gas_smell"]


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


def test_a_replan_with_only_powered_steps_keeps_the_steps_left_to_try() -> None:
    from homehelper.agent.guardrails.plan import merge_plan

    current = [
        item("p1", status="done_not_fixed"),
        item("p2", status="presented"),
        item("p3"),
    ]
    new = [item("p1", instruction="Run a cycle.", status="skipped", safety_rule="G-SAFE-08")]
    edit = merge_plan(current, new)
    assert edit.items == current
    assert [d.reason for d in edit.decisions] == [
        "kept the current plan: every new step needs the power"
    ]
    # With nothing left to try, the skipped steps come in, so the handoff can say why.
    tried = [item("p1", status="done_not_fixed")]
    merged = merge_plan(tried, new).items
    assert [(i.id, i.status) for i in merged] == [("p1", "done_not_fixed"), ("p2", "skipped")]


def test_a_power_off_item_whose_step_was_skipped_is_skipped_too() -> None:
    plan = [
        item("p1", status="done_not_fixed"),
        item("power-off-1", instruction=POWER_OFF_INSTRUCTION, safety_rule="G-SAFE-06"),
        item("p2", instruction="Open the panel and run a test cycle.", requires_disassembly=True),
        item("power-off-2", instruction=POWER_OFF_INSTRUCTION, safety_rule="G-SAFE-06"),
        item("p3", instruction="Remove the kick plate.", requires_disassembly=True),
    ]
    edit = skip_powered(plan, ["water_near_electric"])
    assert [(i.id, i.status) for i in edit.items] == [
        ("p1", "done_not_fixed"),
        ("power-off-1", "skipped"),
        ("p2", "skipped"),
        ("power-off-2", "pending"),  # still guards p3
        ("p3", "pending"),
    ]


def test_a_power_off_item_still_guarding_its_run_stays() -> None:
    drafted = [
        item("p1", instruction="Clean the filter."),
        item("p2", instruction="Remove the panel and run a test cycle.", requires_disassembly=True),
        item("p3", instruction="Remove the kick plate.", requires_disassembly=True),
    ]
    built = postprocess_plan(drafted, category="dishwasher").items
    assert [i.id for i in built] == ["p1", "power-off-1", "p2", "p3"]
    built[0] = built[0].model_copy(update={"status": "done_not_fixed"})
    edit = skip_powered(built, ["water_near_electric"])
    assert [(i.id, i.status) for i in edit.items] == [
        ("p1", "done_not_fixed"),
        ("power-off-1", "pending"),  # p3 is still to try, after the power-off
        ("p2", "skipped"),
        ("p3", "pending"),
    ]
