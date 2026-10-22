"""Photo understanding accuracy on `evals/datasets/vision.yaml` (M6-02/M6-04).

    uv run python -m homehelper_evals.vision [--models evals/models/opencode-go.yaml]

Each case sends one image through the real vision prompt
(`homehelper.agent.nodes.perceive.analyze_images`). Images live under `data/media/vision/`
(git-ignored); `python -m homehelper_evals.vision_media generate|fetch` puts them there.

Reported: per-field accuracy (null when nothing is there counts as right), the share of
appliances fully identified, issue-keyword recall, hazard recall, and calibration. Calibration is
what decides the confirm threshold (spec §11.2): of the wrong identifications, how many came with
confidence below it (the confirm step catches them), and of the confident ones, how many were
wrong (shown to the user as fact).
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.functional_validators import AfterValidator

from homehelper.agent.engine.predicates import LOW_CONFIDENCE
from homehelper.agent.nodes.perceive import analyze_images
from homehelper.core.config import Settings
from homehelper.knowledge.model_numbers import normalize_error_code, normalize_model
from homehelper.llm import LLMClient, ModelRegistry, build_llm_client
from homehelper.media.schemas import VisionResult
from homehelper_evals import DATASETS_DIR, REPO_ROOT, REPORTS_DIR
from homehelper_evals.cli import load_model_overrides

DATASET = DATASETS_DIR / "vision.yaml"
MEDIA_DIR = REPO_ROOT / "data" / "media" / "vision"
UNSET = "unset"  # not graded
IDENTITY_FIELDS = ("category", "brand", "model_number")
GRADED_FIELDS = (*IDENTITY_FIELDS, "displayed_error_code")
SWEEP = (0.5, 0.6, 0.7, 0.8, 0.9)
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

# Licences that allow reuse without asking (spec: only these images are fetched, never stored in
# git). Non-commercial and no-derivatives licences are refused.
ALLOWED_LICENCES = frozenset({"cc0", "pdm", "cc-by", "cc-by-sa"})
ALLOWED_HOSTS = (
    "upload.wikimedia.org",
    "thumb.wikimedia.org",  # Commons thumbnails (the API's `thumburl`)
    "live.staticflickr.com",
    "images.openverse.org",
)


def normalize_licence(raw: str) -> str:
    text = re.sub(r"[\s_]+", "-", raw.strip().lower())
    text = re.sub(r"-\d+(\.\d+)?$", "", text)  # version: "cc-by-4.0" -> "cc-by"
    if text in ("public-domain", "pd", "pdm", "public-domain-mark"):
        return "pdm"
    if text in ("cc0", "cc-zero"):
        return "cc0"
    if text.startswith("by"):
        text = "cc-" + text
    return text


def _allowed_licence(value: str) -> str:
    if normalize_licence(value) not in ALLOWED_LICENCES:
        raise ValueError(f"licence {value!r} is not one of CC0, PDM, CC BY, CC BY-SA")
    return value


class WebSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["web"] = "web"
    url: str
    page_url: str
    licence: Annotated[str, AfterValidator(_allowed_licence)]
    author: str
    sha256: str | None = None  # pinned on first fetch

    @field_validator("url")
    @classmethod
    def _known_host(cls, value: str) -> str:
        host = re.sub(r"^https://([^/]+)/.*$", r"\1", value)
        if host not in ALLOWED_HOSTS:
            raise ValueError(f"host {host!r} is not one of {', '.join(ALLOWED_HOSTS)}")
        return value


class SyntheticSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["synthetic"] = "synthetic"
    template: Literal["nameplate", "display", "blank", "text"]
    params: dict[str, Any] = Field(default_factory=dict)


class VisionExpect(BaseModel):
    """`None`: the model must report nothing. `"unset"`: not graded."""

    model_config = ConfigDict(extra="forbid")
    category: str | None = UNSET
    brand: str | None = UNSET
    model_number: str | None = UNSET
    displayed_error_code: str | None = UNSET
    issue_keywords: list[str] = Field(default_factory=list)
    hazards: list[str] | None = None


class VisionCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    image: str  # relative to the media dir
    source: WebSource | SyntheticSource = Field(discriminator="kind")
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    expect: VisionExpect
    notes: str | None = None


def load_cases(path: Path = DATASET) -> list[VisionCase]:
    data = yaml.safe_load(path.read_text())
    return [VisionCase.model_validate(case) for case in data["cases"]]


def _norm(field: str, value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    if field == "model_number":
        return normalize_model(value)
    if field == "displayed_error_code":
        return normalize_error_code(value)
    return re.sub(r"[^a-z0-9]", "", value.lower())


def grade(case: VisionCase, result: VisionResult) -> dict[str, Any]:
    expect = case.expect
    fields = {
        name: _norm(name, getattr(result, name)) == _norm(name, getattr(expect, name))
        for name in GRADED_FIELDS
        if getattr(expect, name) != UNSET
    }
    identity = [fields[name] for name in IDENTITY_FIELDS if name in fields]
    issues = " ".join(result.visible_issues).lower()
    keywords = expect.issue_keywords
    hazards = None
    if expect.hazards is not None:
        wanted, got = set(expect.hazards), set(result.hazard_signals)
        hazards = {"missed": sorted(wanted - got), "extra": sorted(got - wanted)}
    present = [name for name in IDENTITY_FIELDS if getattr(expect, name) not in (None, UNSET)]
    return {
        "fields": fields,
        "identifiable": bool(present),  # an appliance is there to identify
        "identified": bool(present) and all(fields[name] for name in present),
        "identity_wrong": (not all(identity)) if identity else None,
        "issue_recall": (
            round(sum(k.lower() in issues for k in keywords) / len(keywords), 3)
            if keywords
            else None
        ),
        "hazards": hazards,
    }


def _failed(case: VisionCase) -> dict[str, Any]:
    """A failed call is wrong on everything it would have been graded on."""
    empty = VisionResult(confidence=0.0)
    graded = grade(case, empty)
    graded["fields"] = {name: False for name in graded["fields"]}
    graded["identified"] = False
    if graded["identity_wrong"] is not None:
        graded["identity_wrong"] = True
    return graded


def _rate(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def calibration(rows: list[dict[str, Any]], threshold: float = LOW_CONFIDENCE) -> dict[str, Any]:
    """Over photos that show an appliance: the confidence is about its identity, so a confident
    "nothing here" on an empty photo says nothing about calibration."""
    graded = [
        r
        for r in rows
        if not r.get("error")  # a failed call has no confidence; it would look "caught"
        and r["grade"]["identifiable"]
        and r["grade"]["identity_wrong"] is not None
    ]
    wrong = [r for r in graded if r["grade"]["identity_wrong"]]

    def at(t: float) -> dict[str, Any]:
        confident = [r for r in graded if r["confidence"] >= t]
        return {
            "threshold": t,
            "confirm_rate": _rate([r["confidence"] < t for r in graded]),
            "catch_rate": _rate([r["confidence"] < t for r in wrong]),
            "silent_error_rate": _rate([r["grade"]["identity_wrong"] for r in confident]),
        }

    bins: list[list[dict[str, Any]]] = [[] for _ in range(5)]
    for row in graded:
        bins[min(int(row["confidence"] * 5), 4)].append(row)
    ece = (
        sum(
            len(b)
            * abs(
                sum(r["confidence"] for r in b) / len(b)
                - sum(not r["grade"]["identity_wrong"] for r in b) / len(b)
            )
            for b in bins
            if b
        )
        / len(graded)
        if graded
        else None
    )
    return {
        **at(threshold),
        "graded": len(graded),
        "ece": round(ece, 3) if ece is not None else None,
        "sweep": [at(t) for t in SWEEP],
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    missing = [r for r in rows if r.get("error") == "missing_media"]
    rows = [r for r in rows if r.get("error") != "missing_media"]
    field_hits: dict[str, list[bool]] = {}
    for row in rows:
        for name, hit in row["grade"]["fields"].items():
            field_hits.setdefault(name, []).append(hit)
    identifiable = [r for r in rows if r["grade"]["identifiable"]]
    recalls = [r["grade"]["issue_recall"] for r in rows if r["grade"]["issue_recall"] is not None]
    hazard_rows = [r["grade"]["hazards"] for r in rows if r["grade"]["hazards"] is not None]
    expected = sum(len(r["expect_hazards"] or []) for r in rows if "expect_hazards" in r)
    missed = sum(len(h["missed"]) for h in hazard_rows)
    return {
        "cases": len(rows),
        "missing_media": len(missing),
        "errors": sum(1 for r in rows if r.get("error")),
        "field_accuracy": {name: _rate(hits) for name, hits in sorted(field_hits.items())},
        "identification_rate": _rate([r["grade"]["identified"] for r in identifiable]),
        "issue_keyword_recall": round(sum(recalls) / len(recalls), 3) if recalls else None,
        "hazard_recall": round((expected - missed) / expected, 3) if expected else None,
        "hazard_false_alarms": sum(len(h["extra"]) for h in hazard_rows),
        "calibration": calibration(rows),
    }


async def run(
    cases: list[VisionCase], llm: LLMClient, media_dir: Path = MEDIA_DIR, concurrency: int = 4
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: VisionCase) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": case.id,
            "difficulty": case.difficulty,
            "source": case.source.kind,
            "expect_hazards": case.expect.hazards,
        }
        path = media_dir / case.image
        if not path.exists():
            return {**row, "error": "missing_media", "confidence": 0.0, "grade": _failed(case)}
        mime = MIME.get(path.suffix.lower(), "image/jpeg")
        async with semaphore:
            try:
                result = await analyze_images(llm, [(mime, path.read_bytes())])
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                return {**row, "error": error, "confidence": 0.0, "grade": _failed(case)}
        return {
            **row,
            "confidence": result.confidence,
            "result": result.model_dump(),
            "grade": grade(case, result),
        }

    return list(await asyncio.gather(*(one(case) for case in cases)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m homehelper_evals.vision")
    parser.add_argument("--models", type=Path, help="model overrides YAML (as in `evals run`)")
    parser.add_argument("--media-dir", type=Path, default=MEDIA_DIR)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", type=Path, default=REPORTS_DIR / "vision.json")
    args = parser.parse_args(argv)

    overrides = load_model_overrides(args.models) if args.models else {}
    registry = ModelRegistry.load(overrides=overrides)
    llm = build_llm_client(Settings(), registry=registry)
    rows = asyncio.run(run(load_cases(), llm, args.media_dir, args.concurrency))
    summary = {"model": registry.for_task("vision").model, **summarize(rows)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    for row in rows:
        g = row["grade"]
        wrong = [name for name, ok in g["fields"].items() if not ok]
        if row.get("error") or wrong:
            got = row.get("error") or {k: row["result"].get(k) for k in wrong}
            print(f"- {row['id']} ({row['confidence']:.2f}): {got}", file=sys.stderr)
    print(f"report: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
