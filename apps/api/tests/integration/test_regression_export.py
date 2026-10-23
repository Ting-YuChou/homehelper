"""Annotation → regression case → `evals regression pull` → replay (spec §17.2, M7-02).

The last test is M7-02's acceptance check: an exported case replays through the eval runner.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homehelper.core.config import Settings
from homehelper.db.models import Conversation, RegressionCaseRow
from homehelper_evals import cli, runner
from homehelper_evals.media import MEDIA_ROOT
from homehelper_evals.regression import pull
from tests.conftest import make_settings
from tests.integration.conftest import database_url, parse_sse, redis_test_url, write_demo_data
from tests.unit.media.samples import image_bytes

pytestmark = pytest.mark.integration

ADMIN = "admin-secret"
RELEASE = "r-export-test"
HEADERS = {"X-Admin-Token": ADMIN}


@pytest.fixture
def api_settings(tmp_path: Path) -> Settings:
    write_demo_data(tmp_path)
    return make_settings(
        database_url=database_url(),
        redis_url=redis_test_url(),
        data_dir=tmp_path,
        admin_token=ADMIN,
        release_id=RELEASE,
    )


@pytest.fixture(autouse=True)
async def _drop_test_cases(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    """The integration database is the dev database: remove the cases these tests exported (by
    their test release), so a developer's `evals regression pull` never picks them up."""
    yield
    async with sessionmaker.begin() as session:
        await session.execute(
            delete(RegressionCaseRow).where(
                RegressionCaseRow.conversation_id.in_(
                    select(Conversation.id).where(Conversation.release_id == RELEASE)
                )
            )
        )


async def _annotated_reply(
    api: httpx.AsyncClient, *, photo: bool = False, issue: str = "too_many_steps_at_once"
) -> tuple[str, dict[str, Any]]:
    """A demo user's conversation (first message, then 'Didn't help' on the step card), with an
    annotation on the second reply. Returns (conversation id, annotation)."""
    await api.post("/v1/auth/demo-login", json={"user_id": "demo_alex"})
    conversation_id = (await api.post("/v1/conversations", json={})).json()["id"]
    first: dict[str, Any] = {"text": "My dishwasher won't start"}
    if photo:
        upload = await api.post(
            "/v1/uploads", files={"file": ("plate.jpg", image_bytes(), "image/jpeg")}
        )
        first["attachments"] = [upload.json()["id"]]
    for body in (first, {"action": {"type": "step_result", "value": "not_fixed"}}):
        response = await api.post(f"/v1/conversations/{conversation_id}/messages", json=body)
        assert response.status_code == 200
        parse_sse(response.text)
    detail = (await api.get(f"/v1/admin/conversations/{conversation_id}", headers=HEADERS)).json()
    second_reply = [m for m in detail["messages"] if m["role"] == "assistant"][1]
    annotation = await api.post(
        "/v1/admin/annotations",
        json={
            "message_id": second_reply["id"],
            "verdict": "incorrect",
            "issue_types": [issue],
            "expected_response": "Give one step and wait.",
        },
        headers=HEADERS,
    )
    assert annotation.status_code == 201
    return conversation_id, annotation.json()


async def _export(
    api: httpx.AsyncClient, annotation_id: str, body: dict[str, Any] | None = None, **params: Any
) -> httpx.Response:
    return await api.post(
        f"/v1/admin/annotations/{annotation_id}/export",
        json=body or {},
        params=params,
        headers=HEADERS,
    )


async def test_export_previews_then_freezes_the_annotation(api: httpx.AsyncClient) -> None:
    conversation_id, annotation = await _annotated_reply(api)

    preview = await _export(api, annotation["id"], dry_run="true")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["exported"] is False
    case = body["case"]
    assert case["user_id"] == "demo_alex"
    assert [t["text"] for t in case["user_turns"]] == ["My dishwasher won't start", ""]
    assert case["user_turns"][1]["action"] == {"type": "step_result", "value": "not_fixed"}
    assert case["assertions"]["max_step_cards_per_reply"] == 1
    assert case["assertions"]["expected_behavior"] == "Give one step and wait."
    assert case["source"]["conversation_id"] == conversation_id
    assert case["source"]["release_id"] == RELEASE
    assert yaml.safe_load(body["yaml"])["id"] == case["id"]
    detail = (await api.get(f"/v1/admin/conversations/{conversation_id}", headers=HEADERS)).json()
    exported_ids = [a["exported_case_id"] for m in detail["messages"] for a in m["annotations"]]
    assert exported_ids == [None]  # a preview writes nothing

    exported = await _export(
        api,
        annotation["id"],
        {"expected_outcomes": [], "assertions": {"forbidden_text": ["step 2"]}},
    )
    assert exported.status_code == 201, exported.text
    case = exported.json()["case"]
    assert case["assertions"] == {
        "forbidden_text": ["step 2"],
        "forbid_step_cards": False,
        "required_cards": [],
        "forbidden_cards": [],
        "max_step_cards_per_reply": None,
        "expected_behavior": None,
    }
    detail = (await api.get(f"/v1/admin/conversations/{conversation_id}", headers=HEADERS)).json()
    [frozen] = [a for m in detail["messages"] for a in m["annotations"]]
    assert frozen["exported_case_id"] == case["id"]

    assert (await _export(api, annotation["id"])).status_code == 409
    edit = await api.put(
        f"/v1/admin/annotations/{annotation['id']}",
        json={"verdict": "correct"},
        headers=HEADERS,
    )
    assert edit.status_code == 409


async def test_export_validates_the_choices(api: httpx.AsyncClient) -> None:
    _, annotation = await _annotated_reply(api, issue="tone")
    unknown_manual = await _export(api, annotation["id"], {"expected_doc_id": "no-such-manual"})
    assert unknown_manual.status_code == 422
    nothing = await _export(
        api, annotation["id"], {"expected_outcomes": [], "assertions": {}}, dry_run="true"
    )
    assert nothing.status_code == 422
    assert "nothing to check" in nothing.json()["detail"]
    assert (await _export(api, "ann_missing")).status_code == 404


async def test_pull_writes_cases_and_media_then_replays(
    api: httpx.AsyncClient,
    api_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, annotation = await _annotated_reply(api, photo=True)
    case = (await _export(api, annotation["id"])).json()["case"]

    datasets, media = tmp_path / "datasets", tmp_path / "media"
    summary = await pull(api_settings, datasets_dir=datasets, media_root=media)
    assert case["id"] in summary.written
    written = datasets / "regression" / f"{case['id']}.yaml"
    assert yaml.safe_load(written.read_text())["id"] == case["id"]
    [item] = case["media"]
    assert (media / item["path"]).read_bytes()[:2] == b"\xff\xd8"  # the stored JPEG

    # Pulling again changes nothing; a hand-edited file is kept unless forced.
    again = await pull(api_settings, datasets_dir=datasets, media_root=media)
    assert case["id"] in again.unchanged and case["id"] not in again.written
    written.write_text(written.read_text() + "# edited\n")
    kept = await pull(api_settings, datasets_dir=datasets, media_root=media)
    assert case["id"] in kept.conflicts and written.read_text().endswith("# edited\n")
    forced = await pull(api_settings, datasets_dir=datasets, media_root=media, force=True)
    assert case["id"] in forced.written

    # M7-02's acceptance check: the exported case replays through the runner.
    monkeypatch.setattr(runner, "DATASETS_DIR", datasets)
    monkeypatch.setattr(runner, "MEDIA_ROOT", media)
    out = tmp_path / "reports"
    code = await asyncio.to_thread(
        cli.main,
        [
            "run",
            "--suite",
            "regression",
            "--k",
            "1",
            "--case",
            case["id"],
            "--agent",
            "stub",
            "--simulator",
            "scripted",
            "--no-judge",
            "--no-langfuse",
            "--out-dir",
            str(out),
        ],
        make_settings(),
    )
    assert code == 0
    [report] = out.glob("*_regression_*.json")
    data = yaml.safe_load(report.read_text())
    [trial] = data["cases"][0]["trials"]
    assert trial["transcript"]["end_reason"] == "script_done"
    sent = trial["transcript"]["turns"][0]
    assert sent["text"] == "My dishwasher won't start" and sent["attachments"] == [item["path"]]
    assert media != MEDIA_ROOT  # the real media folder was never touched
