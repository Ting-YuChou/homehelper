from collections import Counter
from pathlib import Path

from homehelper.ingestion.manifest import load_manifest
from homehelper.knowledge.features import FEATURES_FILE, FeatureCatalog, ManualFeatures
from homehelper.knowledge.schemas import CategoryId

MANUALS_DIR = Path(__file__).resolve().parents[4] / "data" / "manuals"


def _catalog() -> FeatureCatalog:
    return FeatureCatalog.load(MANUALS_DIR / FEATURES_FILE)


def test_every_entry_fits_the_manifest() -> None:
    manifest = load_manifest(MANUALS_DIR / "manifest.yaml")
    categories = {entry.doc_id: entry.category for entry in manifest}
    assert _catalog().problems(categories) == []


def test_every_category_says_where_the_model_sticker_is() -> None:
    assert set(_catalog().categories) == set(CategoryId)


def test_only_brands_with_several_manuals_in_a_category_are_listed() -> None:
    manifest = load_manifest(MANUALS_DIR / "manifest.yaml")
    groups = Counter((entry.brand, entry.category) for entry in manifest)
    by_doc = {entry.doc_id: (entry.brand, entry.category) for entry in manifest}
    assert all(groups[by_doc[doc_id]] > 1 for doc_id in _catalog().manuals)


def test_flat_entries_split_traits_from_badges() -> None:
    features = ManualFeatures.model_validate({"controls": ["top"], "badges": ["800 Series"]})
    assert features.traits == {"controls": ["top"]}
    assert features.badges == ["800 Series"]


def test_describe_uses_the_users_words() -> None:
    catalog = _catalog()
    assert catalog.describe("bosch-shx68t55", CategoryId.DISHWASHER) == [
        "on the top edge of the door",
        "built in under the counter",
        '"800 Series" printed on it or in its name',
    ]
    assert catalog.describe("lg-rh1077-vk", CategoryId.DRYER) == []  # nothing known


def test_problems_catches_unknown_traits_values_and_manuals() -> None:
    catalog = FeatureCatalog.model_validate(
        {
            "categories": {c.value: {"model_location": "on the back"} for c in CategoryId}
            | {
                "dishwasher": {
                    "model_location": "on the door",
                    "traits": {"controls": {"question": "?", "values": {"top": "top"}}},
                }
            },
            "manuals": {
                "a": {"controls": ["front"]},
                "b": {"colour": ["red"]},
                "c": {"controls": ["top"]},
            },
        }
    )
    problems = catalog.problems({"a": CategoryId.DISHWASHER, "b": CategoryId.DISHWASHER})
    assert problems == [
        "a: 'front' is not a controls value",
        "b: dishwasher has no trait 'colour'",
        "c: not in the manifest",
    ]
