"""The multimodal conversation suite (M6-04): cases with photos, sending them, grading cards."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from homehelper.agent.protocol import AgentSnapshot
from homehelper.channels.events import (
    AgentEvent,
    ApplianceConfirmCard,
    InboundMessage,
    MessageCompletedEvent,
    MessageDeltaEvent,
    StepCard,
)
from homehelper_evals.cases import EvalCase, load_dataset
from homehelper_evals.conversation import run_conversation
from homehelper_evals.graders.deterministic import card_check
from homehelper_evals.media import EvalMediaSource, missing_media
from homehelper_evals.runner import SUITES, build_cases
from homehelper_evals.simulator import ScriptedUserSimulator
from homehelper_evals.testing import make_case, make_transcript
from homehelper_evals.transcript import AgentTurn


def _case(**fields: object) -> EvalCase:
    base = {
        "id": "mm-1",
        "kind": "multimodal",
        "scenario": "The washer won't drain.",
        "expected_outcomes": ["resolved"],
        "user_turns": ["Here's my washer, it won't drain."],
        "media": [{"turn": 0, "path": "vision/synthetic/plate-lg-washer.png"}],
    }
    return EvalCase.model_validate({**base, **fields})


def test_media_must_ride_on_a_scripted_turn() -> None:
    with pytest.raises(ValidationError, match="media"):
        _case(media=[{"turn": 1, "path": "vision/x.png"}])


def test_the_dataset_loads_and_covers_the_cases_that_matter() -> None:
    cases = load_dataset("multimodal")
    assert len(cases) >= 6
    assert all(case.media for case in cases)
    assert any(
        "forbidden_text" in case.assertions.model_dump(exclude_defaults=True) for case in cases
    )
    assert any("appliance_confirm" in case.assertions.required_cards for case in cases)
    assert any(case.safety_expectation == "escalate" for case in cases)


def test_media_source_serves_files_by_path(tmp_path: Path) -> None:
    (tmp_path / "vision").mkdir()
    (tmp_path / "vision" / "a.png").write_bytes(b"\x89PNGdata")
    (tmp_path / "clip.mp4").write_bytes(b"video")
    source = EvalMediaSource(tmp_path)

    async def check() -> None:
        loaded = await source.load(["vision/a.png", "clip.mp4", "missing.png", "../etc"], None)
        assert [(m.attachment_id, m.kind, m.mime) for m in loaded] == [
            ("vision/a.png", "image", "image/png"),
            ("clip.mp4", "video", "video/mp4"),
        ]
        assert await source.read(loaded[0]) == b"\x89PNGdata"
        await source.save_analysis("vision/a.png", {"vision": {}})  # cached per conversation
        [again] = await source.load(["vision/a.png"], None)
        assert again.analysis == {"vision": {}}

    import asyncio

    asyncio.run(check())


def test_missing_media_is_found_before_running(tmp_path: Path) -> None:
    assert missing_media(_case(), tmp_path) == ["vision/synthetic/plate-lg-washer.png"]


def test_cases_with_missing_media_are_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("homehelper_evals.runner.MEDIA_ROOT", tmp_path)
    assert "multimodal" in SUITES
    skipped: list[str] = []
    assert build_cases(SUITES["multimodal"], skipped=skipped) == []
    assert "mm-sharp-nameplate" in skipped
    assert "skipped" in capsys.readouterr().err


def test_a_strict_suite_with_skipped_cases_has_no_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from homehelper_evals.cli import main

    monkeypatch.setattr("homehelper_evals.runner.MEDIA_ROOT", tmp_path)
    code = main(
        ["run", "--suite", "multimodal", "--simulator", "scripted", "--no-judge", "--agent", "echo"]
    )
    assert code != 0
    assert "missing media" in capsys.readouterr().err


class RecordingAgent:
    def __init__(self) -> None:
        self.messages: list[InboundMessage] = []

    async def handle(self, message: InboundMessage) -> AsyncIterator[AgentEvent]:
        self.messages.append(message)
        yield MessageDeltaEvent(message_id="m", text="Thanks.")
        yield MessageCompletedEvent(message_id="m")

    async def snapshot(self, conversation_id: str) -> AgentSnapshot:
        return AgentSnapshot(conversation_id=conversation_id)


async def test_the_photo_is_sent_with_its_turn() -> None:
    agent = RecordingAgent()
    case = _case(user_turns=["Here's my washer.", "It still won't drain."], max_turns=2)
    transcript = await run_conversation(case, agent, ScriptedUserSimulator())
    assert [m.attachments for m in agent.messages] == [
        ["vision/synthetic/plate-lg-washer.png"],
        [],
    ]
    assert transcript.user_turns[0].attachments == ["vision/synthetic/plate-lg-washer.png"]


def test_the_scripted_user_checks_the_model_number_too() -> None:
    case = make_case(category="washing_machine", brand="LG", model_number="WM4000HWA")
    simulator = ScriptedUserSimulator()
    wrong = AgentTurn(
        cards=[
            ApplianceConfirmCard(
                category="washing_machine", brand="LG", model_number="WM3400CW", confidence=0.5
            )
        ]
    )
    right = AgentTurn(
        cards=[
            ApplianceConfirmCard(
                category="washing_machine", brand="LG", model_number="WM-4000HWA", confidence=0.5
            )
        ]
    )

    import asyncio

    assert asyncio.run(simulator.next_turn(case, [wrong])).confirm_appliance == "no"
    assert asyncio.run(simulator.next_turn(case, [right])).confirm_appliance == "yes"


def test_required_and_forbidden_cards() -> None:
    case = _case(assertions={"required_cards": ["appliance_confirm"], "forbidden_cards": ["step"]})
    confirm = ApplianceConfirmCard(category="washing_machine", confidence=0.5)
    step = StepCard(plan_item_id="p1", index=1, total=2, instruction="Clean the filter.")
    ok = make_transcript(AgentTurn(cards=[confirm]))
    assert card_check(case, ok).passed is True
    missing = make_transcript(AgentTurn(text="Is it an LG?"))
    assert card_check(case, missing).passed is False
    stepped = make_transcript(AgentTurn(cards=[confirm]), AgentTurn(cards=[step]))
    assert card_check(case, stepped).passed is False
    assert card_check(make_case(), ok).passed is None  # nothing asserted


def test_video_eval_skips_without_a_key(capsys: pytest.CaptureFixture[str]) -> None:
    from homehelper.core.config import Settings
    from homehelper_evals.video import main

    assert main([], settings=Settings(_env_file=None, gemini_api_key="")) == 0  # type: ignore[call-arg]
    assert "GEMINI_API_KEY" in capsys.readouterr().err


def test_video_eval_grades_keywords() -> None:
    from homehelper.media.schemas import VideoResult
    from homehelper_evals.video import VideoCase, grade_video

    case = VideoCase.model_validate(
        {
            "id": "v1",
            "path": "home_issue.mp4",
            "expect": {"category": "microwave", "symptom_keywords": ["start", "button"]},
        }
    )
    result = VideoResult(
        category="microwave",
        symptom_description="It won't start when buttons are pressed",
        confidence=0.7,
    )
    graded = grade_video(case, result)
    assert graded["fields"] == {"category": True}
    assert graded["symptom_recall"] == 1.0
