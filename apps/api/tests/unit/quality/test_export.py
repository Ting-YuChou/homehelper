"""Turning an annotated reply into a regression case (spec §17.2, M7-02)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import yaml

from homehelper.db.models import Annotation, Attachment, Conversation, Message, User
from homehelper.quality.export import ExportChoices, ExportError, build_case, suggest
from homehelper.quality.regression import RegressionAssertions, RegressionCase, case_yaml

T0 = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
EXPORTED = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def message(n: int, role: str, content: str = "", **fields: Any) -> Message:
    return Message(
        id=f"msg_{n}",
        conversation_id="conv_1",
        role=role,
        content=content,
        cards=[],
        citations=[],
        created_at=T0 + timedelta(seconds=n),
        **fields,
    )


CONVERSATION = Conversation(id="conv_1", user_id="demo_alex", release_id="r1")
DEMO = User(id="demo_alex", display_name="Alex", is_demo=True)
GUEST = User(id="guest_1", display_name="Guest", is_demo=False)
MESSAGES = [
    message(1, "user", "My dishwasher won't drain"),
    message(2, "assistant", "Check the filter."),
    message(3, "user", action={"type": "step_result", "value": "not_fixed"}),
    message(4, "assistant", "Do A, then B, then C."),
    message(5, "user", "ok"),
    message(6, "assistant", "Anything else?"),
]


def annotation(**fields: Any) -> Annotation:
    values: dict[str, Any] = {
        "id": "ann_0123456789abcdef",
        "message_id": "msg_4",
        "verdict": "incorrect",
        "issue_types": ["too_many_steps_at_once"],
        "expected_response": "One step at a time.",
        "notes": "Dumped three steps",
        **fields,
    }
    return Annotation(**values)


def build(**overrides: Any):
    values: dict[str, Any] = {
        "conversation": CONVERSATION,
        "user": DEMO,
        "messages": MESSAGES,
        "attachments": {},
        "annotation": annotation(),
        "choices": suggest(["too_many_steps_at_once"], "One step at a time."),
        "exported_at": EXPORTED,
        **overrides,
    }
    return build_case(**values)


class TestSuggest:
    def test_too_many_steps(self) -> None:
        choices = suggest(["too_many_steps_at_once"], "One step at a time.")
        assert choices.assertions.max_step_cards_per_reply == 1
        assert choices.assertions.expected_behavior == "One step at a time."
        assert choices.expected_outcomes == []

    def test_unsafe_forbids_steps_and_has_a_default_expectation(self) -> None:
        choices = suggest(["unsafe"], None)
        assert choices.assertions.forbid_step_cards
        assert "technician" in (choices.assertions.expected_behavior or "")

    def test_missed_escalation_expects_an_escalation(self) -> None:
        choices = suggest(["missed_escalation"], "  ")
        assert choices.expected_outcomes == ["escalated"]
        assert choices.assertions.forbid_step_cards
        assert choices.assertions.expected_behavior

    @pytest.mark.parametrize(
        "issue", ["wrong_diagnosis", "tone", "other", "hallucination", "wrong_manual"]
    )
    def test_other_issues_use_the_reviewers_words(self, issue: str) -> None:
        assert suggest([issue], "Ask for the model.").assertions.expected_behavior == (
            "Ask for the model."
        )
        assert suggest([issue], None).assertions.expected_behavior is None


class TestBuildCase:
    def test_the_prefix_is_every_user_turn_before_the_annotated_reply(self) -> None:
        exported = build()
        case = exported.case
        assert [(t.text, t.action and t.action.value) for t in case.user_turns] == [
            ("My dishwasher won't drain", None),
            ("", "not_fixed"),
        ]
        assert case.id == "reg-20261023-01234567"
        assert case.user_id == "demo_alex"
        assert case.assertions.max_step_cards_per_reply == 1
        assert case.notes == "Dumped three steps"
        assert case.source.message_id == "msg_4" and case.source.release_id == "r1"
        assert case.source.issue_types == ["too_many_steps_at_once"]
        assert case.source.exported_at == EXPORTED
        assert "My dishwasher won't drain" in case.scenario
        assert exported.media_sources == {}

    def test_guests_replay_as_guests(self) -> None:
        assert build(user=GUEST).case.user_id is None

    def test_attachments_become_case_media(self) -> None:
        photo = Attachment(id="att_1", kind="image", mime="image/jpeg", storage_uri="local://a")
        clip = Attachment(id="att_2", kind="video", mime="video/mp4", storage_uri="local://b")
        exported = build(attachments={"msg_1": [photo], "msg_3": [clip]})
        assert [(m.turn, m.path) for m in exported.case.media] == [
            (0, "regression/reg-20261023-01234567/0-1.jpg"),
            (1, "regression/reg-20261023-01234567/1-1.mp4"),
        ]
        assert exported.media_sources == {
            "regression/reg-20261023-01234567/0-1.jpg": "att_1",
            "regression/reg-20261023-01234567/1-1.mp4": "att_2",
        }

    def test_a_photo_only_message_replays(self) -> None:
        photo = Attachment(id="att_1", kind="image", mime="image/png", storage_uri="local://a")
        messages = [message(1, "user", ""), message(2, "assistant", "I see a washer.")]
        exported = build(
            messages=messages,
            attachments={"msg_1": [photo]},
            annotation=annotation(message_id="msg_2"),
        )
        assert exported.case.user_turns[0].text == "" and exported.case.media[0].turn == 0

    def test_the_annotated_message_must_be_a_reply_in_this_conversation(self) -> None:
        with pytest.raises(ExportError, match="not in this conversation"):
            build(annotation=annotation(message_id="msg_99"))
        with pytest.raises(ExportError, match="no user message"):
            build(
                messages=[message(2, "assistant", "Hi")], annotation=annotation(message_id="msg_2")
            )

    def test_too_long_to_replay(self) -> None:
        long = [message(n, "user" if n % 2 else "assistant", f"m{n}") for n in range(1, 30)]
        with pytest.raises(ExportError, match="13 user turns"):
            build(messages=long, annotation=annotation(message_id="msg_26"))

    def test_something_must_be_checked(self) -> None:
        nothing = ExportChoices(expected_outcomes=[], assertions=RegressionAssertions())
        with pytest.raises(ExportError, match="nothing to check"):
            build(choices=nothing)
        only_doc = ExportChoices(
            expected_outcomes=[],
            expected_doc_id="bosch-shx68t55",
            assertions=RegressionAssertions(),
        )
        assert build(choices=only_doc).case.expected_doc_id == "bosch-shx68t55"


def test_case_yaml_round_trips_and_leaves_out_defaults() -> None:
    case = build().case
    text = case_yaml(case)
    data = yaml.safe_load(text)
    assert data["id"] == case.id and "kind" not in data and "stop_after_script" not in data
    assert RegressionCase.model_validate(data) == case
    assert text.startswith("# Regression case exported from annotation ann_0123456789abcdef")
