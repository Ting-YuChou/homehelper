from homehelper.agent.state import NLUResult, SlotUpdate
from homehelper_evals.nlu import grade, load_cases, summarize


def test_dataset_loads_and_covers_every_graded_intent() -> None:
    cases = load_cases()
    assert len(cases) >= 60
    assert len({case.id for case in cases}) == len(cases)
    intents = {intent for case in cases for intent in case.expect.intents}
    assert {"report_problem", "ask_how_to", "step_feedback", "out_of_scope"} <= intents
    assert sum(bool(case.expect.hazards) for case in cases) >= 8


def test_grading_normalizes_slots_and_splits_hazard_errors() -> None:
    (case,) = [c for c in load_cases() if c.id == "nlu-062"]
    nlu = NLUResult(
        intent="step_feedback",
        step_feedback="not_fixed",
        hazard_signals=["smoke_or_burning", "sparks"],
    )
    result = grade(case, nlu)
    assert result["intent"] and result["step_feedback"]
    assert result["hazards"] == {"missed": [], "extra": ["sparks"], "exact": False}

    (lg,) = [c for c in load_cases() if c.id == "nlu-003"]
    slots = [
        SlotUpdate(name="appliance_category", value="Washing Machine"),
        SlotUpdate(name="brand", value="lg"),
        SlotUpdate(name="error_code", value="oe"),
    ]
    graded = grade(lg, NLUResult(intent="report_problem", slot_updates=slots))
    assert all(graded["slots"].values())

    rows = [
        {
            "grade": result,
            "expect_intent": "step_feedback",
            "intent": "step_feedback",
            "expect_hazards": case.expect.hazards,
        },
    ]
    summary = summarize(rows)
    assert (summary["hazard_recall"], summary["hazard_precision"]) == (1.0, 0.5)
