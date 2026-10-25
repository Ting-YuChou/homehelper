from collections import Counter
from pathlib import Path

from homehelper.ingestion.manifest import load_manifest
from homehelper.knowledge.features import (
    FEATURES_FILE,
    FeatureCatalog,
    ManualFeatures,
    ManualIndex,
)
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


def _index() -> ManualIndex:
    return ManualIndex.load(MANUALS_DIR)


def test_candidates_are_the_brands_manuals_in_the_category() -> None:
    index = _index()
    fridges = index.candidates(CategoryId.REFRIGERATOR, "samsung")
    assert sorted(fridges) == [
        "samsung-rf23db",
        "samsung-rf24bb6",
        "samsung-rz32",
        "samsung-side-by-side",
    ]
    assert index.candidates(CategoryId.REFRIGERATOR, "Maytag") == []
    assert len(index.candidates(CategoryId.REFRIGERATOR, None)) == 10
    assert index.model_manuals("RF23DB9600QL", CategoryId.REFRIGERATOR) == ["samsung-rf23db"]


def test_narrow_keeps_what_fits_and_never_rules_everything_out() -> None:
    index = _index()
    fridges = index.candidates(CategoryId.REFRIGERATOR, "Samsung")
    assert sorted(index.narrow(fridges, {"layout": "french_door"})) == [
        "samsung-rf23db",
        "samsung-rf24bb6",
    ]
    assert index.narrow(fridges, {"layout": "top_freezer"}) == fridges  # nothing fits: ignored
    dishwashers = index.candidates(CategoryId.DISHWASHER, "Siemens")
    # sn636x03 states no badge, the iQ100 is ruled out by "iQ500".
    assert sorted(index.narrow(dishwashers, {}, "iq500")) == [
        "siemens-sn258i06",
        "siemens-sn56p530eu",
    ]
    # A trait a manual doesn't state keeps it.
    bosch = index.candidates(CategoryId.DISHWASHER, "Bosch")
    assert sorted(index.narrow(bosch, {"controls": "front"})) == [
        "bosch-she3ar76u",
        "bosch-sps4emi28e",
    ]


def test_splitting_trait_picks_the_question_that_tells_them_apart() -> None:
    index = _index()
    microwaves = index.candidates(CategoryId.MICROWAVE, "Samsung")
    name, trait = index.splitting_trait(microwaves, CategoryId.MICROWAVE) or ("", None)
    assert name == "cooking" and trait is not None and "Convection" in trait.question
    criterion = index.candidates(CategoryId.DISHWASHER, "Criterion")
    assert (index.splitting_trait(criterion, CategoryId.DISHWASHER) or ("",))[0] == "controls"
    # All five LG washers load from the front: no question helps.
    washers = index.candidates(CategoryId.WASHING_MACHINE, "LG")
    assert index.splitting_trait(washers, CategoryId.WASHING_MACHINE) is None
    # Asked already: not asked again.
    assert index.splitting_trait(criterion, CategoryId.DISHWASHER, {"controls": "top"}) is None
    assert index.model_location(CategoryId.DRYER).startswith("on a sticker inside the door")
