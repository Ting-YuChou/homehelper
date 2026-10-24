"""Retrieval queries derived from the scenario dataset: one per (scenario text, manual) pair."""

import json
from pathlib import Path

from pydantic import BaseModel

from homehelper.ingestion.manifest import file_index, load_manifest
from homehelper.knowledge.schemas import CategoryId
from homehelper_evals import REPO_ROOT, SCENARIOS_PATH
from homehelper_evals.manifest import example_model_number
from homehelper_evals.splits import Split, group_key, load_splits

# v1 dataset product names → category ids (including the v1 "Diswasher" typo).
PRODUCT_CATEGORIES = {
    "WashingMachines": CategoryId.WASHING_MACHINE,
    "CoffeeMaker": CategoryId.COFFEE_MAKER,
    "Dryer": CategoryId.DRYER,
    "Diswasher": CategoryId.DISHWASHER,
    "Microwave": CategoryId.MICROWAVE,
    "Vacuum": CategoryId.VACUUM,
    "Television": CategoryId.TELEVISION,
    "Refrigerator": CategoryId.REFRIGERATOR,
    "Blender-FoodProcessor": CategoryId.BLENDER_FOOD_PROCESSOR,
    "WaterPurifier": CategoryId.WATER_PURIFIER,
}


class RetrievalCase(BaseModel):
    case_id: str  # the first dataset row id of this (scenario, manual) pair
    query: str
    doc_id: str  # the manual the scenario was written from
    category: CategoryId
    brand: str  # from the manifest, so v1 label mistakes (e.g. LG vs Samsung) don't leak in
    split: Split
    # A model number the manual's patterns match (`manifest.example_model_number`), if any.
    model_number: str | None = None


def load_cases(manifest_path: Path | None = None) -> list[RetrievalCase]:
    manifest_path = manifest_path or REPO_ROOT / "data" / "manuals" / "manifest.yaml"
    entries = {e.doc_id: e for e in load_manifest(manifest_path)}
    index = file_index(entries.values())
    splits = load_splits()
    cases: dict[tuple[str, str], RetrievalCase] = {}
    with SCENARIOS_PATH.open() as f:
        for line in f:
            row = json.loads(line)
            doc_id = index[row["appliance_name"]]
            key = (group_key(row["scenario"]), doc_id)
            if key not in cases:
                cases[key] = RetrievalCase(
                    case_id=str(row["id"]),
                    query=row["scenario"].strip(),
                    doc_id=doc_id,
                    category=PRODUCT_CATEGORIES[row["product_name"]],
                    brand=entries[doc_id].brand,
                    split=splits[str(row["id"])],
                    model_number=example_model_number(entries[doc_id].model_patterns),
                )
    return list(cases.values())
