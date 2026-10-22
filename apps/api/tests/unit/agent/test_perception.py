"""What a photo adds to a turn (M6-02, spec §11.2): pure mapping from vision results to slots."""

from homehelper.agent.engine.perception import PerceivedSlot, media_input
from homehelper.media.schemas import MediaObservation, VisionResult


def _photo(attachment_id: str = "att_1", **fields: object) -> MediaObservation:
    vision = VisionResult.model_validate({"confidence": 0.9, "visible_issues": [], **fields})
    return MediaObservation(attachment_id=attachment_id, kind="image", vision=vision)


def test_no_media_is_no_input() -> None:
    assert media_input([]) is None


def test_maps_the_appliance_fields_to_slots() -> None:
    result = media_input(
        [
            _photo(
                category="washing_machine",
                brand=" LG ",
                model_number="wm3400-cw",
                displayed_error_code="o e",
                confidence=0.82,
            )
        ]
    )
    assert result is not None
    assert result.slot_updates == [
        PerceivedSlot(
            name="appliance_category", value="washing_machine", source="vision", confidence=0.82
        ),
        PerceivedSlot(name="brand", value="LG", source="vision", confidence=0.82),
        PerceivedSlot(name="model_number", value="WM3400CW", source="vision", confidence=0.82),
        PerceivedSlot(name="error_code", value="OE", source="vision", confidence=0.82),
    ]
    assert result.failures == []
    assert result.analyzed == 1


def test_visible_issues_describe_the_symptom() -> None:
    result = media_input(
        [_photo(visible_issues=["torn door seal", "water pooling under the door", "rust", "dent"])]
    )
    assert result is not None
    [symptom] = result.slot_updates
    assert symptom.name == "symptom"
    assert symptom.value == "torn door seal; water pooling under the door; rust"


def test_empty_and_missing_fields_are_skipped() -> None:
    result = media_input([_photo(category=None, brand="  ", model_number="")])
    assert result is not None
    assert result.slot_updates == []


def test_failures_and_hazards_are_collected() -> None:
    failed = MediaObservation(attachment_id="att_2", kind="video", error="timeout")
    result = media_input([_photo(hazard_signals=["smoke_or_burning"], category="dryer"), failed])
    assert result is not None
    assert result.failures == ["video"]
    assert result.hazard_signals == ["smoke_or_burning"]
    assert result.analyzed == 1


def test_only_failures() -> None:
    result = media_input(
        [MediaObservation(attachment_id="att_1", kind="image", error="analysis_failed")]
    )
    assert result is not None
    assert (result.slot_updates, result.failures, result.analyzed) == ([], ["image"], 0)


def test_long_strings_from_the_model_are_cut() -> None:
    vision = VisionResult.model_validate(
        {"confidence": 0.9, "visible_issues": ["x" * 500] * 9, "brand": "B" * 300}
    )
    assert len(vision.visible_issues) <= 5
    assert all(len(issue) <= 120 for issue in vision.visible_issues)
    assert vision.brand is not None and len(vision.brand) <= 60
