"""Telling manuals apart without a model number (ADR-013): pure helpers, predicates, plan merge."""

from homehelper.agent.engine import default_catalog
from homehelper.agent.engine.identify import appearance, identify, model_hint, same_manuals
from homehelper.agent.engine.predicates import (
    PREDICATES,
    PredicateContext,
    identification_changed_since_plan,
)
from homehelper.agent.engine.signals import TurnSignals
from homehelper.agent.guardrails.plan import is_web_only, limit_web_only, merge_plan
from homehelper.agent.state import Decision, PlanBasis, PlanItem, SlotValue

from .helpers import new_state, plan, say
from .no_model_helpers import manual_index

INDEX = manual_index()
CATALOG = default_catalog()


def slot(value: str, **fields: object) -> SlotValue:
    return SlotValue.model_validate(
        {"value": value, "source": "user", "confidence": 1.0, "confirmed": True, **fields}
    )


STATE_FIELDS = {"plan_basis", "plan", "step_id", "decision_log"}


def fridge(**values: object):
    """A Samsung fridge issue at the guide step; slot values and state fields by keyword."""
    fields = {k: v for k, v in values.items() if k in STATE_FIELDS}
    slots = {k: v for k, v in values.items() if k not in STATE_FIELDS}
    return new_state(
        **{"active_journey": "troubleshoot", "step_id": "guide", **fields},
        slots={"appliance_category": slot("refrigerator"), "brand": slot("Samsung"), **slots},
    )


def test_identify_by_model_by_look_or_not_at_all() -> None:
    by_model = identify(fridge(model_number=slot("RS27T5200SR")), INDEX)
    assert by_model is not None and (by_model.scope, by_model.doc_ids) == ("model", ["samsung-sbs"])
    by_look = identify(fridge(trait_layout=slot("side_by_side")), INDEX)
    assert by_look is not None and (by_look.scope, by_look.doc_ids) == (
        "identified",
        ["samsung-sbs"],
    )
    assert by_look.traits == {"layout": "side_by_side"}
    unknown = identify(fridge(), INDEX)
    assert unknown is not None and (unknown.scope, len(unknown.doc_ids)) == ("generic", 3)
    # A model number no manual matches: still general, and remembered.
    other = identify(fridge(model_number=slot("XYZ123")), INDEX)
    assert other is not None and (other.scope, other.model_number) == ("generic", "XYZ123")
    # A low-confidence model from a photo is not used.
    blurry = slot("RS27T5200SR", source="vision", confidence=0.4, confirmed=False)
    assert identify(fridge(model_number=blurry), INDEX).scope == "generic"  # type: ignore[union-attr]
    # The brand's only manual is as good as a model number.
    dishwasher = new_state(slots={"appliance_category": slot("dishwasher"), "brand": slot("Bosch")})
    assert identify(dishwasher, INDEX).scope == "identified"  # type: ignore[union-attr]
    assert identify(new_state(), INDEX) is None


def test_same_manuals_compares_scope_and_doc_ids() -> None:
    a = PlanBasis(scope="generic", doc_ids=["b", "a"])
    assert same_manuals(a, PlanBasis(scope="generic", doc_ids=["a", "b"], traits={"x": "y"}))
    assert not same_manuals(a, PlanBasis(scope="identified", doc_ids=["a"]))
    assert not same_manuals(a, None)


def test_appearance_uses_the_users_words() -> None:
    state = fridge(trait_layout=slot("side_by_side"), badge=slot("Family Hub"))
    assert appearance(state, INDEX) == ["side by side", "Family Hub"]


def test_model_hint_asks_the_splitting_question_once() -> None:
    state = fridge()
    basis = identify(state, INDEX)
    hint = model_hint(state, INDEX, basis)
    assert hint is not None
    assert hint.startswith("Is it French door or side by side? Or, if it's handy")
    assert "inside the fresh-food compartment" in hint and "photo" in hint
    state.model_asked.append("refrigerator")
    assert model_hint(state, INDEX, basis) is None
    # Known manual: nothing to ask.
    assert model_hint(fridge(), INDEX, PlanBasis(scope="identified", doc_ids=["x"])) is None


def test_model_hint_without_a_splitting_trait_says_the_steps_are_general() -> None:
    state = fridge(trait_layout=slot("french_door"))
    basis = identify(state, INDEX)  # two French door manuals left; nothing else tells them apart
    hint = model_hint(state, INDEX, basis)
    assert hint is not None and hint.startswith("These steps are general ones for Samsung")
    no_brand = new_state(slots={"appliance_category": slot("refrigerator")})
    text = model_hint(no_brand, INDEX, identify(no_brand, INDEX))
    assert text is not None and "the brand and model number" in text


def test_identification_changed_compares_with_the_plan_basis() -> None:
    basis = PlanBasis(scope="generic", doc_ids=["samsung-fd1", "samsung-sbs"], brand="samsung")
    assert not identification_changed_since_plan(fridge())  # no basis yet
    assert not identification_changed_since_plan(fridge(plan_basis=basis))
    assert identification_changed_since_plan(
        fridge(plan_basis=basis, trait_layout=slot("side_by_side"))
    )
    assert identification_changed_since_plan(fridge(plan_basis=basis, model_number=slot("RF23X")))
    # A brand given or corrected counts too.
    assert identification_changed_since_plan(fridge(plan_basis=basis, brand=slot("LG")))
    pinned = PlanBasis(scope="model", doc_ids=["samsung-fd1"], model_number="RF23X")
    same = fridge(plan_basis=pinned, model_number=slot("rf-23x"), trait_layout=slot("x"))
    assert not identification_changed_since_plan(same)  # the model's manual; looks don't matter


ANY_INPUT = TurnSignals(intent="other")


def _holds(name: str, state, signals: TurnSignals | None = ANY_INPUT) -> bool:
    return PREDICATES.evaluate(name, PredicateContext(CATALOG["troubleshoot"], state, signals))


def test_identification_predicates_need_input_and_the_handoff_needs_no_plan() -> None:
    basis = PlanBasis(scope="generic", doc_ids=["samsung-fd1", "samsung-sbs"])
    state = fridge(plan_basis=basis, model_number=slot("RS27T"))
    assert _holds("identification_changed", state)
    assert not _holds("identification_changed", state, None)  # state-only: never chains
    no_plan = state.model_copy(
        update={
            "step_id": "escalate",
            "decision_log": [
                Decision(
                    kind="transition", to_step="escalate", predicate="plan_unavailable", reason=""
                )
            ],
        }
    )
    assert _holds("identification_changed_after_no_plan", no_plan)
    failed = no_plan.model_copy(
        update={
            "decision_log": [
                Decision(
                    kind="guardrail",
                    to_step="escalate",
                    predicate="max_failed_steps_reached",
                    reason="",
                )
            ]
        }
    )
    assert not _holds("identification_changed_after_no_plan", failed)


def test_a_shown_step_keeps_the_plan_available() -> None:
    state = fridge(plan=plan(2, status="done_not_fixed")[:1] + plan(1, status="presented"))
    assert _holds("plan_available", state, None)
    done = fridge(plan=plan(2, status="done_not_fixed"))
    assert _holds("plan_unavailable", done, None)


def test_merge_keeps_tried_steps_first_and_renumbers() -> None:
    current = [
        PlanItem(id="p1", instruction="A", citation_ids=["c1"], status="done_not_fixed"),
        PlanItem(id="power-off-1", instruction="Unplug", safety_rule="G-SAFE-06", status="skipped"),
        PlanItem(id="p2", instruction="B", citation_ids=["c2"], status="presented"),
        PlanItem(id="p3", instruction="C", citation_ids=["c3"]),
    ]
    new = [
        PlanItem(id="power-off-1", instruction="Unplug", safety_rule="G-SAFE-06"),
        PlanItem(id="p1", instruction="D", citation_ids=["c9"]),
    ]
    edit = merge_plan(current, new)
    # New ids continue after the highest used: a card never shows a replaced step's id.
    assert [(i.id, i.instruction, i.status) for i in edit.items] == [
        ("p1", "A", "done_not_fixed"),
        ("power-off-1", "Unplug", "skipped"),
        ("power-off-2", "Unplug", "pending"),
        ("p4", "D", "pending"),
    ]
    assert "kept 2 tried steps" in edit.decisions[0].reason
    kept = merge_plan(current, [])
    assert kept.items == current and "kept the current plan" in kept.decisions[0].reason
    assert merge_plan([], new).items == new


def test_web_only_steps_are_medium_risk_and_never_open_the_appliance() -> None:
    items = [
        PlanItem(id="p1", instruction="Reset it.", citation_ids=["web-0123456789"]),
        PlanItem(
            id="p2",
            instruction="Remove the back panel.",
            citation_ids=["web-0123456789"],
            requires_disassembly=True,
        ),
        PlanItem(id="p3", instruction="Clean it.", citation_ids=["c1", "web-0123456789"]),
    ]
    assert [is_web_only(i) for i in items] == [True, True, False]
    edit = limit_web_only(items)
    assert [(i.id, i.risk_level) for i in edit.items] == [("p1", "medium"), ("p3", "low")]
    assert [d.reason for d in edit.decisions] == [
        "p1 from a web page: risk_level=medium",
        "dropped p2: disassembly from a web page",
    ]


def test_dont_know_is_not_a_model_number() -> None:
    from homehelper.agent.engine import transition

    state = new_state()
    turn = say(
        "report_problem",
        "My Samsung fridge is warm, I don't know the model",
        slots={
            "appliance_category": "refrigerator",
            "symptom": "not cooling",
            "model_number": "don't know",
        },
    )
    result = transition(CATALOG, state, turn)
    assert "model_number" not in result.state.slots
    assert any("not a model number" in d.reason for d in result.decisions)


def test_a_model_number_without_digits_is_kept() -> None:
    from homehelper.agent.engine import transition

    turn = say(
        "report_problem",
        "My Mr. Coffee BVMC-HC won't brew",
        slots={
            "appliance_category": "coffee_maker",
            "symptom": "won't brew",
            "model_number": "BVMC-HC",
        },
    )
    result = transition(CATALOG, new_state(), turn)
    assert result.state.slots["model_number"].value == "BVMC-HC"


def test_a_model_number_without_digits_must_be_a_known_one() -> None:
    from homehelper.agent.nodes.understand import known_model
    from homehelper.agent.state import NLUResult, SlotUpdate

    def model(value: str) -> list[str]:
        nlu = NLUResult(
            intent="report_problem", slot_updates=[SlotUpdate(name="model_number", value=value)]
        )
        return [u.value for u in known_model(nlu, INDEX).slot_updates]

    assert model("shx-m") == ["SHX-M"]  # Bosch's SHX* pattern, typed in lower case
    assert model("rf23r62e3sr") == ["rf23r62e3sr"]  # with a digit: unchanged
    assert model("MISSING") == []
    assert model("SAMSUNG") == []
    assert model("front") == []


def test_nlu_trait_updates_must_fit_the_category() -> None:
    from homehelper.agent.nodes.understand import valid_traits
    from homehelper.agent.state import NLUResult, SlotUpdate

    nlu = NLUResult(
        intent="report_problem",
        slot_updates=[
            SlotUpdate(name="trait_layout", value="side_by_side"),
            SlotUpdate(name="trait_layout", value="purple"),
            SlotUpdate(name="trait_type", value="front_load"),  # not a fridge trait
            SlotUpdate(name="symptom", value="warm"),
        ],
    )
    kept = valid_traits(nlu, "refrigerator", INDEX).slot_updates
    assert [(u.name, u.value) for u in kept] == [
        ("trait_layout", "side_by_side"),
        ("symptom", "warm"),
    ]
    # The category named in the same message counts; without any, traits are dropped.
    named = nlu.model_copy(
        update={
            "slot_updates": [
                SlotUpdate(name="appliance_category", value="refrigerator"),
                *nlu.slot_updates[:1],
            ]
        }
    )
    assert len(valid_traits(named, None, INDEX).slot_updates) == 2
    assert [u.name for u in valid_traits(nlu, None, INDEX).slot_updates] == ["symptom"]


def test_vision_keeps_only_the_categorys_traits() -> None:
    from homehelper.agent.nodes.perceive import known_traits, vision_traits
    from homehelper.media.schemas import VisionResult

    vision = VisionResult.model_validate(
        {
            "category": "refrigerator",
            "confidence": 0.5,
            "features": [
                {"name": "layout", "value": "french_door"},
                {"name": "layout", "value": "round"},
                {"name": "type", "value": "front_load"},
            ],
        }
    )
    assert [(t.name, t.value) for t in known_traits(vision, INDEX).features] == [
        ("layout", "french_door")
    ]
    assert known_traits(vision, None).features == []
    assert vision_traits(INDEX) == {
        "refrigerator": [{"name": "layout", "values": ["french_door", "side_by_side"]}]
    }


def test_retrieval_query_follows_the_identification() -> None:
    from homehelper.agent.nodes.act import retrieval_query

    state = fridge(model_number=slot("XQ9000"), trait_layout=slot("french_door"))
    generic = PlanBasis(scope="generic", doc_ids=["samsung-fd1", "samsung-fd2"])
    query = retrieval_query(state, "warm", generic)
    assert (query.model_number, query.doc_ids, query.per_doc, query.web) == (
        None,
        ["samsung-fd1", "samsung-fd2"],
        2,
        "always_add",
    )
    one = retrieval_query(state, "warm", PlanBasis(scope="identified", doc_ids=["samsung-fd1"]))
    assert (one.doc_ids, one.per_doc, one.web) == (["samsung-fd1"], None, "add_when_insufficient")
    model = retrieval_query(state, "warm", PlanBasis(scope="model", doc_ids=["samsung-fd1"]))
    assert (model.model_number, model.doc_ids) == ("XQ9000", None)
    assert retrieval_query(state, "warm").web == "replace"  # no index: as before


def test_words_typed_with_a_step_button_add_appliance_details_only() -> None:
    from homehelper.agent.engine.signals import TurnInput, signals_from_input
    from homehelper.agent.state import NLUResult, SlotUpdate
    from homehelper.channels.events import StructuredAction

    nlu = NLUResult(
        intent="report_problem",
        step_feedback="fixed",
        slot_updates=[
            SlotUpdate(name="model_number", value="RS27T"),
            SlotUpdate(name="trait_layout", value="side_by_side"),
            SlotUpdate(name="appliance_category", value="dryer"),
        ],
    )
    action = StructuredAction(type="step_result", value="not_fixed")
    signals = signals_from_input(TurnInput(text="No luck. Model RS27T", nlu=nlu, action=action))
    assert signals.feedback == "not_fixed" and signals.from_card and signals.intent is None
    assert [u.name for u in signals.slot_updates] == ["model_number", "trait_layout"]
    other = StructuredAction(type="confirm_appliance", value="yes")
    assert signals_from_input(TurnInput(nlu=nlu, action=other)).slot_updates == []


def test_a_paused_issue_keeps_its_plan_basis() -> None:
    from homehelper.agent.engine.issues import open_issue, pause_active, restore, take_paused

    basis = PlanBasis(
        scope="identified", doc_ids=["samsung-sbs"], traits={"layout": "side_by_side"}
    )
    state = fridge(plan_basis=basis)
    open_issue(state, "troubleshoot")
    pause_active(state)
    paused = take_paused(state, "iss_1")
    state.plan_basis = None
    restore(state, paused)
    assert state.plan_basis == basis


def test_with_a_model_number_the_hint_asks_only_what_tells_the_manuals_apart() -> None:
    state = fridge(model_number=slot("XQ9000"))  # no manual matches it
    assert model_hint(state, INDEX, identify(state, INDEX)) == "Is it French door or side by side?"
    narrowed = fridge(model_number=slot("XQ9000"), trait_layout=slot("french_door"))
    assert model_hint(narrowed, INDEX, identify(narrowed, INDEX)) is None


def test_unknown_model_is_noticed_once() -> None:
    from homehelper.agent.nodes.act import unknown_model

    generic = PlanBasis(scope="generic", doc_ids=["a", "b"], model_number="XQ9000")
    assert unknown_model(None, generic)
    assert not unknown_model(generic, generic)  # already said
    assert not unknown_model(None, PlanBasis(scope="model", doc_ids=["a"], model_number="RF23"))
