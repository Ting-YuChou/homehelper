"""Video understanding on `evals/datasets/video.yaml` (M6-03/M6-04), with Gemini.

    uv run python -m homehelper_evals.video [--models evals/models/opencode-go.yaml]

Needs GEMINI_API_KEY (skips with a message otherwise). Each case sends one clip from
`data/media/` (git-ignored) through the real video prompt, under the `video` task's time budget
(60 s), and reports field accuracy, symptom/audio keyword recall, latency and cost.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from homehelper.agent import prompts
from homehelper.agent.nodes.perceive import CATEGORIES
from homehelper.core.config import Settings
from homehelper.llm import LLMUsage, ModelRegistry
from homehelper.media.gemini import GeminiVideoAnalyzer, build_video_analyzer
from homehelper.media.schemas import VideoResult
from homehelper_evals import DATASETS_DIR, REPORTS_DIR
from homehelper_evals.cli import load_model_overrides
from homehelper_evals.media import MEDIA_ROOT, TYPES

DATASET = DATASETS_DIR / "video.yaml"


class VideoExpect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = "unset"
    brand: str | None = "unset"
    error_codes: list[str] = Field(default_factory=list)
    symptom_keywords: list[str] = Field(default_factory=list)
    audio_keywords: list[str] = Field(default_factory=list)
    hazards: list[str] | None = None


class VideoCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    path: str  # under data/media/
    reviewed: bool = False  # labels checked by a person who watched and listened to the clip
    expect: VideoExpect
    notes: str | None = None


def load_cases(path: Path = DATASET) -> list[VideoCase]:
    return [VideoCase.model_validate(c) for c in yaml.safe_load(path.read_text())["cases"]]


def _recall(keywords: list[str], text: str) -> float | None:
    if not keywords:
        return None
    return round(sum(k.lower() in text.lower() for k in keywords) / len(keywords), 3)


def grade_video(case: VideoCase, result: VideoResult) -> dict[str, Any]:
    expect = case.expect
    fields = {
        name: (getattr(result, name) or "").lower() == (getattr(expect, name) or "").lower()
        for name in ("category", "brand")
        if getattr(expect, name) != "unset"
    }
    codes = {c.upper() for c in result.visible_error_codes}
    graded: dict[str, Any] = {
        "fields": fields,
        "error_codes": all(c.upper() in codes for c in expect.error_codes),
        "symptom_recall": _recall(expect.symptom_keywords, result.symptom_description or ""),
        "audio_recall": _recall(expect.audio_keywords, " ".join(result.audio_cues)),
    }
    if expect.hazards is not None:
        graded["hazards_exact"] = set(expect.hazards) == set(result.hazard_signals)
    return graded


async def run(cases: list[VideoCase], analyzer: GeminiVideoAnalyzer) -> list[dict[str, Any]]:
    prompt = prompts.render("video", categories=CATEGORIES)
    rows = []
    for case in cases:  # one at a time: each clip is a large upload
        path = MEDIA_ROOT / case.path
        row: dict[str, Any] = {"id": case.id, "reviewed": case.reviewed}
        if not path.is_file():
            rows.append({**row, "error": "missing_media"})
            continue
        started = time.perf_counter()
        try:
            async with asyncio.timeout(analyzer.timeout_s):
                result = await analyzer.analyze(
                    path.read_bytes(), TYPES[path.suffix.lower()][1], prompt
                )
        except Exception as exc:
            rows.append({**row, "error": f"{type(exc).__name__}: {exc}"})
            continue
        seconds = round(time.perf_counter() - started, 1)
        rows.append(
            {
                **row,
                "seconds": seconds,
                "within_budget": seconds <= analyzer.timeout_s,
                "result": result.model_dump(),
                "grade": grade_video(case, result),
            }
        )
    return rows


def main(argv: list[str] | None = None, *, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m homehelper_evals.video")
    parser.add_argument("--models", type=Path, help="model overrides YAML (as in `evals run`)")
    parser.add_argument("--out", type=Path, default=REPORTS_DIR / "video.json")
    args = parser.parse_args(argv)

    settings = settings or Settings()
    overrides = load_model_overrides(args.models) if args.models else {}
    registry = ModelRegistry.load(overrides=overrides)
    usage: list[LLMUsage] = []
    analyzer = build_video_analyzer(settings, registry, usage_sink=usage.append)
    if analyzer is None:
        print("skipped: set GEMINI_API_KEY in .env to run the video eval", file=sys.stderr)
        return 0
    rows = asyncio.run(run(load_cases(), analyzer))
    summary = {
        "model": registry.for_task("video").model,
        "cases": len(rows),
        "errors": [r["id"] for r in rows if r.get("error")],
        "unreviewed": [r["id"] for r in rows if not r["reviewed"]],
        "cost_usd": round(sum(u.cost_usd for u in usage), 4),
        "max_seconds": max((r.get("seconds", 0) for r in rows), default=0),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(f"report: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
