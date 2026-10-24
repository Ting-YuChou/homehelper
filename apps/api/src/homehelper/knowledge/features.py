"""What a user can see on an appliance when they don't know its model number
(`data/manuals/features.yaml`): where the model sticker usually is, and the visible traits that
tell manuals of the same brand and category apart."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

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

    categories: dict[CategoryId, CategoryFeatures]
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
