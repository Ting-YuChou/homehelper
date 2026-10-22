"""Scenario variants from `home_helper_dataset.jsonl` and the stratified sample used for
conversation simulation (spec §16.1, §20 Q9).

A *variant* is one scenario group (normalized scenario text, see `splits.group_key`) with one
distinct `solution_steps` text. 965 groups have a single variant; 6 groups appear in several
manuals with different steps. Each variant has three rows, one per tone (`human_intonations`).
"""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel

from homehelper.knowledge.schemas import CategoryId
from homehelper_evals import ROOT_CAUSES_PATH, SCENARIOS_PATH
from homehelper_evals.splits import Split, assign_split, group_key, load_rows

# `product_name` in the dataset → canonical category (spec §2.2; fixes the v1 "Diswasher" typo).
PRODUCT_CATEGORIES: dict[str, CategoryId] = {
    "Diswasher": CategoryId.DISHWASHER,
    "WashingMachines": CategoryId.WASHING_MACHINE,
    "Dryer": CategoryId.DRYER,
    "Refrigerator": CategoryId.REFRIGERATOR,
    "Microwave": CategoryId.MICROWAVE,
    "CoffeeMaker": CategoryId.COFFEE_MAKER,
    "Blender-FoodProcessor": CategoryId.BLENDER_FOOD_PROCESSOR,
    "Vacuum": CategoryId.VACUUM,
    "Television": CategoryId.TELEVISION,
    "WaterPurifier": CategoryId.WATER_PURIFIER,
}

_STEP_PREFIX = re.compile(r"^\s*\d+[.)]\s*")
# Steps the v1 generator wrote when it found no answer in the manual ("I don't know.",
# "I'm sorry, the manual does not provide ...", "I apologize, but the attached manual ...",
# "(Note: The manual does not provide ...)").
_NON_ANSWER = re.compile(
    r"^\W*(note:\s*)?(i don['\u2019]t know|i['\u2019]m sorry|i am sorry|i apologi[sz]e"
    r"|(the|this) (attached |provided )?manual (provided |content provided )?"
    r"(does not|doesn['\u2019]t) "
    r"(provide|contain|include|address|mention|specify))",
    re.I,
)


class ScenarioRow(BaseModel):
    id: int
    persona: str


class ScenarioVariant(BaseModel):
    variant_id: str
    scenario: str
    solution_steps: list[str]
    category: CategoryId
    brand: str
    appliance_name: str  # the manual's PDF filename; maps to a manifest doc_id (spec §16.2)
    split: Split
    rows: list[ScenarioRow]


class RootCause(BaseModel):
    """Frozen M2-01 label: which solution step actually fixes the problem."""

    root_cause_step: int  # 1-based index into `solution_steps`
    user_fixable: bool  # False when the fixing step is "call service" or similar
    troubleshootable: bool  # False for warnings / notes that are not a problem a user reports
    rationale: str


def parse_steps(solution_steps: str) -> list[str]:
    lines = [line.strip() for line in solution_steps.splitlines() if line.strip()]
    return [_STEP_PREFIX.sub("", line) for line in lines]


def variant_id(scenario: str, solution_steps: str) -> str:
    key = group_key(scenario) + "\n" + "\n".join(parse_steps(solution_steps))
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def load_variants(path: Path = SCENARIOS_PATH) -> list[ScenarioVariant]:
    by_id: dict[str, list[dict]] = defaultdict(list)
    for row in load_rows(path):
        by_id[variant_id(row["scenario"], row["solution_steps"])].append(row)
    variants = []
    for vid, rows in by_id.items():
        first = min(rows, key=lambda r: r["id"])
        variants.append(
            ScenarioVariant(
                variant_id=vid,
                scenario=first["scenario"].strip(),
                solution_steps=parse_steps(first["solution_steps"]),
                category=PRODUCT_CATEGORIES[first["product_name"]],
                brand=first["company_name"],
                appliance_name=first["appliance_name"],
                split=assign_split(first["scenario"]),
                rows=[
                    ScenarioRow(id=r["id"], persona=r["human_intonations"])
                    for r in sorted(rows, key=lambda r: r["id"])
                ],
            )
        )
    return sorted(variants, key=lambda v: v.rows[0].id)


def is_solvable(variant: ScenarioVariant, root_cause: RootCause) -> bool:
    """False when a user-fixable variant's root-cause step is a generator non-answer: the
    simulated user could never report "fixed", so the case would fail whatever the agent does.
    Variants that are not user-fixable stay: the simulator never sees their root-cause text, and
    an agent that hands off passes."""
    if not root_cause.user_fixable:
        return True
    return not _NON_ANSWER.search(variant.solution_steps[root_cause.root_cause_step - 1])


def load_root_causes(path: Path = ROOT_CAUSES_PATH) -> dict[str, RootCause]:
    labels = json.loads(path.read_text())["labels"]
    return {vid: RootCause.model_validate(label) for vid, label in labels.items()}


def _rank(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def sample_variants(
    variants: list[ScenarioVariant],
    *,
    split: Split,
    per_category: int,
    seed: str = "v1",
) -> list[ScenarioVariant]:
    """Stratified, deterministic sample: `per_category` variants from each category of `split`.

    Within a category, picks round-robin across manuals (in seeded order) so that one manual
    with many scenarios does not dominate. The same seed always yields the same sample, and a
    larger `per_category` is a superset of a smaller one.
    """
    by_category: dict[CategoryId, dict[str, list[ScenarioVariant]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for variant in variants:
        if variant.split == split:
            by_category[variant.category][variant.appliance_name].append(variant)

    sample: list[ScenarioVariant] = []
    for category in sorted(by_category):
        manuals = by_category[category]
        queues = [
            sorted(manuals[name], key=lambda v: _rank(seed, v.variant_id))
            for name in sorted(manuals, key=lambda name: _rank(seed, name))
        ]
        picked: list[ScenarioVariant] = []
        while len(picked) < per_category and any(queues):
            for queue in queues:
                if queue and len(picked) < per_category:
                    picked.append(queue.pop(0))
        sample.extend(picked)
    return sample


def pick_row(variant: ScenarioVariant, seed: str = "v1") -> ScenarioRow:
    """One tone per sampled variant, chosen deterministically so tones stay balanced overall."""
    return min(variant.rows, key=lambda row: _rank(seed, str(row.id)))
