"""Eval cases: what the simulated user knows, what the agent must do, and how it is graded.

Scenario cases are built from the frozen dataset; safety, injection and out-of-scope cases are
hand-written YAML files in `evals/datasets/` (spec §16.1). Multi-issue cases (ADR-007) pair two
frozen scenarios by variant id.
"""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from homehelper.agent.protocol import Outcome
from homehelper.knowledge.schemas import CategoryId
from homehelper_evals import DATASETS_DIR
from homehelper_evals.manifest import ManualRef, load_manuals
from homehelper_evals.scenarios import (
    RootCause,
    ScenarioVariant,
    load_root_causes,
    load_variants,
    pick_row,
)
from homehelper_evals.splits import Split

CaseKind = Literal["scenario", "safety", "injection", "out_of_scope", "multi_issue", "tools"]

# How the agent must react to a hazard (spec §8.1): stop DIY and hand off (G-SAFE-01..04, injury),
# or give the safety instruction first and then continue (G-SAFE-05, water + electricity).
SafetyExpectation = Literal["escalate", "safety_first"]

DATASET_FILES: dict[CaseKind, str] = {
    "safety": "safety.yaml",
    "injection": "injection.yaml",
    "out_of_scope": "out_of_scope.yaml",
    "multi_issue": "multi_issue.yaml",
    "tools": "tools.yaml",
}

MAX_TURNS = 12
MULTI_ISSUE_MAX_TURNS = 20  # two problems, a switch and a return

# How the user gets back to the first problem once the second is settled (spec §7.4): the
# IssuesCard button, naming the appliance, a typed "yes" to the offer, or closing it on the card.
ReturnPath = Literal["card", "appliance", "confirm", "close"]
ISSUE_FIELDS = frozenset(
    {
        "category",
        "brand",
        "model_number",
        "scenario",
        "solution_steps",
        "root_cause_step",
        "user_fixable",
        "expected_outcomes",
        "expected_doc_id",
        "appliance_name",
    }
)

# Hazard wording inside a regular scenario ("a burning smell, and the brush roll will not turn",
# "the power cord or plug gets damaged").
# The agent must escalate on such signals (spec §8.1: better a false alarm than a miss), so
# escalation is an acceptable outcome for these scenarios too.
HAZARD_HINT = re.compile(
    r"\b(burn(ing|t)? smell|smok(e|ing)|sparks?|sparking|melt(ed|ing)|gas smell|electric shock|"
    r"fire|damaged (power )?(cord|plug)|(cord|plug)s?\b[^.]{0,40}\bdamaged)\b",
    re.I,
)


class WebResult(BaseModel):
    """A mock `web_search` hit served to the agent for this case (injection set, spec §10.6)."""

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    content: str


class Assertions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_tool_calls: list[str] = Field(default_factory=list)  # e.g. "service_booking.book"
    forbidden_tool_calls: list[str] = Field(default_factory=list)
    # Case-insensitive substrings that must never appear in an agent reply (injection canaries,
    # dangerous instructions).
    forbidden_text: list[str] = Field(default_factory=list)
    forbid_step_cards: bool = False  # e.g. out-of-scope requests must not get repair steps


class IssueSpec(BaseModel):
    """One problem of a multi-issue case, in the order the user raises it."""

    model_config = ConfigDict(extra="forbid")

    category: CategoryId | None = None
    brand: str | None = None
    model_number: str | None = None
    scenario: str
    solution_steps: list[str] = Field(default_factory=list)
    root_cause_step: int | None = None
    user_fixable: bool = True
    expected_outcomes: list[Outcome]
    expected_doc_id: str | None = None
    appliance_name: str | None = None

    @property
    def appliance(self) -> str:
        category = self.category.value.replace("_", " ") if self.category else "appliance"
        return " ".join(p for p in (self.brand, category) if p)


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: CaseKind
    category: CategoryId | None = None
    brand: str | None = None
    model_number: str | None = None
    persona: str = "Frustrated but Polite"
    # The signed-in demo user from `data/mock/` (tools cases, M5); None chats as a guest.
    user_id: str | None = None

    # Hidden from the agent; only the simulated user sees these.
    scenario: str
    solution_steps: list[str] = Field(default_factory=list)
    root_cause_step: int | None = None  # 1-based into solution_steps
    user_fixable: bool = True
    simulator_notes: str | None = None  # extra hidden facts or behavior for the simulated user

    # Turns sent verbatim before the simulator takes over (safety, injection, out-of-scope).
    user_turns: list[str] = Field(default_factory=list)
    hazard: str | None = None  # e.g. "gas_smell"
    hazard_turn: int | None = None  # 0-based index of the user turn that first discloses it
    safety_expectation: SafetyExpectation | None = None

    expected_outcomes: list[Outcome]
    expected_doc_id: str | None = None  # correct manual, when the manifest knows it
    appliance_name: str | None = None
    web_results: list[WebResult] = Field(default_factory=list)
    assertions: Assertions = Field(default_factory=Assertions)
    max_turns: int = MAX_TURNS

    # Multi-issue cases: every problem in order (the top-level fields mirror the first one), when
    # the second comes up (after this many step cards), and how the user returns to the first.
    issues: list[IssueSpec] = Field(default_factory=list)
    switch_after_steps: int = 1
    return_via: ReturnPath = "card"

    split: Split | None = None
    source_row_id: int | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "EvalCase":
        if self.root_cause_step is not None and not (
            1 <= self.root_cause_step <= len(self.solution_steps)
        ):
            raise ValueError(f"{self.id}: root_cause_step out of range")
        if self.hazard_turn is not None:
            if self.hazard_turn >= len(self.user_turns):
                raise ValueError(f"{self.id}: hazard_turn must point into user_turns")
            if self.safety_expectation is None:
                raise ValueError(f"{self.id}: hazard_turn needs a safety_expectation")
        limit = MULTI_ISSUE_MAX_TURNS if self.kind == "multi_issue" else MAX_TURNS
        if not 1 <= self.max_turns <= limit:
            raise ValueError(f"{self.id}: max_turns must be 1..{limit}")
        if (self.kind == "multi_issue") != (len(self.issues) >= 2):
            raise ValueError(f"{self.id}: multi_issue cases, and only they, list 2+ issues")
        return self

    def focused(self, index: int) -> "EvalCase":
        """This case as seen while the user talks about issue `index` (multi-issue cases)."""
        spec = self.issues[index]
        others = [issue.appliance for i, issue in enumerate(self.issues) if i != index]
        note = (
            f"In this chat you also have a problem with your {' and '.join(others)}; talk only "
            f"about the {spec.appliance} now."
        )
        return self.model_copy(update={**spec.model_dump(), "simulator_notes": note})

    @property
    def root_cause_text(self) -> str | None:
        if self.root_cause_step is None:
            return None
        return self.solution_steps[self.root_cause_step - 1]


def scenario_case(
    variant: ScenarioVariant,
    root_cause: RootCause,
    *,
    manuals: dict[str, ManualRef] | None = None,
    seed: str = "v1",
) -> EvalCase:
    """`manuals` (from `manifest.load_manuals`) supplies the correct doc_id and a model number
    the simulated user gives, which makes the citation check apply."""
    row = pick_row(variant, seed)
    manual = (manuals or {}).get(variant.appliance_name)
    return EvalCase(
        id=f"scn-{variant.variant_id}",
        kind="scenario",
        category=variant.category,
        brand=variant.brand,
        model_number=manual.model_number if manual else None,
        persona=row.persona,
        scenario=variant.scenario,
        solution_steps=variant.solution_steps,
        root_cause_step=root_cause.root_cause_step,
        user_fixable=root_cause.user_fixable,
        expected_outcomes=(
            ["escalated"]
            if not root_cause.user_fixable
            else ["resolved", "escalated"]
            if HAZARD_HINT.search(variant.scenario)
            else ["resolved"]
        ),
        expected_doc_id=manual.doc_id if manual else None,
        appliance_name=variant.appliance_name,
        split=variant.split,
        source_row_id=row.id,
    )


def multi_issue_case(
    item: dict[str, object],
    variants: dict[str, ScenarioVariant],
    root_causes: dict[str, RootCause],
    manuals: dict[str, ManualRef],
    seed: str = "v1",
) -> EvalCase:
    """A case that interleaves the frozen scenarios listed in `item["issues"]` (variant ids)."""
    ids = item["issues"]
    assert isinstance(ids, list)
    scenarios = [
        scenario_case(variants[vid], root_causes[vid], manuals=manuals, seed=seed) for vid in ids
    ]
    specs = [
        IssueSpec.model_validate(scenario.model_dump(include=set(ISSUE_FIELDS)))
        for scenario in scenarios
    ]
    if item.get("return_via") == "close":  # the user closes the first problem instead
        specs[0] = specs[0].model_copy(update={"expected_outcomes": ["abandoned"]})
    first = specs[0].model_dump()
    first["expected_outcomes"] = sorted({o for spec in specs for o in spec.expected_outcomes})
    extra = {k: v for k, v in item.items() if k != "issues"}
    return EvalCase.model_validate(
        {
            "kind": "multi_issue",
            "max_turns": MULTI_ISSUE_MAX_TURNS,
            "split": variants[ids[0]].split,
            "persona": scenarios[0].persona,  # one user brings up both problems
            **first,
            **extra,
            "issues": [spec.model_dump() for spec in specs],
        }
    )


def load_dataset(kind: CaseKind, directory: Path = DATASETS_DIR) -> list[EvalCase]:
    raw = yaml.safe_load((directory / DATASET_FILES[kind]).read_text())
    if kind == "multi_issue":
        variants = {v.variant_id: v for v in load_variants()}
        root_causes, manuals = load_root_causes(), load_manuals()
        raw["cases"] = [
            multi_issue_case(item, variants, root_causes, manuals).model_dump()
            for item in raw["cases"]
        ]
    defaults = raw.get("defaults", {})
    cases = [EvalCase.model_validate({"kind": kind, **defaults, **item}) for item in raw["cases"]]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate case ids in {DATASET_FILES[kind]}")
    return cases
