"""`perceive` (M6-02/03, spec §11.2-11.3): what the message's photos and video show, before NLU
reads its words.

All photos of a message go to the vision model in one call; a video goes to Gemini at the same
time, bounded by the `video` task's timeout (60 s), with an "analyzing" status first. Answers are
cached on the attachments, so a retried turn reuses them. A failed or slow analysis is recorded,
not raised: the engine answers with M-MEDIA-01 and the conversation goes on.
"""

import asyncio
import base64
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from homehelper.agent import prompts
from homehelper.agent.deps import AgentDeps
from homehelper.agent.nodes.understand import MEDIA_ONLY_TEXT
from homehelper.agent.turn import GraphState
from homehelper.channels.events import AgentEvent, StatusEvent
from homehelper.core.logging import get_logger
from homehelper.knowledge.features import ManualIndex
from homehelper.knowledge.schemas import CategoryId
from homehelper.llm import LLMClient, Message
from homehelper.media.schemas import MediaObservation, VideoResult, VisionResult
from homehelper.media.source import LoadedMedia

log = get_logger(__name__)
__all__ = ["MEDIA_ONLY_TEXT", "analyze_images", "perceive", "vision_messages"]

CATEGORIES = [category.value for category in CategoryId]


def vision_traits(manuals: ManualIndex | None) -> dict[str, list[dict[str, object]]]:
    """Per category, the visible traits the vision model may report (ADR-013)."""
    if manuals is None:
        return {}
    return {
        category.value: [
            {"name": name, "values": list(trait.values)} for name, trait in vocab.traits.items()
        ]
        for category, vocab in manuals.features.categories.items()
        if vocab.traits
    }


def known_traits(vision: VisionResult, manuals: ManualIndex | None) -> VisionResult:
    """Only traits and values the photo's category has: anything else is dropped."""
    category = vision.category if vision.category in CATEGORIES else None
    if manuals is None or category is None:
        return vision.model_copy(update={"features": []})
    kept = [
        t
        for t in vision.features
        if (trait := manuals.trait(CategoryId(category), t.name)) and t.value in trait.values
    ]
    return vision.model_copy(update={"features": kept})


def vision_messages(
    images: list[tuple[str, bytes]], traits: dict[str, list[dict[str, object]]] | None = None
) -> list[Message]:
    """One user message: the instructions, then each photo as a data URL (`mime`, bytes)."""
    text = prompts.render("vision", count=len(images), categories=CATEGORIES, traits=traits or {})
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for mime, data in images:
        url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return [Message(role="user", content=parts)]


async def analyze_images(
    llm: LLMClient,
    images: list[tuple[str, bytes]],
    traits: dict[str, list[dict[str, object]]] | None = None,
) -> VisionResult:
    return await llm.structured("vision", vision_messages(images, traits), VisionResult)


def _cached(photos: list[LoadedMedia]) -> VisionResult | None:
    """The saved answer, if it was for exactly these photos."""
    ids = [p.attachment_id for p in photos]
    analyses = [p.analysis or {} for p in photos]
    if all(a.get("photos") == ids and "vision" in a for a in analyses):
        try:
            return VisionResult.model_validate(analyses[0]["vision"])
        except ValidationError:
            return None  # saved under an older schema: analyze again
    return None


async def _photos(deps: AgentDeps, photos: list[LoadedMedia]) -> list[MediaObservation]:
    assert deps.media is not None
    vision = _cached(photos)
    if vision is None:
        try:
            images = [(p.mime, await deps.media.read(p)) for p in photos]
            vision = await analyze_images(deps.llm, images, vision_traits(deps.manuals))
        except Exception as exc:  # storage, provider or schema: never fails the turn
            log.warning("vision_failed", error=f"{type(exc).__name__}: {exc}", photos=len(photos))
            return [
                MediaObservation(
                    attachment_id=p.attachment_id, kind="image", error="analysis_failed"
                )
                for p in photos
            ]
        analysis = {
            "vision": vision.model_dump(mode="json"),
            "photos": [p.attachment_id for p in photos],
        }
        for photo in photos:
            await _save(deps, photo.attachment_id, analysis)
    vision = known_traits(vision, deps.manuals)
    return [
        MediaObservation(attachment_id=p.attachment_id, kind="image", vision=vision) for p in photos
    ]


async def _save(deps: AgentDeps, attachment_id: str, analysis: dict[str, Any]) -> None:
    """The cache only saves a repeat call; losing it must not lose the analysis."""
    assert deps.media is not None
    try:
        await deps.media.save_analysis(attachment_id, analysis)
    except Exception as exc:
        log.warning("media_cache_failed", attachment_id=attachment_id, error=str(exc))


async def _video(deps: AgentDeps, video: LoadedMedia) -> MediaObservation:
    def failed(error: str) -> MediaObservation:
        return MediaObservation(attachment_id=video.attachment_id, kind="video", error=error)  # type: ignore[arg-type]

    assert deps.media is not None
    cached = (video.analysis or {}).get("video")
    if cached is not None:
        try:
            result = VideoResult.model_validate(cached)
            return MediaObservation(attachment_id=video.attachment_id, kind="video", video=result)
        except ValidationError:
            pass  # saved under an older schema: analyze again
    if deps.video is None:
        return failed("unavailable")
    prompt = prompts.render("video", categories=CATEGORIES)
    try:
        async with asyncio.timeout(deps.video.timeout_s):
            data = await deps.media.read(video)
            result = await deps.video.analyze(data, video.mime, prompt)
    except TimeoutError:
        log.warning("video_timeout", attachment_id=video.attachment_id)
        return failed("timeout")
    except Exception as exc:  # VideoAnalysisError, storage errors: never fail the turn
        log.warning(
            "video_failed", attachment_id=video.attachment_id, error=f"{type(exc).__name__}: {exc}"
        )
        return failed("analysis_failed")
    await _save(deps, video.attachment_id, {"video": result.model_dump(mode="json")})
    return MediaObservation(attachment_id=video.attachment_id, kind="video", video=result)


async def perceive(
    state: GraphState, deps: AgentDeps, emit: Callable[[AgentEvent], None]
) -> dict[str, Any]:
    message = state.turn.message
    assert message is not None
    if not message.attachments:
        return {}
    if deps.media is None:
        observations = [
            MediaObservation(attachment_id=a, kind="image", error="unavailable")
            for a in message.attachments
        ]
        return {"turn": state.turn.model_copy(update={"media": observations})}

    try:
        loaded = await deps.media.load(message.attachments, message.user_id)
    except Exception as exc:
        log.warning("media_load_failed", error=f"{type(exc).__name__}: {exc}")
        observations = [
            MediaObservation(attachment_id=a, kind="image", error="unavailable")
            for a in message.attachments
        ]
        return {"turn": state.turn.model_copy(update={"media": observations})}
    if len(loaded) < len(message.attachments):
        log.warning("media_not_loaded", requested=len(message.attachments), loaded=len(loaded))
    photos = [m for m in loaded if m.kind == "image"]
    videos = [m for m in loaded if m.kind == "video"]
    if videos:
        emit(StatusEvent(stage="analyzing_media", label="Watching your video… (up to a minute)"))
    elif photos:
        emit(StatusEvent(stage="analyzing_media", label="Looking at your photo…"))
    jobs = [_photos(deps, photos)] if photos else []
    results = await asyncio.gather(*jobs, *(_one(deps, v) for v in videos))
    observations = [o for result in results for o in result]
    return {"turn": state.turn.model_copy(update={"media": observations})}


async def _one(deps: AgentDeps, video: LoadedMedia) -> list[MediaObservation]:
    return [await _video(deps, video)]
