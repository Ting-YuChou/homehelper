"""PDF → per-page Markdown via LlamaParse, cached by PDF content hash (spec §10.2 step 2, M1-02).

The cache (`data/parsed/<sha256>.<tier>.json`) means an unchanged PDF is never parsed (or paid
for) twice. Parsed output is derived from copyrighted manuals and is never committed.
"""

import asyncio
import json
from pathlib import Path
from typing import Literal

from llama_cloud import AsyncLlamaCloud
from pydantic import BaseModel

from homehelper.core.logging import get_logger
from homehelper.ingestion.manifest import ManualEntry

log = get_logger(__name__)

Tier = Literal["fast", "cost_effective", "agentic", "agentic_plus"]
DEFAULT_TIER: Tier = "cost_effective"
TIER_VERSION = "latest"
PARSE_TIMEOUT_S = 900.0


class ParsedPage(BaseModel):
    page: int  # 1-based, as in the PDF
    markdown: str
    error: str | None = None


class ParsedManual(BaseModel):
    doc_id: str
    sha256: str
    tier: str
    pages: list[ParsedPage]
    credits: float | None = None

    @property
    def failed_pages(self) -> list[int]:
        return [p.page for p in self.pages if p.error]


def cache_path(cache_dir: Path, sha256: str, tier: str) -> Path:
    return cache_dir / f"{sha256}.{tier}.json"


def load_cached(cache_dir: Path, entry: ManualEntry, tier: str) -> ParsedManual | None:
    path = cache_path(cache_dir, entry.sha256, tier)
    if not path.exists():
        return None
    parsed = ParsedManual.model_validate_json(path.read_text())
    return parsed.model_copy(update={"doc_id": entry.doc_id})


class ManualParser:
    def __init__(
        self,
        api_key: str,
        cache_dir: Path,
        tier: Tier = DEFAULT_TIER,
        *,
        client: AsyncLlamaCloud | None = None,
    ) -> None:
        self._client = client or AsyncLlamaCloud(api_key=api_key)
        self._cache_dir = cache_dir
        self._tier = tier

    async def parse(self, entry: ManualEntry, pdf_path: Path) -> tuple[ParsedManual, bool]:
        """Returns the parsed manual and whether it came from the cache."""
        cached = await asyncio.to_thread(load_cached, self._cache_dir, entry, self._tier)
        if cached is not None:
            return cached, True

        log.info("parse_started", doc_id=entry.doc_id, pages=entry.pages, tier=self._tier)
        result = await self._client.parsing.parse(
            tier=self._tier,
            version=TIER_VERSION,
            upload_file=(
                pdf_path.name,
                await asyncio.to_thread(pdf_path.read_bytes),
                "application/pdf",
            ),
            expand=["markdown"],
            output_options={
                "markdown": {"tables": {"output_tables_as_markdown": True}},
            },
            timeout=PARSE_TIMEOUT_S,
        )
        pages = [
            ParsedPage(
                page=page.page_number,
                markdown=getattr(page, "markdown", ""),
                error=getattr(page, "error", None),
            )
            for page in (result.markdown.pages if result.markdown else [])
        ]
        usage = getattr(result.job, "usage", None)
        parsed = ParsedManual(
            doc_id=entry.doc_id,
            sha256=entry.sha256,
            tier=self._tier,
            pages=sorted(pages, key=lambda p: p.page),
            credits=getattr(usage, "credits", None),
        )
        await asyncio.to_thread(self._write, parsed)
        log.info(
            "parse_finished",
            doc_id=entry.doc_id,
            pages=len(parsed.pages),
            failed_pages=parsed.failed_pages,
            credits=parsed.credits,
        )
        return parsed, False

    def _write(self, parsed: ParsedManual) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_path(self._cache_dir, parsed.sha256, parsed.tier)
        path.write_text(json.dumps(parsed.model_dump(), ensure_ascii=False))
