"""Read-only view of the manual manifest for evals (spec §10.1, §16.2): maps a scenario's
`appliance_name` (PDF filename) to the manual's `doc_id` and a concrete model number the
simulated user can give, so the citation check applies. The manifest is owned by the knowledge
track; while it is empty every lookup misses and the citation check is not applicable."""

import re
from collections import Counter
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel, Field

from homehelper.knowledge.features import FEATURES_FILE, FeatureCatalog
from homehelper.knowledge.schemas import CategoryId
from homehelper_evals import MANIFEST_PATH

MIN_MODEL_LENGTH = 4  # "LM*" expands to "LM", which names no real model


class ManualRef(BaseModel):
    doc_id: str
    brand: str | None = None  # reviewed display name: "Mr. Coffee", not the dataset's "Mr.Coffee"
    model_number: str | None = None
    category: CategoryId | None = None
    manuals_for_brand: int = 1  # manuals with this brand and category, this one included
    appearance: list[str] = Field(default_factory=list)  # visible traits (features.yaml)


def example_model_number(patterns: list[str]) -> str | None:
    """A deterministic model number that matches one of the manifest's glob patterns: the most
    specific pattern with a trailing `*` dropped and inner wildcards set to "0". Glob and prefix
    matching both accept it (spec §10.4 normalization)."""
    candidates = []
    for pattern in patterns:
        literal = re.sub(r"\[([^\]])[^\]]*\]", r"\1", pattern.strip())  # [AB] -> A
        literal = literal.rstrip("*")
        literal = literal.replace("*", "0").replace("?", "0")
        if len(re.sub(r"[^A-Za-z0-9]", "", literal)) >= MIN_MODEL_LENGTH:
            candidates.append(literal)
    if not candidates:
        return None
    return max(candidates, key=lambda c: (len(c), c))


def load_manuals(path: Path = MANIFEST_PATH) -> dict[str, ManualRef]:
    entries = yaml.safe_load(path.read_text()) or []
    features_path = path.parent / FEATURES_FILE
    features = FeatureCatalog.load(features_path) if features_path.exists() else None
    groups = Counter((e.get("brand"), e.get("category")) for e in entries)
    manuals: dict[str, ManualRef] = {}
    for entry in entries:
        category = CategoryId(entry["category"]) if entry.get("category") else None
        ref = ManualRef(
            doc_id=entry["doc_id"],
            brand=entry.get("brand"),
            model_number=example_model_number(entry.get("model_patterns") or []),
            category=category,
            manuals_for_brand=groups[(entry.get("brand"), entry.get("category"))],
            appearance=features.describe(entry["doc_id"], category)
            if features and category
            else [],
        )
        for filename in [entry["file"], *(entry.get("aliases") or [])]:
            manuals[PurePosixPath(filename).name] = ref
    return manuals


def doc_groups(path: Path = MANIFEST_PATH) -> dict[str, tuple[str | None, str | None]]:
    """doc_id -> (brand, category), to tell a sibling model's manual from another appliance's."""
    entries = yaml.safe_load(path.read_text()) or []
    return {e["doc_id"]: (e.get("brand"), e.get("category")) for e in entries}
