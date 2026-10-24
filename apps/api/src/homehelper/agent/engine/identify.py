"""Which manual the user's appliance is, when they may not know its model number (ADR-013).

Pure functions of the state and the read-only `ManualIndex`: the model number pins its manual;
without one, the brand's manuals in the category are narrowed by what the user sees (traits and
badges from `features.yaml`). One left is as good as a model number; several make the plan
general. `model_hint` is the fixed sentence that asks for the model number, once.
"""

from homehelper.agent.engine.predicates import slot_traits, usable_model
from homehelper.agent.state import AgentState, PlanBasis
from homehelper.knowledge.features import BADGE_SLOT, ManualIndex
from homehelper.knowledge.schemas import CategoryId


def _value(state: AgentState, name: str) -> str | None:
    slot = state.slots.get(name)
    return slot.value if slot else None


def category_of(state: AgentState) -> CategoryId | None:
    value = _value(state, "appliance_category")
    return CategoryId(value) if value in {c.value for c in CategoryId} else None


def identify(state: AgentState, index: ManualIndex) -> PlanBasis | None:
    """The manuals this issue's appliance can be, and why; None without a category."""
    category = category_of(state)
    if category is None:
        return None
    model = usable_model(state.slots.get("model_number"))
    traits = slot_traits(state)
    badge = _value(state, BADGE_SLOT)
    if model is not None:
        manuals = index.model_manuals(model, category)
        if manuals:
            return PlanBasis(scope="model", doc_ids=manuals, model_number=model)
    candidates = index.candidates(category, _value(state, "brand"))
    narrowed = index.narrow(candidates, traits, badge)
    return PlanBasis(
        scope="identified" if len(narrowed) == 1 else "generic",
        doc_ids=narrowed,
        model_number=model,
        traits=traits,
        badge=badge,
    )


def same_manuals(a: PlanBasis | None, b: PlanBasis | None) -> bool:
    return (
        a is not None
        and b is not None
        and (a.scope, sorted(a.doc_ids))
        == (
            b.scope,
            sorted(b.doc_ids),
        )
    )


def appearance(state: AgentState, index: ManualIndex) -> list[str]:
    """What the user says the appliance looks like, in their words, for the web search."""
    category = category_of(state)
    words = []
    for name, value in slot_traits(state).items():
        trait = index.trait(category, name) if category else None
        if trait is not None and value in trait.values:
            words.append(trait.values[value])
    badge = _value(state, BADGE_SLOT)
    return [*words, badge] if badge else words


def model_hint(state: AgentState, index: ManualIndex, basis: PlanBasis | None) -> str | None:
    """The one request for the model number (ADR-013): where its sticker usually is, and, when
    a visible trait tells the brand's manuals apart, that question first. None once the manual
    is known, or once asked about this appliance."""
    category = category_of(state)
    if category is None or basis is None or basis.scope != "generic":
        return None
    if category.value in state.model_asked:
        return None
    noun = category.value.replace("_", " ")
    brand = _value(state, "brand")
    location = index.model_location(category)
    what = "the model number" if brand else "the brand and model number"
    split = index.splitting_trait(basis.doc_ids, category, slot_traits(state))
    if split is not None:
        _, trait = split
        return (
            f"{trait.question} Or, if it's handy, tell me {what}: it's usually {location}. "
            f"You can also send a photo of that sticker or of the front of the {noun}."
        )
    appliance = f"{brand} {noun}" if brand else noun
    return (
        f"These steps are general ones for {appliance}s. If it's handy, tell me {what} (it's "
        f"usually {location}) or send a photo of that sticker, and I'll use the manual for "
        "your exact model."
    )
