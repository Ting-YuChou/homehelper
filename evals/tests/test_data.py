"""The frozen M2-01 labels, the hand-written datasets, and scenario sampling."""

import json
from collections import Counter

import pytest

from homehelper.llm import FakeLLMClient, LLMError
from homehelper_evals import ROOT_CAUSES_PATH
from homehelper_evals.cases import load_dataset, scenario_case
from homehelper_evals.root_cause import LABEL_TASK, label_variant
from homehelper_evals.scenarios import (
    load_root_causes,
    load_variants,
    parse_steps,
    sample_variants,
    variant_id,
)
from homehelper_evals.splits import load_splits


def test_parse_steps_strips_numbering() -> None:
    assert parse_steps("1. Plug it in.\n2) Close the door.\n\n") == [
        "Plug it in.",
        "Close the door.",
    ]
    assert variant_id("The  Dryer stops.", "1. A") == variant_id("the dryer stops.", "1) A")


def test_frozen_labels_cover_every_variant() -> None:
    variants = load_variants()
    labels = load_root_causes()
    assert set(labels) == {v.variant_id for v in variants}
    for variant in variants:
        assert 1 <= labels[variant.variant_id].root_cause_step <= len(variant.solution_steps)
    document = json.loads(ROOT_CAUSES_PATH.read_text())
    assert document["version"] == 1 and document["labeler"]["task"] == LABEL_TASK


def test_variants_follow_the_committed_split() -> None:
    splits = load_splits()
    for variant in load_variants():
        assert {splits[str(row.id)] for row in variant.rows} == {variant.split}


def test_stratified_sample_is_deterministic_and_nested() -> None:
    variants = load_variants()
    small = sample_variants(variants, split="test", per_category=3)
    large = sample_variants(variants, split="test", per_category=5)
    assert Counter(v.category for v in small) == {c: 3 for c in {v.category for v in small}}
    assert len({v.category for v in small}) == 10
    assert all(v.split == "test" for v in large)
    small_ids = {v.variant_id for v in small}
    assert small_ids <= {v.variant_id for v in large}
    assert small_ids == {
        v.variant_id for v in sample_variants(variants, split="test", per_category=3)
    }
    assert small_ids != {
        v.variant_id for v in sample_variants(variants, split="test", per_category=3, seed="v2")
    }


def test_scenario_case_expected_outcomes() -> None:
    labels = load_root_causes()
    variants = {v.variant_id: v for v in load_variants()}
    unfixable = next(vid for vid, label in labels.items() if not label.user_fixable)
    assert scenario_case(variants[unfixable], labels[unfixable]).expected_outcomes == ["escalated"]
    burning = next(
        vid
        for vid, v in variants.items()
        if "burning smell" in v.scenario.lower() and labels[vid].user_fixable
    )
    assert scenario_case(variants[burning], labels[burning]).expected_outcomes == [
        "resolved",
        "escalated",
    ]


@pytest.mark.parametrize(
    ("kind", "minimum"), [("safety", 40), ("injection", 20), ("out_of_scope", 20)]
)
def test_datasets_have_spec_size(kind, minimum) -> None:
    cases = load_dataset(kind)
    assert len(cases) >= minimum
    assert all(case.kind == kind and case.user_turns for case in cases)


def test_safety_cases_cover_every_hazard_type() -> None:
    cases = load_dataset("safety")
    assert all(case.hazard_turn is not None for case in cases)
    assert {case.hazard for case in cases} == {
        "gas_smell",
        "smoke_or_burning",
        "sparks",
        "high_voltage_internal",
        "refrigerant",
        "water_near_electric",
        "injury",
    }
    for case in cases:
        expected = (
            ["resolved", "escalated"] if case.hazard == "water_near_electric" else ["escalated"]
        )
        assert case.expected_outcomes == expected, case.id


def test_injection_cases_have_a_canary() -> None:
    for case in load_dataset("injection"):
        a = case.assertions
        assert a.forbidden_text or a.forbidden_tool_calls or case.hazard, case.id
        for result in case.web_results:
            assert ".example." in result.url  # never a real site


def test_out_of_scope_cases_forbid_repair_steps() -> None:
    for case in load_dataset("out_of_scope"):
        assert case.expected_outcomes == ["out_of_scope"]
        assert case.assertions.forbid_step_cards and case.max_turns == 3


async def test_label_variant_validates_the_step_number() -> None:
    variant = load_variants()[0]
    reply = {"root_cause_step": 2, "user_fixable": True, "troubleshootable": True, "rationale": "x"}
    llm = FakeLLMClient({LABEL_TASK: [reply, {**reply, "root_cause_step": 99}]})
    assert (await label_variant(llm, variant)).root_cause_step == 2
    assert variant.scenario in llm.calls[0].messages[1].content
    with pytest.raises(LLMError):
        await label_variant(llm, variant)
