"""Citation accuracy end to end with a fixture manifest (the real one is filled in by M1-01)."""

from pathlib import Path

from homehelper_evals.agents import OracleStubAgent
from homehelper_evals.cases import scenario_case
from homehelper_evals.manifest import example_model_number, load_manuals
from homehelper_evals.metrics import compute_metrics
from homehelper_evals.runner import run_cases
from homehelper_evals.scenarios import load_root_causes, load_variants
from homehelper_evals.simulator import ScriptedUserSimulator
from homehelper_evals.simulator.llm import system_prompt

MANIFEST = """\
- doc_id: samsung-wd5100d-combo
  file: washing_machine/Samsung/WD5100D_WEB_IB_SU-PJT_COMBO-MD.pdf
  category: washing_machine
  brand: Samsung
  model_patterns: ["WD5100D*", "WD53DB*"]
  aliases: ["WD5100D_WEB_IB_SU-PJT_COMBO-MD(1).pdf"]
- doc_id: no-patterns
  file: dryer/LG/unknown.pdf
  category: dryer
  brand: LG
  model_patterns: []
"""


def test_example_model_number_matches_a_pattern() -> None:
    assert example_model_number(["WD5100D*", "WD53DB*"]) == "WD5100D"
    assert example_model_number(["RH1077*VK"]) == "RH10770VK"
    assert example_model_number(["DV?0A[BC]*"]) == "DV00AB"
    assert example_model_number(["LM*"]) is None  # too short to name a model
    assert example_model_number([]) is None


def test_load_manuals_maps_files_and_aliases(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(MANIFEST)
    manuals = load_manuals(path)
    ref = manuals["WD5100D_WEB_IB_SU-PJT_COMBO-MD.pdf"]
    assert (ref.doc_id, ref.model_number) == ("samsung-wd5100d-combo", "WD5100D")
    assert manuals["WD5100D_WEB_IB_SU-PJT_COMBO-MD(1).pdf"] == ref
    assert manuals["unknown.pdf"].model_number is None
    empty = tmp_path / "empty.yaml"
    empty.write_text("[]\n")
    assert load_manuals(empty) == {}


async def test_citation_check_applies_when_the_manual_is_known(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(MANIFEST)
    manuals = load_manuals(path)
    labels = load_root_causes()
    variant = next(
        v
        for v in load_variants()
        if v.appliance_name == "WD5100D_WEB_IB_SU-PJT_COMBO-MD.pdf"
        and labels[v.variant_id].user_fixable
    )
    case = scenario_case(variant, labels[variant.variant_id], manuals=manuals)
    assert (case.model_number, case.expected_doc_id) == ("WD5100D", "samsung-wd5100d-combo")
    assert "WD5100D" in system_prompt(case)

    results = await run_cases(
        [case],
        k=1,
        concurrency=1,
        agent_factory=OracleStubAgent,
        simulator=ScriptedUserSimulator(),
        judge=None,
    )
    transcript = results[0].trials[0].transcript
    assert "WD5100D" in (transcript.user_turns[0].text or "")
    assert results[0].trials[0].grade.check("citations").passed is True
    metrics = compute_metrics(results, k=1)
    assert metrics["citation_trials"] == 1 and metrics["citation_accuracy"] == 1.0


async def test_without_a_manual_the_citation_count_is_zero() -> None:
    labels = load_root_causes()
    variant = load_variants()[0]
    case = scenario_case(variant, labels[variant.variant_id], manuals={})
    assert case.model_number is None and case.expected_doc_id is None
    results = await run_cases(
        [case],
        k=1,
        concurrency=1,
        agent_factory=OracleStubAgent,
        simulator=ScriptedUserSimulator(),
        judge=None,
    )
    metrics = compute_metrics(results, k=1)
    assert metrics["citation_trials"] == 0 and metrics["citation_accuracy"] is None
