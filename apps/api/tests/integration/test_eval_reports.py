"""Eval reports in the database and `/v1/admin/evals` (spec §15.2, §16.4, M7-04)."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from homehelper.core.config import Settings
from homehelper.db.models import EvalReportRow, Release
from homehelper_evals import cli
from homehelper_evals.publish import publish_reports
from tests.conftest import make_settings
from tests.integration.conftest import database_url, redis_test_url, write_demo_data

pytestmark = pytest.mark.integration

ADMIN = "admin-secret"
HEADERS = {"X-Admin-Token": ADMIN}
PREFIX = "r-evals-test"  # every release id here starts with it; cleaned up after each test


@pytest.fixture
def api_settings(tmp_path: Path) -> Settings:
    write_demo_data(tmp_path)
    return make_settings(
        database_url=database_url(),
        redis_url=redis_test_url(),
        data_dir=tmp_path,
        admin_token=ADMIN,
    )


@pytest.fixture(autouse=True)
async def _drop_test_rows(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    yield
    async with sessionmaker.begin() as session:
        await session.execute(
            delete(EvalReportRow).where(EvalReportRow.release_id.startswith(PREFIX))
        )
        await session.execute(delete(Release).where(Release.id.startswith(PREFIX)))


def _reports(folder: Path, suite: str) -> list[Path]:
    return list(folder.glob(f"*_{suite}_*.json"))


def write_report(folder: Path, release: str, suite: str, stamp: str, **extra: Any) -> Path:
    config = {
        "k": 4,
        "agent": "homehelper_evals.builders:journey",
        "simulator": "llm (anthropic/claude-haiku-5-5)",
        "judge": "anthropic/claude-sonnet-5-5",
        "limit": None,
        "strict_judge": True,
        **extra.pop("config", {}),
    }
    report = {
        "report_type": "conversation_simulation",
        "schema_version": 1,
        "release": release,
        "suite": suite,
        "created_at": f"2026-10-{stamp}T08:00:00+00:00",
        "git_sha": "abc1234",
        "config": config,
        "metrics": {"resolution_rate": 0.6, "safety_pass_rate": 1.0, **extra.pop("metrics", {})},
        "cases": [],
        **extra,
    }
    path = folder / f"{release}_{suite}_202610{stamp}T080000Z.json"
    path.write_text(json.dumps(report))
    return path


async def test_publishing_is_idempotent_and_skips_other_reports(
    api_settings: Settings, tmp_path: Path
) -> None:
    first = write_report(tmp_path, f"{PREFIX}-a", "full", "20")
    other = tmp_path / "retrieval_kb.json"
    other.write_text(json.dumps({"kb_version": "kb_20261001_01"}))
    published, skipped = await publish_reports(api_settings, [tmp_path])
    assert published == [first.stem] and skipped == [other]
    published, _ = await publish_reports(api_settings, [first])
    assert published == [first.stem]


async def test_admin_lists_reports_with_trends_metadata(
    api: httpx.AsyncClient,
    api_settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with sessionmaker.begin() as session:
        session.add(Release(id=f"{PREFIX}-a", git_sha="abc1234", kb_version="kb_20261001_01"))
    write_report(tmp_path, f"{PREFIX}-a", "full", "20")
    write_report(tmp_path, f"{PREFIX}-b", "full", "21", metrics={"resolution_rate": 0.7})
    write_report(tmp_path, f"{PREFIX}-b", "safety", "21", config={"judge": None})
    await publish_reports(api_settings, [tmp_path])

    response = await api.get("/v1/admin/evals", params={"suite": "full"}, headers=HEADERS)
    assert response.status_code == 200, response.text
    rows = [r for r in response.json() if r["release_id"].startswith(PREFIX)]
    assert [r["release_id"] for r in rows] == [f"{PREFIX}-b", f"{PREFIX}-a"]  # newest first
    assert rows[0]["metrics"]["resolution_rate"] == 0.7
    assert rows[1]["kb_version"] == "kb_20261001_01" and rows[0]["kb_version"] is None
    assert rows[0]["weakened"] is None
    assert "cases" not in rows[0]

    safety = (
        await api.get(
            "/v1/admin/evals",
            params={"release_id": f"{PREFIX}-b", "suite": "safety"},
            headers=HEADERS,
        )
    ).json()
    assert [r["suite"] for r in safety] == ["safety"]
    assert safety[0]["weakened"] == "was run without a judge (--no-judge)"

    detail = await api.get(f"/v1/admin/evals/{rows[0]['id']}", headers=HEADERS)
    assert detail.status_code == 200 and detail.json()["cases"] == []
    assert (await api.get("/v1/admin/evals/nope", headers=HEADERS)).status_code == 404
    assert (await api.get("/v1/admin/evals")).status_code == 401


async def test_evals_run_records_its_report(
    api: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(database_url=database_url())
    code = await asyncio.to_thread(
        cli.main,
        [
            "run",
            "--suite",
            "smoke",
            "--limit",
            "2",
            "--release",
            f"{PREFIX}-run",
            "--simulator",
            "scripted",
            "--no-judge",
            "--no-langfuse",
            "--record",
            "--out-dir",
            str(tmp_path),
        ],
        settings,
    )
    assert code == 0
    [path] = _reports(tmp_path, "smoke")
    detail = (await api.get(f"/v1/admin/evals/{path.stem}", headers=HEADERS)).json()
    assert detail["suite"] == "smoke" and len(detail["cases"]) == 2
    assert detail["weakened"] == "was run without a judge (--no-judge)"
