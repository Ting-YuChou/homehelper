"""Manual PDFs for citations (spec §10.5, §13.2).

Locally the PDF is served from `data/manuals/pdfs/<manifest file>`. The public demo serves no
PDFs (spec Q10, ADR-011): the API image has none, so a manual's `url` is null and citations show
the manual's name and page only.
"""

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from homehelper.api.deps import SettingsDep, UserDep
from homehelper.api.schemas import ManualOut
from homehelper.ingestion.manifest import ManualEntry, load_manifest

router = APIRouter(prefix="/manuals", tags=["manuals"])


@lru_cache(maxsize=4)
def _manifest(path: Path, mtime: float) -> dict[str, ManualEntry]:
    return {entry.doc_id: entry for entry in load_manifest(path)}


def manual_entries(manuals_dir: Path) -> dict[str, ManualEntry]:
    path = manuals_dir / "manifest.yaml"
    return _manifest(path, path.stat().st_mtime) if path.exists() else {}


def _pdf(manuals_dir: Path, entry: ManualEntry) -> Path | None:
    pdfs = (manuals_dir / "pdfs").resolve()
    path = (pdfs / entry.file).resolve()
    return path if path.is_relative_to(pdfs) and path.is_file() else None


def _entry(manuals_dir: Path, doc_id: str) -> ManualEntry:
    entry = manual_entries(manuals_dir).get(doc_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown manual")
    return entry


@router.get("/{doc_id}", response_model=ManualOut)
async def get_manual(
    doc_id: str, request: Request, user: UserDep, settings: SettingsDep
) -> ManualOut:
    entry = _entry(settings.manuals_dir, doc_id)
    # Relative: browsers reach the API through the web app's `/v1` proxy (ADR-011).
    url = request.app.url_path_for("get_manual_file", doc_id=entry.doc_id)
    return ManualOut(
        doc_id=entry.doc_id,
        title=entry.title,
        brand=entry.brand,
        category=entry.category,
        pages=entry.pages,
        url=str(url) if _pdf(settings.manuals_dir, entry) else None,
    )


@router.get(
    "/{doc_id}/file",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}, "description": "The manual PDF."}},
)
async def get_manual_file(doc_id: str, user: UserDep, settings: SettingsDep) -> FileResponse:
    entry = _entry(settings.manuals_dir, doc_id)
    path = _pdf(settings.manuals_dir, entry)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Manual file not available")
    # inline: browsers open it in their PDF viewer, where `#page=N` jumps to the cited page.
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{entry.doc_id}.pdf",
        content_disposition_type="inline",
    )
