"""What the photos and videos of a turn add to it (spec §11.2): slot values with the model's
confidence, hazards seen in them, and which analyses failed. Pure, like the rest of the engine.

The appliance's identity reaches the journey only through these slots, never through NLU, so a
photo can't turn into a `source="user"` value that skips the confirm step.
"""

from typing import Literal

from pydantic import BaseModel, Field

from homehelper.agent.state import HazardSignal
from homehelper.knowledge.model_numbers import normalize_error_code, normalize_model
from homehelper.media.schemas import MediaObservation, VideoResult, VisionResult
from homehelper.media.validation import MediaKind

MAX_SYMPTOM_ISSUES = 3
# Slots below this need the user's confirmation unless already confirmed (spec §11.2). Defined
# here, the lowest engine module that needs it; `predicates` re-exports it.
LOW_CONFIDENCE = 0.7
# The model's confidence is about the appliance's identity. A legible error code or a visible
# problem doesn't get less true because the nameplate is unreadable, so those are not held back
# for confirmation (which only troubleshooting has).
IDENTITY_SLOTS = frozenset({"appliance_category", "brand", "model_number"})


MIN_UNDERSTOOD = 0.3  # below this the model barely understood the photo: no floor


def _confidence(name: str, confidence: float) -> float:
    if name in IDENTITY_SLOTS or confidence < MIN_UNDERSTOOD:
        return confidence
    return max(confidence, LOW_CONFIDENCE)


class PerceivedSlot(BaseModel):
    name: str
    value: str
    source: Literal["vision", "video"]
    confidence: float = Field(ge=0, le=1)


class MediaInput(BaseModel):
    slot_updates: list[PerceivedSlot] = Field(default_factory=list)
    failures: list[MediaKind] = Field(default_factory=list)
    hazard_signals: list[HazardSignal] = Field(default_factory=list)
    analyzed: int = 0  # attachments with a usable analysis


def _vision_slots(result: VisionResult) -> list[PerceivedSlot]:
    issues = [i.strip() for i in result.visible_issues if i.strip()][:MAX_SYMPTOM_ISSUES]
    values = {
        "appliance_category": result.category.strip() if result.category else None,
        "brand": result.brand,
        "model_number": normalize_model(result.model_number) if result.model_number else None,
        "error_code": (
            normalize_error_code(result.displayed_error_code)
            if result.displayed_error_code
            else None
        ),
        "symptom": "; ".join(issues) if issues else None,
    }
    return [
        PerceivedSlot(
            name=name,
            value=value,
            source="vision",
            confidence=_confidence(name, result.confidence),
        )
        for name, value in values.items()
        if value
    ]


def _video_slots(result: VideoResult) -> list[PerceivedSlot]:
    codes = [c for c in result.visible_error_codes if c.strip()]
    values = {
        "appliance_category": result.category.strip() if result.category else None,
        "brand": result.brand.strip() if result.brand else None,
        "error_code": normalize_error_code(codes[0]) if codes else None,
        "symptom": result.symptom_description.strip() if result.symptom_description else None,
    }
    return [
        PerceivedSlot(
            name=name,
            value=value,
            source="video",
            confidence=_confidence(name, result.confidence),
        )
        for name, value in values.items()
        if value
    ]


def media_input(observations: list[MediaObservation]) -> MediaInput | None:
    if not observations:
        return None
    media = MediaInput()
    results: list[VisionResult] = []  # one vision answer covers all the photos of a message
    for observation in observations:
        if observation.video is not None:
            media.analyzed += 1
            media.slot_updates.extend(_video_slots(observation.video))
            for hazard in observation.video.hazard_signals:
                if hazard not in media.hazard_signals:
                    media.hazard_signals.append(hazard)
            continue
        if observation.error is not None or observation.vision is None:
            if observation.kind not in media.failures:
                media.failures.append(observation.kind)
            continue
        media.analyzed += 1
        if observation.vision in results:
            continue
        results.append(observation.vision)
        media.slot_updates.extend(_vision_slots(observation.vision))
        for hazard in observation.vision.hazard_signals:
            if hazard not in media.hazard_signals:
                media.hazard_signals.append(hazard)
    return media
