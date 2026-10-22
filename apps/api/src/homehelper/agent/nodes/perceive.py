"""`perceive` (M6-02, spec §11.2): what the message's photos show, before NLU reads its words.

All photos of a message go to the vision model in one call. The answer is cached on the
attachments, so a retried turn reuses it. A failed analysis is recorded, not raised: the engine
answers with M-MEDIA-01 and the conversation goes on.
"""

import base64
from collections.abc import Callable
from typing import Any

from homehelper.agent import prompts
from homehelper.agent.deps import AgentDeps
from homehelper.agent.nodes.understand import MEDIA_ONLY_TEXT
from homehelper.agent.turn import GraphState
from homehelper.channels.events import AgentEvent, StatusEvent
from homehelper.core.logging import get_logger
from homehelper.knowledge.schemas import CategoryId
from homehelper.llm import LLMClient, LLMError, Message
from homehelper.media.schemas import MediaObservation, VisionResult
from homehelper.media.source import LoadedMedia

log = get_logger(__name__)
__all__ = ["MEDIA_ONLY_TEXT", "analyze_images", "perceive", "vision_messages"]

CATEGORIES = [category.value for category in CategoryId]


def vision_messages(images: list[tuple[str, bytes]]) -> list[Message]:
    """One user message: the instructions, then each photo as a data URL (`mime`, bytes)."""
    text = prompts.render("vision", count=len(images), categories=CATEGORIES)
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for mime, data in images:
        url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return [Message(role="user", content=parts)]


async def analyze_images(llm: LLMClient, images: list[tuple[str, bytes]]) -> VisionResult:
    return await llm.structured("vision", vision_messages(images), VisionResult)


def _cached(photos: list[LoadedMedia]) -> VisionResult | None:
    """The saved answer, if it was for exactly these photos."""
    ids = [p.attachment_id for p in photos]
    analyses = [p.analysis or {} for p in photos]
    if all(a.get("photos") == ids and "vision" in a for a in analyses):
        return VisionResult.model_validate(analyses[0]["vision"])
    return None


async def _photos(deps: AgentDeps, photos: list[LoadedMedia]) -> list[MediaObservation]:
    assert deps.media is not None
    vision = _cached(photos)
    if vision is None:
        try:
            images = [(p.mime, await deps.media.read(p)) for p in photos]
            vision = await analyze_images(deps.llm, images)
        except (LLMError, OSError) as exc:
            log.warning("vision_failed", error=str(exc), photos=len(photos))
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
            await deps.media.save_analysis(photo.attachment_id, analysis)
    return [
        MediaObservation(attachment_id=p.attachment_id, kind="image", vision=vision) for p in photos
    ]


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

    loaded = await deps.media.load(message.attachments, message.user_id)
    if len(loaded) < len(message.attachments):
        log.warning("media_not_loaded", requested=len(message.attachments), loaded=len(loaded))
    observations: list[MediaObservation] = []
    if loaded:
        emit(StatusEvent(stage="analyzing_media", label="Looking at what you sent…"))
    photos = [m for m in loaded if m.kind == "image"]
    if photos:
        observations.extend(await _photos(deps, photos))
    for video in (m for m in loaded if m.kind == "video"):
        # Video understanding arrives with M6-03.
        observations.append(
            MediaObservation(attachment_id=video.attachment_id, kind="video", error="unavailable")
        )
    return {"turn": state.turn.model_copy(update={"media": observations})}
