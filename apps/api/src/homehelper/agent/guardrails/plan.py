"""Pure post-processing of a planner-generated Solution Plan (spec §7.6, P1, P3).

`plan.build` (M3-07) calls `postprocess_plan` on the planner output; each helper is usable alone.
Every removal or insertion is returned as a `Decision` for the decision log (P7).
"""

from collections.abc import Iterable

from pydantic import BaseModel, Field

from homehelper.agent.guardrails.hazards import HIGH_VOLTAGE_CATEGORIES
from homehelper.agent.state import Decision, PlanItem

MAX_PLAN_ITEMS = 6

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


def drop_high_risk(items: Iterable[PlanItem]) -> PlanEdit:
    kept: list[PlanItem] = []
    decisions: list[Decision] = []
    for item in items:
        if item.risk_level == "high":
            decisions.append(_plan_decision(f"dropped {item.id}: risk_level=high"))
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
    """Apply all §7.6 rules in order: P3, high risk, G-SAFE-03, cap, G-WARR-01, G-SAFE-06."""
    decisions: list[Decision] = []

    def apply(edit: PlanEdit) -> list[PlanItem]:
        decisions.extend(edit.decisions)
        return edit.items

    current = apply(drop_uncited(items))
    current = apply(drop_high_risk(current))
    current = apply(forbid_high_voltage_disassembly(current, category))
    if len(current) > max_items:
        dropped = ", ".join(item.id for item in current[max_items:])
        decisions.append(_plan_decision(f"dropped {dropped}: plan capped at {max_items} items"))
        current = current[:max_items]
    current = apply(flag_warranty(current, in_warranty))
    current = apply(insert_power_off(current))
    return PlanEdit(items=current, decisions=decisions)
