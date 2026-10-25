"""Deterministic guardrail rule table (spec §8.1).

Rules are enforced in different places; `enforced_by` says where, so a reader can find the code.
"""

from dataclasses import dataclass
from typing import Literal

from homehelper.agent.guardrails.plan import MAX_PLAN_ITEMS
from homehelper.agent.state import HazardSignal

RuleKind = Literal["hard", "soft", "structural"]


@dataclass(frozen=True)
class GuardrailRule:
    id: str
    trigger: str
    action: str
    kind: RuleKind
    enforced_by: str


RULES: dict[str, GuardrailRule] = {
    rule.id: rule
    for rule in [
        GuardrailRule(
            "G-SAFE-01",
            "Gas smell",
            "Fixed template (no switches, ventilate, leave, call the gas company); end DIY",
            "hard",
            "hazards.detect_hazards + journey guardrail hazard_detected",
        ),
        GuardrailRule(
            "G-SAFE-02",
            "Smoke, burning smell, sparks, electric shock",
            "Fixed template (unplug / breaker off if safe, stop using); escalate",
            "hard",
            "hazards.detect_hazards + journey guardrail hazard_detected",
        ),
        GuardrailRule(
            "G-SAFE-03",
            "Microwave or TV internals (magnetron, high-voltage capacitor), opening HV parts",
            "Refuse disassembly steps; escalate",
            "hard",
            "hazards.detect_hazards; plan.forbid_high_voltage_disassembly",
        ),
        GuardrailRule(
            "G-SAFE-04",
            "Refrigerant, sealed system",
            "Fixed template; escalate",
            "hard",
            "hazards.detect_hazards + journey guardrail hazard_detected",
        ),
        GuardrailRule(
            "G-SAFE-05",
            "Water and electricity together",
            "Fixed template first (breaker off), then continue the journey",
            "hard",
            "hazards.detect_hazards (prefix reply, no escalation)",
        ),
        GuardrailRule(
            "G-SAFE-06",
            "Any disassembly step",
            "A power-off step must come first (inserted by code)",
            "structural",
            "plan.insert_power_off",
        ),
        GuardrailRule(
            "G-SAFE-07",
            "Someone is injured (cut, burn, electric shock)",
            "Fixed template (seek medical help, stop using); escalate",
            "hard",
            "hazards.detect_hazards + journey guardrail hazard_detected",
        ),
        GuardrailRule(
            "G-SAFE-08",
            "A hazard that told the user to cut the power (water near electricity, smoke, "
            "sparks) for that appliance, or a gas smell for any",
            "No step that needs the power on, the appliance running, or an outlet or cord: the "
            "planner is told, and code skips such steps (not counted as failed); a plan left "
            "with only those hands off for that reason",
            "structural",
            "plan.skip_powered at plan.build; transition._skip_powered_steps every turn; "
            "predicate only_powered_steps_left",
        ),
        GuardrailRule(
            "G-WARR-01",
            "Under warranty + disassembly step",
            "Warn that the warranty may be voided; offer warranty service",
            "soft",
            "plan.flag_warranty (PlanItem.warranty_warning)",
        ),
        GuardrailRule(
            "G-SCOPE-01",
            "Not about home appliances",
            "Fixed polite decline and steer back",
            "hard",
            "engine route (out_of_scope journey or side reply)",
        ),
        GuardrailRule(
            "G-LOOP-01",
            "6 failed steps (every planned step), or 2 consecutive frustrated turns",
            "Offer a referral",
            "soft",
            "journey guardrail max_failed_steps_reached; engine notice for frustration",
        ),
        GuardrailRule(
            "G-INJ-01",
            "Instruction-like text in web content or user messages",
            "Treat as data, never execute; log to trace",
            "structural",
            "knowledge layer (spec §10.6)",
        ),
        GuardrailRule(
            "G-PRIV-01",
            "Asking for address, phone, or other personal data outside booking",
            "Supervisor check",
            "soft",
            "privacy.check_privacy",
        ),
    ]
}

HAZARD_RULES: dict[HazardSignal, str] = {
    "gas_smell": "G-SAFE-01",
    "smoke_or_burning": "G-SAFE-02",
    "sparks": "G-SAFE-02",
    "high_voltage_internal": "G-SAFE-03",
    "refrigerant": "G-SAFE-04",
    "water_near_electric": "G-SAFE-05",
    "injury": "G-SAFE-07",
}

# Hazards that end DIY help. Water near electricity only requires a power-off first (G-SAFE-05).
ESCALATING_HAZARDS: frozenset[HazardSignal] = frozenset(HAZARD_RULES) - {"water_near_electric"}

# G-LOOP-01: every planned step was tried (the plan cap, so no step is cut off unseen).
MAX_FAILED_STEPS = MAX_PLAN_ITEMS
MAX_FRUSTRATED_TURNS = 2  # G-LOOP-01
