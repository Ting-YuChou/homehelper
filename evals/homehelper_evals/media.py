"""Photos and videos for multimodal eval cases (M6-04): served from `data/media/` by path.

The paths in a case double as attachment ids. Nothing is uploaded: the agent reads the files the
way it reads uploads (`MediaSource`), so the upload pipeline is not part of what is measured.

No-model cases also let the simulated user photograph the model sticker or the appliance. There
is no image: the attachment comes with the analysis a vision model would return for the case's
appliance, so these cases measure what the agent does with a photo, not how well it reads one
(`homehelper_evals.vision` measures that).
"""

import asyncio
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any, Literal

from homehelper.knowledge.features import FEATURES_FILE, FeatureCatalog
from homehelper.media.schemas import SeenTrait, VisionResult
from homehelper.media.source import LoadedMedia
from homehelper_evals import MANIFEST_PATH, REPO_ROOT
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


SIMULATED_PHOTO = "sim-photo:"
PhotoKind = Literal["nameplate", "exterior"]
# A legible sticker; an appliance whose brand and type show but whose model number does not.
SIMULATED_CONFIDENCE: dict[PhotoKind, float] = {"nameplate": 0.95, "exterior": 0.8}


def simulated_photo(case: EvalCase, kind: PhotoKind | None) -> str | None:
    """The attachment id for a photo the simulated user takes, if the case allows it."""
    if kind == "nameplate" and case.model_knowledge == "finds_when_asked":
        allowed = case.reveal == "photo"
    else:
        allowed = kind == "exterior" and case.can_send_photo
    return f"{SIMULATED_PHOTO}{kind}" if allowed else None


def simulated_analysis(case: EvalCase, kind: PhotoKind) -> VisionResult:
    """What a vision model would report: the sticker's model number, or the appliance's look
    as `features.yaml` describes the case's manual (the first value of each trait)."""
    features = _features().manual(case.expected_doc_id) if case.expected_doc_id else None
    exterior = kind == "exterior" and features is not None
    return VisionResult(
        category=case.category.value if case.category else None,
        brand=case.brand,
        model_number=case.model_number if kind == "nameplate" else None,
        nameplate_text=f"MODEL {case.model_number}" if kind == "nameplate" else None,
        confidence=SIMULATED_CONFIDENCE[kind],
        features=[
            SeenTrait(name=name, value=values[0])
            for name, values in (features.traits.items() if exterior and features else [])
            if values
        ],
        badges=features.badges[:1] if exterior and features else [],
        features_confidence=SIMULATED_CONFIDENCE["exterior"] if exterior else 0,
    )


@cache
def _features() -> FeatureCatalog:
    return FeatureCatalog.load(MANIFEST_PATH.parent / FEATURES_FILE)


class EvalMediaSource:
    """A `MediaSource` over files; one per conversation, so its analysis cache is too. With a
    case it also serves that case's simulated photos."""

    def __init__(self, root: Path = MEDIA_ROOT, case: EvalCase | None = None) -> None:
        self.root = root
        self._case = case
        self._analyses: dict[str, dict[str, Any]] = {}

    async def load(self, ids: Sequence[str], user_id: str | None) -> list[LoadedMedia]:
        loaded = []
        for path in ids:
            if path.startswith(SIMULATED_PHOTO):
                if self._case is not None and (photo := self._simulated(path)):
                    loaded.append(photo)
                continue
            target = _resolve(self.root, path)
            if target is None:
                continue
            kind, mime = TYPES[target.suffix.lower()]
            loaded.append(
                LoadedMedia(path, kind, mime, str(target), self._analyses.get(path))  # type: ignore[arg-type]
            )
        return loaded

    def _simulated(self, attachment_id: str) -> LoadedMedia | None:
        assert self._case is not None
        kind = attachment_id.removeprefix(SIMULATED_PHOTO)
        if kind not in SIMULATED_CONFIDENCE:
            return None
        vision = simulated_analysis(self._case, kind)  # type: ignore[arg-type]
        # Saved as `perceive` saves it, so the agent uses it instead of calling the model.
        analysis = {"vision": vision.model_dump(mode="json"), "photos": [attachment_id]}
        return LoadedMedia(attachment_id, "image", "image/jpeg", attachment_id, analysis)

    async def read(self, media: LoadedMedia) -> bytes:
        return await asyncio.to_thread(Path(media.storage_uri).read_bytes)

    async def save_analysis(self, attachment_id: str, analysis: dict[str, Any]) -> None:
        self._analyses[attachment_id] = analysis
