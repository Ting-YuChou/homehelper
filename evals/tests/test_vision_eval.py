"""Vision accuracy eval (M6-04): dataset, grading, calibration, and a run with a fake model."""

import json
from pathlib import Path

import pytest

from homehelper.llm import FakeLLMClient, LLMError
from homehelper.media.schemas import VisionResult
from homehelper_evals.vision import (
    VisionCase,
    grade,
    load_cases,
    main,
    run,
    summarize,
)
from homehelper_evals.vision_media import render_case


def _case(**fields: object) -> VisionCase:
    return VisionCase.model_validate(
        {
            "id": "c1",
            "image": "synthetic/c1.png",
            "source": {
                "kind": "synthetic",
                "template": "nameplate",
                "params": {
                    "brand": "LG",
                    "model_number": "WM4000HWA",
                    "category": "washing_machine",
                },
            },
            "expect": {"category": "washing_machine", "brand": "LG", "model_number": "WM4000HWA"},
            **fields,
        }
    )


def _result(confidence: float = 0.9, **fields: object) -> VisionResult:
    return VisionResult.model_validate({"confidence": confidence, **fields})


def test_dataset_loads() -> None:
    cases = load_cases()
    assert len(cases) >= 15
    assert len({c.id for c in cases}) == len(cases)
    assert any(c.expect.category is None for c in cases), "needs images that show no appliance"
    assert any(c.expect.displayed_error_code for c in cases)
    assert any(c.difficulty == "hard" for c in cases)


def test_grading_normalizes_fields() -> None:
    graded = grade(
        _case(),
        _result(category="Washing Machine", brand="lg", model_number="wm-4000 hwa"),
    )
    assert graded["fields"] == {"category": True, "brand": True, "model_number": True}
    assert graded["identified"] is True
    assert graded["identity_wrong"] is False


def test_a_wrong_model_number_is_an_identity_error() -> None:
    graded = grade(_case(), _result(category="washing_machine", brand="LG", model_number="WM3400"))
    assert graded["fields"]["model_number"] is False
    assert graded["identity_wrong"] is True


def test_abstaining_is_right_when_nothing_is_there() -> None:
    blank = _case(expect={"category": None, "brand": None, "model_number": None})
    assert grade(blank, _result(0.1))["fields"] == {
        "category": True,
        "brand": True,
        "model_number": True,
    }
    assert grade(blank, _result(0.8, category="dryer"))["fields"]["category"] is False


def test_unset_fields_are_not_graded() -> None:
    display = _case(expect={"displayed_error_code": "OE"})
    graded = grade(display, _result(displayed_error_code="oe"))
    assert graded["fields"] == {"displayed_error_code": True}
    assert graded["identity_wrong"] is None  # nothing about identity was graded


def test_issue_keywords_and_hazards() -> None:
    case = _case(expect={"issue_keywords": ["gasket", "mold"], "hazards": ["smoke_or_burning"]})
    graded = grade(
        case,
        _result(visible_issues=["Torn door gasket"], hazard_signals=["smoke_or_burning", "sparks"]),
    )
    assert graded["issue_recall"] == 0.5
    assert graded["hazards"] == {"missed": [], "extra": ["sparks"]}


def _row(confidence: float, wrong: bool | None) -> dict[str, object]:
    return {
        "id": "x",
        "confidence": confidence,
        "grade": {
            "fields": {"brand": not wrong} if wrong is not None else {},
            "identifiable": wrong is not None,
            "identified": wrong is False,
            "identity_wrong": wrong,
            "issue_recall": None,
            "hazards": None,
        },
    }


def test_calibration_shows_what_the_confirm_step_catches() -> None:
    rows = [
        _row(0.95, None),  # an empty photo: not part of calibration
        _row(0.95, False),
        _row(0.9, False),
        _row(0.85, True),  # a silent error: confident and wrong
        _row(0.5, True),  # caught: wrong but asked
        _row(0.4, True),  # caught
        _row(0.6, False),  # asked though right
    ]
    summary = summarize(rows)
    calibration = summary["calibration"]
    assert calibration["catch_rate"] == round(2 / 3, 3)
    assert calibration["silent_error_rate"] == round(1 / 3, 3)
    assert calibration["confirm_rate"] == 0.5
    assert 0 <= calibration["ece"] <= 1
    sweep = {point["threshold"]: point for point in calibration["sweep"]}
    assert sweep[0.9]["silent_error_rate"] == 0.0
    assert sweep[0.5]["confirm_rate"] == round(1 / 6, 3)


async def test_run_with_a_fake_model(tmp_path: Path) -> None:
    case = _case()
    render_case(case, tmp_path)
    llm = FakeLLMClient(
        {"vision": [_result(category="washing_machine", brand="LG", model_number="WM4000HWA")]}
    )
    [row] = await run([case], llm, media_dir=tmp_path)
    assert row["grade"]["identified"] is True
    [call] = llm.calls_for("vision")
    parts = call.messages[0].content
    assert isinstance(parts, list)
    assert any(p["type"] == "image_url" for p in parts)


async def test_missing_images_are_reported_not_graded(tmp_path: Path) -> None:
    [row] = await run([_case()], FakeLLMClient(), media_dir=tmp_path)
    assert row["error"] == "missing_media"
    assert summarize([row])["missing_media"] == 1
    assert summarize([row])["cases"] == 0


async def test_a_failed_call_counts_as_wrong(tmp_path: Path) -> None:
    case = _case()
    render_case(case, tmp_path)
    [row] = await run([case], FakeLLMClient({"vision": [LLMError("down")]}), media_dir=tmp_path)
    assert row["error"].startswith("LLMError")
    assert row["grade"]["identity_wrong"] is True


def test_main_writes_a_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case()
    render_case(case, tmp_path)

    async def fake_run(cases, llm, media_dir, concurrency=4):
        return [
            {
                "id": case.id,
                "confidence": 0.9,
                "grade": grade(
                    case, _result(category="washing_machine", brand="LG", model_number="WM4000HWA")
                ),
            }
        ]

    monkeypatch.setattr("homehelper_evals.vision.run", fake_run)
    monkeypatch.setattr("homehelper_evals.vision.load_cases", lambda: [case])
    out = tmp_path / "vision.json"
    assert main(["--out", str(out), "--media-dir", str(tmp_path)]) == 0
    report = json.loads(out.read_text())
    assert report["summary"]["identification_rate"] == 1.0


def test_failed_calls_are_kept_out_of_calibration() -> None:
    failed = {**_row(0.0, True), "error": "LLMError: down"}
    summary = summarize([_row(0.9, False), _row(0.95, True), failed])
    calibration = summary["calibration"]
    assert calibration["graded"] == 2
    assert calibration["catch_rate"] == 0.0  # the one real error was confident
    assert summary["errors"] == 1
