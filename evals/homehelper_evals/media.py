"""Photos and videos for multimodal eval cases (M6-04): served from `data/media/` by path.

The paths in a case double as attachment ids. Nothing is uploaded: the agent reads the files the
way it reads uploads (`MediaSource`), so the upload pipeline is not part of what is measured.
"""

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from homehelper.media.source import LoadedMedia
from homehelper_evals import REPO_ROOT
from homehelper_evals.cases import EvalCase

MEDIA_ROOT = REPO_ROOT / "data" / "media"
TYPES = {
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".png": ("image", "image/png"),
    ".webp": ("image", "image/webp"),
    ".mp4": ("video", "video/mp4"),
    ".mov": ("video", "video/quicktime"),
    ".webm": ("video", "video/webm"),
}


def _resolve(root: Path, path: str) -> Path | None:
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        return None
    return target if target.suffix.lower() in TYPES else None


def missing_media(case: EvalCase, root: Path = MEDIA_ROOT) -> list[str]:
    return [item.path for item in case.media if _resolve(root, item.path) is None]


class EvalMediaSource:
    """A `MediaSource` over files; one per conversation, so its analysis cache is too."""

    def __init__(self, root: Path = MEDIA_ROOT) -> None:
        self.root = root
        self._analyses: dict[str, dict[str, Any]] = {}

    async def load(self, ids: Sequence[str], user_id: str | None) -> list[LoadedMedia]:
        loaded = []
        for path in ids:
            target = _resolve(self.root, path)
            if target is None:
                continue
            kind, mime = TYPES[target.suffix.lower()]
            loaded.append(
                LoadedMedia(path, kind, mime, str(target), self._analyses.get(path))  # type: ignore[arg-type]
            )
        return loaded

    async def read(self, media: LoadedMedia) -> bytes:
        return await asyncio.to_thread(Path(media.storage_uri).read_bytes)

    async def save_analysis(self, attachment_id: str, analysis: dict[str, Any]) -> None:
        self._analyses[attachment_id] = analysis
