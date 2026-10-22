"""The frozen M2-01 labels, the hand-written datasets, and scenario sampling."""

import json
from collections import Counter

import pytest

from homehelper.llm import FakeLLMClient, LLMError
from homehelper.mcp_servers.mock_data import load_mock_data
from homehelper.mcp_servers.registry import TOOL_SPECS
from homehelper_evals import REPO_ROOT, ROOT_CAUSES_PATH
from homehelper_evals.cases import load_dataset, scenario_case
from homehelper_evals.root_cause import LABEL_TASK, label_variant
from homehelper_evals.scenarios import (
    is_solvable,
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
    ("kind", "minimum"),
    [("safety", 40), ("injection", 20), ("out_of_scope", 20), ("multi_issue", 10)],
)
def test_datasets_have_spec_size(kind, minimum) -> None:
    cases = load_dataset(kind)
    assert len(cases) >= minimum
    # Multi-issue cases are driven by the runner's switch and return turns instead.
    assert all(case.kind == kind and (case.user_turns or case.issues) for case in cases)


def test_regression_cases_are_valid_replays_of_known_demo_users() -> None:
    # Every file under evals/datasets/regression/ loads (id = file name), replays a script, and
    # signs in as a known demo user or a guest.
    users = {u.user_id for u in load_mock_data(REPO_ROOT / "data" / "mock").users}
    for case in load_dataset("regression"):
        assert case.kind == "regression" and case.stop_after_script and case.source
        assert case.user_id is None or case.user_id in users


def test_tool_cases_use_known_demo_users_and_tools() -> None:
    cases = load_dataset("tools")
    assert len(cases) >= 8 and all(c.kind == "tools" and c.user_turns for c in cases)
    users = {u.user_id for u in load_mock_data(REPO_ROOT / "data" / "mock").users}
    assert {c.user_id for c in cases} - {None} <= users
    assert any(c.user_id is None for c in cases)  # a guest case
    for case in cases:
        named = case.assertions.required_tool_calls + case.assertions.forbidden_tool_calls
        assert named and set(named) <= set(TOOL_SPECS)


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


def test_damaged_cord_scenarios_accept_escalation() -> None:
    labels = load_root_causes()
    variant = next(v for v in load_variants() if v.variant_id == "22bf8419c33d")
    assert scenario_case(variant, labels["22bf8419c33d"]).expected_outcomes == [
        "resolved",
        "escalated",
    ]


def test_injection_hazard_case_expects_escalation_only() -> None:
    case = next(c for c in load_dataset("injection") if c.id == "injection-user-03")
    assert case.safety_expectation == "escalate" and case.expected_outcomes == ["escalated"]


@pytest.mark.parametrize(
    "phrase", ["the cavity is overheated", "can cause arcing", "potentially cause injury"]
)
def test_guardrail_hazard_words_accept_escalation(phrase) -> None:
    # The agent's guardrail escalates on both words (agent/guardrails/hazards.py).
    labels = load_root_causes()
    variant = next(
        v
        for v in load_variants()
        if phrase in v.scenario.lower() and labels[v.variant_id].user_fixable
    )
    assert scenario_case(variant, labels[variant.variant_id]).expected_outcomes == [
        "resolved",
        "escalated",
    ]


def test_non_answer_root_causes_are_not_solvable() -> None:
    labels = load_root_causes()
    unsolvable = {v.rows[0].id for v in load_variants() if not is_solvable(v, labels[v.variant_id])}
    assert {346, 343, 2086} <= unsolvable  # "I don't know.", "I'm sorry, the manual does not..."
    assert 592 in unsolvable  # "I apologize, but the attached manual does not contain..."
    assert 646 not in unsolvable  # "I don't know.", but not user-fixable: handing off passes
    assert len(unsolvable) == 21
