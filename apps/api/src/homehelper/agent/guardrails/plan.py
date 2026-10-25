"""Pure post-processing of a planner-generated Solution Plan (spec §7.6, P1, P3).

`plan.build` (M3-07) calls `postprocess_plan` on the planner output; each helper is usable alone.
Every removal or insertion is returned as a `Decision` for the decision log (P7). A plan built
again for a better-identified appliance is joined to the steps already tried by `merge_plan`
(ADR-013).
"""

from collections.abc import Iterable

from pydantic import BaseModel, Field

from homehelper.agent.guardrails.hazards import HIGH_VOLTAGE_CATEGORIES
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
    max_items: int = MAX_PLAN_ITEMS,
) -> PlanEdit:
    """Apply all §7.6 rules in order: P3, G-INJ-01, high risk, web-only steps (§10.6),
    G-SAFE-03, cap, G-WARR-01, G-SAFE-06."""
    decisions: list[Decision] = []

    def apply(edit: PlanEdit) -> list[PlanItem]:
        decisions.extend(edit.decisions)
        return edit.items

    current = apply(drop_uncited(items))
    current = apply(drop_non_english(current))
    current = apply(drop_high_risk(current))
    current = apply(limit_web_only(current))
    current = apply(forbid_high_voltage_disassembly(current, category))
    if len(current) > max_items:
        dropped = ", ".join(item.id for item in current[max_items:])
        decisions.append(_plan_decision(f"dropped {dropped}: plan capped at {max_items} items"))
        current = current[:max_items]
    current = apply(flag_warranty(current, in_warranty))
    current = apply(insert_power_off(current))
    return PlanEdit(items=current, decisions=decisions)


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
