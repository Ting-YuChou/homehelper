"""`data/mock/` integrity (M5-01): every demo appliance resolves to a manual, ids are consistent."""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from homehelper.ingestion.manifest import ManualEntry, load_manifest
from homehelper.knowledge.model_numbers import matches_any
from homehelper.mcp_servers.mock_data import MockData
from homehelper.mcp_servers.schemas import Appliance

REPO = Path(__file__).resolve().parents[5]
DATA = MockData.load(REPO / "data" / "mock")
MANIFEST = load_manifest(REPO / "data" / "manuals" / "manifest.yaml")
# The date the demo data was written for; warranty dates are relative to it.
DEMO_DATE = date(2026, 10, 21)


def _manuals_for(appliance: Appliance) -> list[ManualEntry]:
    # Retrieval filters on brand + category before model (spec §10.4), so match within those.
    return [
        e
        for e in MANIFEST
        if e.brand == appliance.brand
        and e.category == appliance.category
        and matches_any(appliance.model_number, e.model_patterns)
    ]


@pytest.mark.parametrize("appliance", DATA.appliances, ids=lambda a: a.appliance_id)
def test_every_appliance_matches_exactly_one_manual(appliance: Appliance) -> None:
    manuals = _manuals_for(appliance)
    assert len(manuals) == 1, [m.doc_id for m in manuals]


def test_ids_are_unique_and_references_resolve() -> None:
    for ids in (
        [u.user_id for u in DATA.users],
        [a.appliance_id for a in DATA.appliances],
        [r.record_id for r in DATA.repair_history],
        [p.part_id for p in DATA.parts],
        [t.technician_id for t in DATA.technicians],
        [v.video_id for v in DATA.videos],
    ):
        assert len(ids) == len(set(ids))
    owners = {a.appliance_id: a.user_id for a in DATA.appliances}
    for record in DATA.repair_history:
        assert owners[record.appliance_id] == record.user_id


def test_users_have_two_to_four_appliances_and_a_technician_for_each() -> None:
    assert 3 <= len(DATA.users) <= 5
    per_user = Counter(a.user_id for a in DATA.appliances)
    assert set(per_user) == {u.user_id for u in DATA.users}
    assert all(2 <= n <= 4 for n in per_user.values())
    for appliance in DATA.appliances:
        user = DATA.user(appliance.user_id)
        assert user is not None
        assert any(t.serves(user.zip_code, appliance.category) for t in DATA.technicians)


def test_demo_coverage_for_warranty_and_history() -> None:
    # G-WARR-01 needs an appliance under warranty; personalization needs a past fix to mention.
    assert any(a.warranty_until and a.warranty_until > DEMO_DATE for a in DATA.appliances)
    assert any(a.warranty_until is None for a in DATA.appliances)  # unknown (landlord-owned)
    washer_drain = [
        r
        for r in DATA.repair_history
        if r.appliance_id == "apl_alex_washer" and "drain" in r.issue.lower()
    ]
    assert washer_drain and washer_drain[0].outcome == "resolved"


def test_part_brands_and_model_patterns_come_from_the_manifest() -> None:
    brands = {e.brand for e in MANIFEST}
    patterns = {p for e in MANIFEST for p in e.model_patterns}
    for part in DATA.parts:
        assert set(part.brands) <= brands, part.part_id
        assert set(part.compatible_models) <= patterns, part.part_id
