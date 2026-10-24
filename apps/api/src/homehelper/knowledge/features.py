"""What a user can see on an appliance when they don't know its model number
(`data/manuals/features.yaml`): where the model sticker usually is, and the visible traits that
tell manuals of the same brand and category apart."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from homehelper.ingestion.manifest import ManualEntry, load_manifest
from homehelper.knowledge.model_numbers import matches_any
from homehelper.knowledge.schemas import CategoryId

FEATURES_FILE = "features.yaml"  # next to manifest.yaml


class Trait(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    values: dict[str, str]  # value -> how the user would describe it


class CategoryFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_location: str
    traits: dict[str, Trait] = Field(default_factory=dict)


class ManualFeatures(BaseModel):
    """The trait values one manual covers (several when it covers several variants), and text
    printed on the appliance or in its name. A trait it doesn't list is unknown."""

    traits: dict[str, list[str]] = Field(default_factory=dict)
    badges: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _flat(cls, data: Any) -> Any:
        # The file lists traits next to `badges`: {controls: [top], badges: [800 Series]}.
        if isinstance(data, dict) and "traits" not in data:
            data = dict(data)
            badges = data.pop("badges", [])
            return {"traits": data, "badges": badges}
        return data


class FeatureCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categories: dict[CategoryId, CategoryFeatures] = Field(default_factory=dict)
    manuals: dict[str, ManualFeatures] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "FeatureCatalog":
        return cls.model_validate(yaml.safe_load(path.read_text()))

    def manual(self, doc_id: str) -> ManualFeatures:
        return self.manuals.get(doc_id) or ManualFeatures()

    def describe(self, doc_id: str, category: CategoryId) -> list[str]:
        """The manual's traits as a user would say them ("front-loading"), then its badges."""
        traits = self.categories[category].traits
        features = self.manual(doc_id)
        facts = [
            traits[name].values[value]
            for name, values in features.traits.items()
            for value in values
        ]
        return facts + [f'"{badge}" printed on it or in its name' for badge in features.badges]

    def problems(self, categories: dict[str, CategoryId]) -> list[str]:
        """Entries that don't fit `categories` (doc_id -> category, from the manifest)."""
        found = []
        for doc_id, features in self.manuals.items():
            category = categories.get(doc_id)
            if category is None:
                found.append(f"{doc_id}: not in the manifest")
                continue
            traits = self.categories[category].traits
            for name, values in features.traits.items():
                if name not in traits:
                    found.append(f"{doc_id}: {category} has no trait {name!r}")
                    continue
                found.extend(
                    f"{doc_id}: {value!r} is not a {name} value"
                    for value in values
                    if value not in traits[name].values
                )
        return found


TRAIT_SLOT_PREFIX = "trait_"  # journey slots holding what the user sees: `trait_<name>`
BADGE_SLOT = "badge"


def trait_slot(name: str) -> str:
    return f"{TRAIT_SLOT_PREFIX}{name}"


@dataclass(frozen=True)
class ManualIndex:
    """The reviewed manuals and what tells them apart: which manuals the user's appliance can be
    when they don't know its model number (ADR-013). Read-only, shared by every turn."""

    manuals: tuple[ManualEntry, ...]
    features: FeatureCatalog

    @classmethod
    def load(cls, manuals_dir: Path) -> "ManualIndex":
        manuals = tuple(m for m in load_manifest(manuals_dir / "manifest.yaml") if m.reviewed)
        path = manuals_dir / FEATURES_FILE
        return cls(manuals, FeatureCatalog.load(path) if path.exists() else FeatureCatalog())

    def entry(self, doc_id: str) -> ManualEntry | None:
        return next((m for m in self.manuals if m.doc_id == doc_id), None)

    def model_manuals(self, model_number: str, category: CategoryId | None) -> list[str]:
        """The manuals whose model patterns match, as the retriever's model level finds them."""
        return [
            m.doc_id
            for m in self.manuals
            if matches_any(model_number, m.model_patterns)
            and (category is None or m.category == category)
        ]

    def candidates(self, category: CategoryId, brand: str | None) -> list[str]:
        """Every manual of the category, or of the brand in it; none for a brand we don't have."""
        wanted = (brand or "").strip().lower()
        return [
            m.doc_id
            for m in self.manuals
            if m.category == category and (not wanted or m.brand.lower() == wanted)
        ]

    def narrow(
        self, doc_ids: list[str], traits: dict[str, str], badge: str | None = None
    ) -> list[str]:
        """The candidates that fit what the user sees. A manual that doesn't state a trait
        stays (unknown is not a no), and a trait or badge that would rule out all of them is
        ignored: the user may be wrong, the manuals can't all be."""
        kept = list(doc_ids)
        for name, value in traits.items():
            fitting = [
                d for d in kept if value in self.features.manual(d).traits.get(name, [value])
            ]
            kept = fitting or kept
        if badge:
            seen = badge.strip().lower()
            fitting = [
                d
                for d in kept
                if any(
                    seen in b.lower() or b.lower() in seen for b in self.features.manual(d).badges
                )
            ]
            kept = fitting or kept
        return kept

    def splitting_trait(
        self, doc_ids: list[str], category: CategoryId, known: dict[str, str] | None = None
    ) -> tuple[str, Trait] | None:
        """The trait whose answer best tells the candidates apart (the most even split, then the
        fewest manuals it says nothing about), skipping traits already known. None if no trait
        tells any of them apart."""
        vocabulary = self.features.categories.get(category)
        if vocabulary is None or len(doc_ids) < 2:
            return None
        best: tuple[tuple[int, int], str] | None = None
        for name in vocabulary.traits:
            if known and name in known:
                continue
            listed = [self.features.manual(d).traits.get(name) for d in doc_ids]
            values = {v for values in listed if values for v in values}
            if len(values) < 2:
                continue
            unknown = sum(values is None for values in listed)
            largest = max(sum(1 for vs in listed if vs is None or v in vs) for v in values)
            score = (largest, unknown)
            if best is None or score < best[0]:
                best = (score, name)
        return (best[1], vocabulary.traits[best[1]]) if best else None

    def model_location(self, category: CategoryId) -> str:
        vocabulary = self.features.categories.get(category)
        return vocabulary.model_location if vocabulary else "on a sticker on the appliance"

    def trait(self, category: CategoryId, name: str) -> Trait | None:
        vocabulary = self.features.categories.get(category)
        return vocabulary.traits.get(name) if vocabulary else None
