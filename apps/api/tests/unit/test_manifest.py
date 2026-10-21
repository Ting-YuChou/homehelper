from pathlib import Path

import pytest

from homehelper.ingestion import manifest as m
from homehelper.knowledge.schemas import CategoryId
from homehelper.llm import FakeLLMClient


def _extraction(patterns: list[str], quality: str = "good") -> m.ManualExtraction:
    return m.ManualExtraction(
        title="Washer",
        model_numbers=patterns,
        model_patterns=patterns,
        language="en",
        text_quality=quality,  # type: ignore[arg-type]
        evidence="Model " + ", ".join(patterns),
    )


@pytest.fixture
def pdf_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for rel in ("washing_machine/LG/a.pdf", "washing_machine/LG/b.pdf", "dryer/Samsung/c.pdf"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"%PDF-1.7 fake")
    monkeypatch.setattr(m, "read_front_text", lambda path: (10, f"text of {path.name}"))
    return tmp_path


async def test_draft_assigns_unique_ids_and_flags_poor_text(pdf_root: Path) -> None:
    llm = FakeLLMClient(
        {
            "extract": [
                lambda msgs: (
                    _extraction(["DV45*"], "garbled")
                    if "c.pdf" in str(msgs[1].content)
                    else _extraction(["WM3400*"])
                )
            ]
            * 3
        }
    )
    entries, extractions = await m.draft_manifest(pdf_root, llm, existing=[])

    assert [e.file for e in entries] == [
        "dryer/Samsung/c.pdf",
        "washing_machine/LG/a.pdf",
        "washing_machine/LG/b.pdf",
    ]
    assert [e.doc_id for e in entries] == ["samsung-dv45", "lg-wm3400", "lg-wm3400-2"]
    assert entries[0].category is CategoryId.DRYER
    assert entries[0].notes == "text garbled"
    assert all(e.pages == 10 and len(e.sha256) == 64 and not e.reviewed for e in entries)
    assert set(extractions) == {e.file for e in entries}


async def test_reviewed_entries_are_kept_and_not_sent_to_the_llm(pdf_root: Path) -> None:
    reviewed = m.ManualEntry(
        doc_id="lg-hand-picked",
        file="washing_machine/LG/a.pdf",
        category=CategoryId.WASHING_MACHINE,
        brand="LG",
        title="Reviewed",
        model_patterns=["WM9*"],
        aliases=["a(1).pdf"],
        pages=10,
        sha256="x" * 64,
        reviewed=True,
    )
    llm = FakeLLMClient({"extract": [_extraction(["WM3400*"])] * 2})
    entries, _ = await m.draft_manifest(pdf_root, llm, existing=[reviewed])

    assert len(llm.calls) == 2
    assert next(e for e in entries if e.file == reviewed.file) == reviewed
    assert m.file_index(entries)["a(1).pdf"] == "lg-hand-picked"


def test_manifest_round_trip(tmp_path: Path) -> None:
    entry = m.ManualEntry(
        doc_id="x",
        file="dryer/LG/x.pdf",
        category=CategoryId.DRYER,
        brand="LG",
        title="X",
        pages=1,
        sha256="0" * 64,
    )
    path = tmp_path / "manifest.yaml"
    m.save_manifest(path, [entry])
    assert m.load_manifest(path) == [entry]
    assert m.load_manifest(tmp_path / "missing.yaml") == []


def test_committed_manifest_is_reviewed_and_maps_every_eval_label() -> None:
    import json

    repo = Path(__file__).resolve().parents[4]
    entries = m.load_manifest(repo / "data/manuals/manifest.yaml")
    assert entries and all(e.reviewed for e in entries)
    assert len({e.doc_id for e in entries}) == len(entries)
    index = m.file_index(entries)
    with (repo / "data/scenarios/home_helper_dataset.jsonl").open() as f:
        labels = {json.loads(line)["appliance_name"] for line in f}
    assert labels <= index.keys()


def test_slugify() -> None:
    assert m.slugify("Black+Decker--BL2010*") == "black-decker-bl2010"
