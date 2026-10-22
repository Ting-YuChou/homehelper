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


def _contradicts(state: AgentState, appliance: ProfileAppliance) -> bool:
    """The issue's category, or a brand or model number the user gave, is not this appliance."""
    if _value(state, "appliance_category") != appliance.category:
        return True
    for name in PREFILL_SLOTS:
        slot = state.slots.get(name)
        if (
            slot
            and slot.source != "profile"
            and _norm(slot.value) != _norm(getattr(appliance, name))
        ):
            return True
    return False


def _unlink(state: AgentState, journey: Journey) -> Decision | None:
    """Drop a link the user's details contradict, with the slots it prefilled."""
    if state.appliance_id is None or state.profile is None:
        return None
    linked = next(
        (a for a in state.profile.appliances if a.appliance_id == state.appliance_id), None
    )
    if linked is not None and not _contradicts(state, linked):
        return None
    old, state.appliance_id = state.appliance_id, None
    for name in PREFILL_SLOTS:
        slot = state.slots.get(name)
        if slot is not None and slot.source == "profile":
            del state.slots[name]
    return Decision(
        kind="slot", journey=journey.id, reason=f"unlinked {old}: the user's details differ"
    )


def link_profile_appliance(state: AgentState, journey: Journey) -> list[Decision]:
    """Keep the active issue linked to the right profile appliance, prefilling its slots; mutates
    `state`. A link the user later contradicts ("it's the Samsung") is dropped, then relinked
    if another appliance matches."""
    if state.active_issue_id is None:
        return []
    decisions = [d for d in [_unlink(state, journey)] if d is not None]
    if state.appliance_id is not None:
        return decisions
    matches = matching_appliances(state)
    if len(matches) != 1:
        return decisions
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
    decisions.append(
        Decision(
            kind="slot",
            journey=journey.id,
            reason=f"linked {appliance.appliance_id} from the profile{prefilled}",
        )
    )
    return decisions
