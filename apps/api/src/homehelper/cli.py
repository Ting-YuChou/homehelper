"""`homehelper` command-line entry point (run from the repo root: `uv run homehelper --help`)."""

import asyncio

import typer

from homehelper.core.config import get_settings
from homehelper.core.logging import configure_logging
from homehelper.ingestion import manifest as manifest_lib
from homehelper.llm import build_llm_client

app = typer.Typer(no_args_is_help=True, help="HomeHelper maintenance commands.")
manifest_app = typer.Typer(no_args_is_help=True, help="Manual manifest (M1-01).")
app.add_typer(manifest_app, name="manifest")


@manifest_app.command("draft")
def manifest_draft(concurrency: int = typer.Option(8, help="Parallel LLM calls.")) -> None:
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


if __name__ == "__main__":
    app()
