from pathlib import Path
from types import SimpleNamespace
from typing import Any

from homehelper.ingestion.manifest import ManualEntry
from homehelper.ingestion.parse import ManualParser
from homehelper.knowledge.schemas import CategoryId


class FakeParsing:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        pages = [
            SimpleNamespace(page_number=2, markdown="## Troubleshooting\n| a | b |", success=True),
            SimpleNamespace(page_number=1, markdown="# Cover", success=True),
            SimpleNamespace(page_number=3, error="timeout", success=False),
        ]
        return SimpleNamespace(markdown=SimpleNamespace(pages=pages), job=SimpleNamespace())


def _entry(doc_id: str = "lg-wm3400") -> ManualEntry:
    return ManualEntry(
        doc_id=doc_id,
        file="washing_machine/LG/a.pdf",
        category=CategoryId.WASHING_MACHINE,
        brand="LG",
        title="LG Washer",
        pages=3,
        sha256="ab" * 32,
    )


async def test_parse_orders_pages_records_failures_and_caches(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    parsing = FakeParsing()
    parser = ManualParser("key", tmp_path / "cache", client=SimpleNamespace(parsing=parsing))  # type: ignore[arg-type]

    parsed, cached = await parser.parse(_entry(), pdf)
    assert not cached
    assert [p.page for p in parsed.pages] == [1, 2, 3]
    assert parsed.failed_pages == [3]
    assert parsing.calls[0]["tier"] == "cost_effective"
    assert parsing.calls[0]["upload_file"] == ("a.pdf", b"%PDF-1.7", "application/pdf")

    # Same PDF content under a renamed doc_id: served from cache, no new API call.
    again, cached = await parser.parse(_entry("renamed"), pdf)
    assert cached
    assert again.doc_id == "renamed"
    assert again.pages == parsed.pages
    assert len(parsing.calls) == 1
