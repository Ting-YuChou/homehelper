"""Linking an issue to an appliance in the user's profile (spec §12.2). Pure, like the engine.

When the issue's category matches exactly one profile appliance, and nothing the user said
contradicts it (brand, model number), the issue is linked to that appliance: its brand and model
number fill the empty slots with `source="profile"`, and code can then check the warranty, read
the repair history and book a visit for it.
"""

import re

from homehelper.agent.engine.schema import Journey
from homehelper.agent.state import AgentState, Decision, ProfileAppliance, SlotValue

PREFILL_SLOTS = ("brand", "model_number")


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _value(state: AgentState, name: str) -> str | None:
    slot = state.slots.get(name)
    return slot.value if slot else None


def matching_appliances(state: AgentState) -> list[ProfileAppliance]:
    category = _value(state, "appliance_category")
    if state.profile is None or category is None:
        return []
    brand, model = _value(state, "brand"), _value(state, "model_number")
    return [
        a
        for a in state.profile.appliances
        if a.category == category
        and (brand is None or _norm(brand) == _norm(a.brand))
        and (model is None or _norm(model) == _norm(a.model_number))
    ]


def link_profile_appliance(state: AgentState, journey: Journey) -> Decision | None:
    """Link the active issue to its profile appliance and prefill slots; mutates `state`."""
    if state.appliance_id is not None or state.active_issue_id is None:
        return None
    matches = matching_appliances(state)
    if len(matches) != 1:
        return None
    appliance = matches[0]
    state.appliance_id = appliance.appliance_id
    filled = []
    for name in PREFILL_SLOTS:
        if name in journey.slots and name not in state.slots:
            state.slots[name] = SlotValue(
                value=getattr(appliance, name), source="profile", confidence=1.0, confirmed=True
            )
            filled.append(name)
    prefilled = f"; prefilled {', '.join(filled)}" if filled else ""
    return Decision(
        kind="slot",
        journey=journey.id,
        reason=f"linked {appliance.appliance_id} from the profile{prefilled}",
    )
