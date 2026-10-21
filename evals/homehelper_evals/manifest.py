"""Read-only view of the manual manifest for evals (spec §10.1, §16.2): maps a scenario's
`appliance_name` (PDF filename) to the manual's `doc_id` and a concrete model number the
simulated user can give, so the citation check applies. The manifest is owned by the knowledge
track; while it is empty every lookup misses and the citation check is not applicable."""

import re
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel

from homehelper_evals import MANIFEST_PATH

MIN_MODEL_LENGTH = 4  # "LM*" expands to "LM", which names no real model


class ManualRef(BaseModel):
    doc_id: str
    model_number: str | None = None


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
    manuals: dict[str, ManualRef] = {}
    for entry in entries:
        ref = ManualRef(
            doc_id=entry["doc_id"],
            model_number=example_model_number(entry.get("model_patterns") or []),
        )
        for filename in [entry["file"], *(entry.get("aliases") or [])]:
            manuals[PurePosixPath(filename).name] = ref
    return manuals
