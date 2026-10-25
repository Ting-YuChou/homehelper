"""A small manual library for the no-model tests (ADR-013): three Samsung fridges told apart by
their layout, and one Bosch dishwasher (the brand's only one)."""

from homehelper.ingestion.manifest import ManualEntry
from homehelper.knowledge.features import FeatureCatalog, ManualIndex
from homehelper.knowledge.schemas import CategoryId

FRIDGES = {
    "samsung-fd1": ("French Door Refrigerator", ["RF23*"], "french_door"),
    "samsung-fd2": ("Refrigerator", ["RF24*"], "french_door"),
    "samsung-sbs": ("Side by Side Refrigerator", ["RS27*"], "side_by_side"),
}


def _entry(doc_id: str, category: CategoryId, brand: str, title: str, patterns: list[str]):
    return ManualEntry(
        doc_id=doc_id,
        file=f"{category.value}/{brand}/{doc_id}.pdf",
        category=category,
        brand=brand,
        title=f"{brand} {title}",
        model_patterns=patterns,
        pages=1,
        sha256="0" * 64,
        reviewed=True,
    )


def manual_index() -> ManualIndex:
    manuals = [
        _entry(doc_id, CategoryId.REFRIGERATOR, "Samsung", title, patterns)
        for doc_id, (title, patterns, _) in FRIDGES.items()
    ]
    manuals.append(_entry("bosch-dw", CategoryId.DISHWASHER, "Bosch", "Dishwasher", ["SHX*"]))
    features = FeatureCatalog.model_validate(
        {
            "categories": {
                "refrigerator": {
                    "model_location": "inside the fresh-food compartment",
                    "traits": {
                        "layout": {
                            "question": "Is it French door or side by side?",
                            "values": {
                                "french_door": "French door",
                                "side_by_side": "side by side",
                            },
                        }
                    },
                },
                "dishwasher": {"model_location": "on the edge of the door"},
            },
            "manuals": {doc_id: {"layout": [layout]} for doc_id, (_, _, layout) in FRIDGES.items()},
        }
    )
    return ManualIndex(tuple(manuals), features)
