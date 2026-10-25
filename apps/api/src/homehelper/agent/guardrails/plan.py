"""Pure post-processing of a planner-generated Solution Plan (spec §7.6, P1, P3).

`plan.build` (M3-07) calls `postprocess_plan` on the planner output; each helper is usable alone.
Every removal or insertion is returned as a `Decision` for the decision log (P7). A plan built
again for a better-identified appliance is joined to the steps already tried by `merge_plan`
(ADR-013).
"""

import re
from collections.abc import Iterable

from pydantic import BaseModel, Field

from homehelper.agent.guardrails.hazards import HIGH_VOLTAGE_CATEGORIES, POWER_OFF_HAZARDS
from homehelper.agent.guardrails.language import looks_english
from homehelper.agent.state import Decision, PlanItem

MAX_PLAN_ITEMS = 6
WEB_ID_PREFIX = "web-"  # web findings' ids (`knowledge.web.finding_id`)
TRIED: frozenset[str] = frozenset({"done_not_fixed", "skipped"})

POWER_OFF_INSTRUCTION = (
    "Before you go further, unplug the appliance or switch off its circuit breaker, and keep it "
    "off while you work."
)
POWER_OFF_ID_PREFIX = "power-off"
POWER_OFF_RULE = "G-SAFE-08"

_APPLIANCE = (
    r"the\s+(\w+\s+)?(appliance|machine|unit|dishwasher|washer|dryer|microwave|oven|range|"
    r"fridge|refrigerator|freezer|coffee\s+maker|vacuum|tv|television|purifier)"
)
_NOT_A_PREPOSITION = (
    r"(?!(over|through|along|across|under|on|in|into|to|from|with|for|around|behind|between|"
    r"down|past)\b)"
)
# A backstop for the planner's `requires_power` flag (the main defence, measured at 3 misses in
# 282 typical steps), not a classifier: only wording that can't mean anything else, so a safe
# step is never skipped. It deliberately misses many powered steps; the flag catches those.
_NEEDS_POWER = re.compile(
    "|".join(
        (
            # Giving the power back.
            r"\b(breaker|electricity|power)\s+back\s+(on|to\s+(the\s+)?on)\b",
            r"\b(turn|switch|flip)\s+on\s+(the\s+)?(main\s+|circuit\s+)?(breaker|power|electricity)\b",
            r"\breset\s+(the\s+)?(tripped\s+|main\s+)?(circuit\s+)?breaker\b",
            r"\bplug(ged|ging)?\s+" + _APPLIANCE + r"\s+(back\s+)?in\b",
            r"\bplug\s+in\s+" + _APPLIANCE + r"\b",
            # "it" is the appliance only when nothing else was disconnected in between.
            r"\bunplug\s+" + _APPLIANCE + r"\b"
            r"((?!\b(disconnect|unplug|remove|detach|harness|hose|connector|wire)\w*\b)[^.;])*"
            r"\bplug\s+it\s+(back\s+)?in\b",
            r"\b(reconnect|restore)\s+(the\s+)?power\b",
            r"\b(turn|switch|power)\s+" + _APPLIANCE + r"\s+back\s+on\b",
            # Running it.
            r"\b(run|start|select)\s+(a|an|the|another|one|two|its)\s+"
            r"(" + _NOT_A_PREPOSITION + r"[\w&/-]+\s+){0,3}"
            r"(cycles?|programs?|programmes?)\b"
            r"(?!\s+(board|dial|knob|selector|card|timer|buttons?|panel|control|lights?|"
            r"indicator|thermostat|module|chart))",
            r"\b(run|start|operate)\s+" + _APPLIANCE + r"\s+(empty|for|on|with|again)\b",
            r"\bpress\s+(the\s+)?start\b",
        )
    ),
    re.IGNORECASE,
)
# Warnings ("Do not run a cycle until the floor is dry") and symptom clauses ("If it won't
# start a cycle, check the latch") are not steps that need the power. A match is negated by a
# negation earlier in its clause (clauses end at a comma or a dash), or by a sentence that
# starts with one unless its clause turns with ", and / but / then" ("Do not add detergent,
# and run a Normal cycle" is a step). Inside a leading "If/When ..." clause (not "if you"),
# a match is a symptom. Known gap, left to the planner flag: a warning followed by a dash or a
# comma splice ("Don't overload the drum - run a rinse cycle") hides the step after it.
_SENTENCE_END = re.compile(r"[.;:!?]")
_CLAUSE_BREAK = re.compile(r"[,\u2013\u2014]|\s-\s")
_NEGATED_CLAUSE = re.compile(
    r"\b(do\s+not|don't|never|must\s+not|should\s+not|not\s+to|avoid|refrain|"
    r"under\s+no\s+circumstances|not\s+safe|unsafe|no\s+need\s+to)\b(?!\s+forget\b)",
    re.IGNORECASE,
)
# Symptom wording negates the verb right after it ("the washer won't start a cycle", "check
# the latch if it doesn't run a cycle"), wherever it is; "make sure the drum doesn't wobble
# and run a Spin cycle" is still a step.
_SYMPTOM_NEGATION = re.compile(
    r"\b(won't|doesn't|didn't|does\s+not|did\s+not|will\s+not|can't|cannot|isn't|is\s+not)"
    r"\s+(\w+ly\s+)?$",
    re.IGNORECASE,
)
_WARNING_SENTENCE = re.compile(
    r"^\s*(you\s+)?(do\s+not|don't|never|must\s+not|should\s+not|avoid|"
    r"under\s+no\s+circumstances)\b(?!\s+forget\b)",
    re.IGNORECASE,
)
_TURNS = re.compile(r"^\s*(and|but|then)\b", re.IGNORECASE)
_SYMPTOM = re.compile(r"^\s*(if|when)\b(?!\s+you\b)", re.IGNORECASE)
_LOOKBACK = 400  # characters searched for the sentence start: instructions are short


def _mentions_power(text: str) -> bool:
    text = text.replace("\u2019", "'")
    for match in _NEEDS_POWER.finditer(text):
        window = max(0, match.start() - _LOOKBACK)
        ends = [m.end() for m in _SENTENCE_END.finditer(text, window, match.start())]
        sentence = text[ends[-1] if ends else window : match.start()]
        breaks = [m.end() for m in _CLAUSE_BREAK.finditer(sentence)]
        clause = sentence[breaks[-1] if breaks else 0 :]
        symptom = bool(_SYMPTOM.search(sentence))
        if symptom and not breaks:
            continue  # inside the If/When clause itself
        if _NEGATED_CLAUSE.search(clause) or _NEGATED_CLAUSE.search(match.group(0)):
            continue
        if _SYMPTOM_NEGATION.search(clause):
            continue
        if _WARNING_SENTENCE.search(sentence) and not _TURNS.search(clause):
            continue
        return True
    return False


class PlanEdit(BaseModel):
    items: list[PlanItem]
    decisions: list[Decision] = Field(default_factory=list)


def _plan_decision(reason: str, rule_id: str | None = None) -> Decision:
    return Decision(kind="plan", rule_id=rule_id, reason=reason)


def drop_uncited(items: Iterable[PlanItem]) -> PlanEdit:
    """P3: items without a citation are removed (code-inserted safety items are exempt)."""
    kept: list[PlanItem] = []
    decisions: list[Decision] = []
    for item in items:
        if item.citation_ids or item.safety_rule:
            kept.append(item)
        else:
            decisions.append(_plan_decision(f"dropped {item.id}: no citation"))
    return PlanEdit(items=kept, decisions=decisions)


def drop_non_english(items: Iterable[PlanItem]) -> PlanEdit:
    """G-INJ-01: an item in another language means the planner followed injected text."""
    kept: list[PlanItem] = []
    decisions: list[Decision] = []
    for item in items:
        if looks_english(item.instruction):
            kept.append(item)
        else:
            decisions.append(_plan_decision(f"dropped {item.id}: not in English", "G-INJ-01"))
    return PlanEdit(items=kept, decisions=decisions)


def drop_high_risk(items: Iterable[PlanItem]) -> PlanEdit:
    kept: list[PlanItem] = []
    decisions: list[Decision] = []
    for item in items:
        if item.risk_level == "high":
            decisions.append(_plan_decision(f"dropped {item.id}: risk_level=high"))
        else:
            kept.append(item)
    return PlanEdit(items=kept, decisions=decisions)


def is_web_only(item: PlanItem) -> bool:
    return bool(item.citation_ids) and all(c.startswith(WEB_ID_PREFIX) for c in item.citation_ids)


def limit_web_only(items: Iterable[PlanItem]) -> PlanEdit:
    """Spec §10.6 ③: a step only an unofficial web page supports is at least medium risk, and
    never one that opens the appliance."""
    kept: list[PlanItem] = []
    decisions: list[Decision] = []
    for item in items:
        if not is_web_only(item):
            kept.append(item)
        elif item.requires_disassembly:
            decisions.append(_plan_decision(f"dropped {item.id}: disassembly from a web page"))
        elif item.risk_level == "low":
            kept.append(item.model_copy(update={"risk_level": "medium"}))
            decisions.append(_plan_decision(f"{item.id} from a web page: risk_level=medium"))
        else:
            kept.append(item)
    return PlanEdit(items=kept, decisions=decisions)


def forbid_high_voltage_disassembly(items: Iterable[PlanItem], category: str | None) -> PlanEdit:
    """G-SAFE-03: no disassembly steps for appliances with high-voltage internals."""
    items = list(items)
    if category not in HIGH_VOLTAGE_CATEGORIES:
        return PlanEdit(items=items)
    kept: list[PlanItem] = []
    decisions: list[Decision] = []
    for item in items:
        if item.requires_disassembly:
            decisions.append(
                _plan_decision(f"dropped {item.id}: disassembly of a {category}", "G-SAFE-03")
            )
        else:
            kept.append(item)
    return PlanEdit(items=kept, decisions=decisions)


def flag_warranty(items: Iterable[PlanItem], in_warranty: bool) -> PlanEdit:
    """G-WARR-01: disassembly items of an appliance under warranty carry a warning."""
    flagged: list[PlanItem] = []
    decisions: list[Decision] = []
    for item in items:
        if in_warranty and item.requires_disassembly and not item.warranty_warning:
            item = item.model_copy(update={"warranty_warning": True})
            decisions.append(_plan_decision(f"warranty warning on {item.id}", "G-WARR-01"))
        flagged.append(item)
    return PlanEdit(items=flagged, decisions=decisions)


def needs_power(item: PlanItem) -> bool:
    """The planner said so (`requires_power`), or the instruction says so unmistakably (giving
    the power back, running a cycle, pressing Start). Code-inserted safety items never do."""
    if item.safety_rule:
        return False
    return item.requires_power or _mentions_power(item.instruction)


def skip_powered(items: Iterable[PlanItem], hazards: Iterable[str]) -> PlanEdit:
    """G-SAFE-08: after a hazard that told the user to cut the power, no step needs it again.
    Open items (pending or shown) that do are skipped, not removed: they carry the rule id, so
    they don't count as failed steps (G-LOOP-01), and a handoff can say why it happened."""
    items = list(items)
    active = sorted(set(hazards) & POWER_OFF_HAZARDS)
    if not active:
        return PlanEdit(items=items)
    result: list[PlanItem] = []
    decisions: list[Decision] = []
    for item in items:
        if item.status in ("pending", "presented") and needs_power(item):
            item = item.model_copy(update={"status": "skipped", "safety_rule": POWER_OFF_RULE})
            decisions.append(
                _plan_decision(
                    f"skipped {item.id}: needs power after {', '.join(active)}", POWER_OFF_RULE
                )
            )
        result.append(item)
    return PlanEdit(items=result, decisions=decisions)


def skipped_for_power(item: PlanItem) -> bool:
    return item.safety_rule == POWER_OFF_RULE


def is_power_off(item: PlanItem) -> bool:
    return item.safety_rule == "G-SAFE-06"


def insert_power_off(items: Iterable[PlanItem]) -> PlanEdit:
    """G-SAFE-06: every run of disassembly items is preceded by a power-off item."""
    result: list[PlanItem] = []
    decisions: list[Decision] = []
    count = 0
    for item in items:
        previous = result[-1] if result else None
        covered = previous is not None and (is_power_off(previous) or previous.requires_disassembly)
        if item.requires_disassembly and not covered:
            count += 1
            result.append(
                PlanItem(
                    id=f"{POWER_OFF_ID_PREFIX}-{count}",
                    instruction=POWER_OFF_INSTRUCTION,
                    safety_rule="G-SAFE-06",
                )
            )
            decisions.append(_plan_decision(f"inserted power-off before {item.id}", "G-SAFE-06"))
        result.append(item)
    return PlanEdit(items=result, decisions=decisions)


def postprocess_plan(
    items: Iterable[PlanItem],
    *,
    category: str | None,
    in_warranty: bool = False,
    hazards: Iterable[str] = (),
    max_items: int = MAX_PLAN_ITEMS,
) -> PlanEdit:
    """Apply all §7.6 rules in order: P3, G-INJ-01, high risk, web-only steps (§10.6),
    G-SAFE-03, G-SAFE-08 (skips, kept last and outside the cap), cap, G-WARR-01, G-SAFE-06."""
    decisions: list[Decision] = []

    def apply(edit: PlanEdit) -> list[PlanItem]:
        decisions.extend(edit.decisions)
        return edit.items

    current = apply(drop_uncited(items))
    current = apply(drop_non_english(current))
    current = apply(drop_high_risk(current))
    current = apply(limit_web_only(current))
    current = apply(forbid_high_voltage_disassembly(current, category))
    marked = apply(skip_powered(current, hazards))
    skipped = [item for item in marked if skipped_for_power(item)]
    current = [item for item in marked if not skipped_for_power(item)]
    if len(current) > max_items:
        dropped = ", ".join(item.id for item in current[max_items:])
        decisions.append(_plan_decision(f"dropped {dropped}: plan capped at {max_items} items"))
        current = current[:max_items]
    current = apply(flag_warranty(current, in_warranty))
    current = apply(insert_power_off(current))
    # Skipped items stay in the plan, last, so a handoff can say they needed the power.
    return PlanEdit(items=[*current, *skipped], decisions=decisions)


def merge_plan(current: list[PlanItem], new: list[PlanItem]) -> PlanEdit:
    """A plan built again (a model number or the appliance's look arrived midway): the steps
    already tried stay first, with their results and ids, so they still count towards
    G-LOOP-01; the new plan replaces the rest, including a step shown but not answered. With
    no new steps the current plan stays as it is. New items are numbered after the highest id
    the plan used, so no card ever shows a reused id."""
    if not new:
        return PlanEdit(
            items=current,
            decisions=[_plan_decision("kept the current plan: the new one has no steps")]
            if current
            else [],
        )
    if not current:
        return PlanEdit(items=new)
    tried = [item for item in current if item.status in TRIED]
    counts = {
        "p": _highest(current, "p"),
        POWER_OFF_ID_PREFIX: _highest(current, POWER_OFF_ID_PREFIX + "-"),
    }
    merged = list(tried)
    for item in new:
        if is_power_off(item):
            counts[POWER_OFF_ID_PREFIX] += 1
            item_id = f"{POWER_OFF_ID_PREFIX}-{counts[POWER_OFF_ID_PREFIX]}"
        else:
            counts["p"] += 1
            item_id = f"p{counts['p']}"
        merged.append(item.model_copy(update={"id": item_id}))
    decisions = []
    if tried:
        decisions.append(
            _plan_decision(f"kept {len(tried)} tried steps; {len(new)} new steps after them")
        )
    return PlanEdit(items=merged, decisions=decisions)


def _highest(items: list[PlanItem], prefix: str) -> int:
    numbers = [
        int(item.id[len(prefix) :])
        for item in items
        if item.id.startswith(prefix) and item.id[len(prefix) :].isdigit()
    ]
    return max(numbers, default=0)
