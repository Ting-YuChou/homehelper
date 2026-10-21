import pytest

from homehelper.ingestion.chunking import (
    Chunk,
    ManualChunker,
    classify,
    clean_heading,
    is_probably_english,
    split_table,
)
from homehelper.ingestion.manifest import ManualEntry
from homehelper.ingestion.parse import ParsedManual, ParsedPage
from homehelper.knowledge.schemas import CategoryId

ENTRY = ManualEntry(
    doc_id="lg-wm3400",
    file="washing_machine/LG/a.pdf",
    category=CategoryId.WASHING_MACHINE,
    brand="LG",
    title="Front Load Washer",
    model_patterns=["WM3400*"],
    pages=5,
    sha256="0" * 64,
)

TROUBLE_TABLE = """| Problem | Possible Cause | Solution |
| --- | --- | --- |
| Washer will not start | Door is open | Close the door firmly and press Start. |
| Water is not draining | Drain hose is kinked | Straighten the drain hose. |"""

PAGES = [
    ParsedPage(
        page=1, markdown="# Table of Contents\n\nSafety ........ 2\nTroubleshooting ........ 4"
    ),
    ParsedPage(
        page=2,
        markdown=(
            "# **IMPORTANT SAFETY INSTRUCTIONS**\n\n"
            "Read all instructions before using the appliance. Unplug the washer before "
            "servicing it. Do not let children play on or in the appliance."
        ),
    ),
    ParsedPage(page=3, markdown="# Troubleshooting\n\n" + TROUBLE_TABLE),
    ParsedPage(
        page=4,
        markdown=(
            "# TROUBLESHOOTING CONT.\n\n## Error Codes\n\n"
            "| Code | Meaning | Solution |\n| --- | --- | --- |\n"
            "| OE | Drain error | Clean the drain pump filter. |"
        ),
    ),
    ParsedPage(
        page=5,
        markdown=(
            "# Dépannage\n\nSi la laveuse ne démarre pas, vérifiez que la porte est bien fermée "
            "et que le cordon est branché. Pour votre sécurité, débranchez la laveuse avant "
            "de la nettoyer. Les tuyaux doivent être droits pour que l'eau puisse être "
            "évacuée et que la laveuse fonctionne avec votre détergent."
        ),
    ),
]


@pytest.fixture(scope="module")
def chunks() -> list[Chunk]:
    parsed = ParsedManual(doc_id=ENTRY.doc_id, sha256=ENTRY.sha256, tier="t", pages=PAGES)
    return ManualChunker().chunk(ENTRY, parsed)


def test_chunks_keep_sections_pages_and_types(chunks: list[Chunk]) -> None:
    summary = [
        (c.metadata.section_path, c.metadata.page_start, c.metadata.chunk_type) for c in chunks
    ]
    assert summary == [
        (["Important Safety Instructions"], 2, "safety"),
        (["Troubleshooting"], 3, "troubleshooting_table"),
        # "TROUBLESHOOTING CONT." continues the same section on the next page.
        (["Troubleshooting", "Error Codes"], 4, "error_code"),
    ]
    assert chunks[1].text.startswith("[LG Front Load Washer — Troubleshooting]\n| Problem |")
    assert chunks[1].metadata.model_patterns == ["WM3400*"]
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_table_of_contents_and_non_english_pages_are_skipped(chunks: list[Chunk]) -> None:
    pages = {c.metadata.page_start for c in chunks}
    assert 1 not in pages  # table of contents
    assert 5 not in pages  # French


def test_large_tables_split_by_rows_with_header_repeated() -> None:
    rows = "\n".join(f"| E{i} | Fault {i} | Call service |" for i in range(40))
    table = "| Code | Meaning | Action |\n| --- | --- | --- |\n" + rows
    chunker = ManualChunker()
    pieces = split_table(table, 100, chunker.count_tokens)
    assert len(pieces) > 1
    assert all(p.startswith("| Code | Meaning | Action |\n| --- | --- | --- |\n") for p in pieces)
    assert all(chunker.count_tokens(p) <= 100 for p in pieces)
    assert sum(p.count("| E") for p in pieces) == 40
    assert split_table(TROUBLE_TABLE, 500, chunker.count_tokens) == [TROUBLE_TABLE]


def test_long_text_is_split_and_tracks_page_ranges() -> None:
    sentence = "Clean the filter every month to keep the dishwasher running well. "
    pages = [
        ParsedPage(page=7, markdown="# Care and Cleaning\n\n" + sentence * 80),
        ParsedPage(page=8, markdown=sentence * 80),
        ParsedPage(page=9, markdown="Short tail of the paragraph on the next page."),
    ]
    parsed = ParsedManual(doc_id="x", sha256="0" * 64, tier="t", pages=pages)
    chunks = ManualChunker().chunk(ENTRY, parsed)
    ranges = [(c.metadata.page_start, c.metadata.page_end) for c in chunks]
    assert len(chunks) >= 4
    assert ranges[0] == (7, 7)
    assert ranges[-1] == (8, 9)  # a short page fragment is merged into its neighbour
    assert all(c.metadata.chunk_type == "procedure" for c in chunks)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("**TROUBLESHOOTING CONT.**", "Troubleshooting"),
        ("Error Codes (continued)", "Error Codes"),
        ("26 Operation", "Operation"),
        ("Mr. Coffee<sup>®</sup> Express", "Mr. Coffee Express"),
    ],
)
def test_clean_heading(raw: str, expected: str) -> None:
    assert clean_heading(raw) == expected


def test_classify_by_table_header_and_headings() -> None:
    issues = "| Issues | Solutions and Explanations |\n| --- | --- |\n| No picture | Check cable |"
    assert classify(("Note",), issues, is_table=True) == "troubleshooting_table"
    assert classify(("Error indication",), "The control shows a code.", False) == "error_code"
    assert classify(("Installation",), "1. Unpack.\n2. Level the unit.", False) == "procedure"
    assert classify(("Specifications",), "Weight: 10 kg", False) == "general"


def test_is_probably_english() -> None:
    assert is_probably_english("Short text")
    assert is_probably_english(" ".join(["the washer is ready for your laundry"] * 10))
    assert not is_probably_english(" ".join(["pour votre sécurité et avec les tuyaux"] * 10))
