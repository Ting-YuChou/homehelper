"""`homehelper` command-line entry point (run from the repo root: `uv run homehelper --help`)."""

import asyncio
from typing import Annotated

import typer

from homehelper.core.config import get_settings
from homehelper.core.logging import configure_logging
from homehelper.db.engine import create_engine
from homehelper.ingestion import manifest as manifest_lib
from homehelper.ingestion import pipeline
from homehelper.ingestion.parse import ManualParser
from homehelper.llm import build_llm_client
from homehelper.mcp_servers.cli import app as mcp_app

app = typer.Typer(no_args_is_help=True, help="HomeHelper maintenance commands.")
manifest_app = typer.Typer(no_args_is_help=True, help="Manual manifest (M1-01).")
app.add_typer(manifest_app, name="manifest")
app.add_typer(mcp_app, name="mcp")


@manifest_app.command("draft")
def manifest_draft(
    concurrency: Annotated[int, typer.Option(help="Parallel LLM calls.")] = 8,
) -> None:
    """Draft entries for unreviewed PDFs and write manifest.yaml plus manifest_review.md."""
    settings = get_settings()
    configure_logging(settings.log_level)
    manuals = settings.manuals_dir
    manifest_path = manuals / "manifest.yaml"
    existing = manifest_lib.load_manifest(manifest_path)
    entries, extractions = asyncio.run(
        manifest_lib.draft_manifest(
            manuals / "pdfs", build_llm_client(settings), existing, concurrency=concurrency
        )
    )
    manifest_lib.save_manifest(manifest_path, entries)
    (manuals / "manifest_review.md").write_text(manifest_lib.review_report(entries, extractions))
    flagged = sum(1 for e in entries if e.notes or not e.model_patterns)
    typer.echo(f"{len(entries)} entries ({len(extractions)} drafted, {flagged} flagged)")


@app.command("parse")
def parse_manuals(
    only: Annotated[list[str] | None, typer.Option(help="doc_ids to parse (default: all).")] = None,
    concurrency: Annotated[int, typer.Option(help="Parallel LlamaParse jobs.")] = 6,
) -> None:
    """Parse manual PDFs to Markdown with LlamaParse (cached by PDF hash; M1-02)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    api_key = settings.llama_cloud_api_key.get_secret_value()
    if not api_key:
        raise typer.BadParameter("LLAMA_CLOUD_API_KEY is not set")
    entries = manifest_lib.load_manifest(settings.manuals_dir / "manifest.yaml")
    if only:
        entries = [e for e in entries if e.doc_id in set(only)]
    parser = ManualParser(api_key, settings.data_dir / "parsed")
    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(entry: manifest_lib.ManualEntry) -> tuple[str, bool, list[int]]:
        async with semaphore:
            parsed, cached = await parser.parse(entry, settings.manuals_dir / "pdfs" / entry.file)
        return entry.doc_id, cached, parsed.failed_pages

    async def run_all() -> list[tuple[str, bool, list[int]]]:
        return await asyncio.gather(*(run_one(e) for e in entries))

    results = asyncio.run(run_all())
    fresh = sum(1 for _, cached, _ in results if not cached)
    failed = {doc_id: pages for doc_id, _, pages in results if pages}
    typer.echo(f"{len(results)} manuals ({fresh} parsed, {len(results) - fresh} cached)")
    if failed:
        typer.echo(f"pages that failed to parse: {failed}")


@app.command("ingest")
def ingest_manuals(
    parse_concurrency: Annotated[int, typer.Option(help="Parallel LlamaParse jobs.")] = 6,
) -> None:
    """Build a new frozen kb_version from the reviewed manifest (M1-04). Needs `make migrate`."""
    settings = get_settings()
    configure_logging(settings.log_level)

    async def run() -> pipeline.IngestResult:
        engine = create_engine(settings.database_url)
        try:
            return await pipeline.ingest(settings, engine, parse_concurrency=parse_concurrency)
        finally:
            await engine.dispose()

    result = asyncio.run(run())
    typer.echo(
        f"{result.kb_version}: {result.chunk_count} chunks from {result.manuals} manuals "
        f"({result.parsed_now} newly parsed)"
    )


if __name__ == "__main__":
    app()
