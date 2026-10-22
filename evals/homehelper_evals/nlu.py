"""NLU accuracy on the hand-labelled set in `evals/datasets/nlu.yaml` (M3-03).

    uv run python -m homehelper_evals.nlu [--models evals/models/opencode-go.yaml] [--k 1]

Each case runs the real `understand` prompt (`homehelper.agent.nodes.understand.nlu_messages`)
with the state given in its `context`. Reported: intent accuracy, per-slot accuracy, step
feedback accuracy, and hazard recall / precision / exact match (recall matters most: a missed
hazard is the dangerous error, spec §8.1).
"""

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from homehelper.agent.deps import AgentDeps
from homehelper.agent.engine import default_catalog
from homehelper.agent.nodes.understand import nlu_messages
from homehelper.agent.state import AgentState, NLUResult, PlanItem
from homehelper.agent.turn import GraphState
from homehelper.core.config import Settings
from homehelper.llm import LLMClient, ModelRegistry, build_llm_client
from homehelper_evals import DATASETS_DIR, REPORTS_DIR
from homehelper_evals.cli import load_model_overrides

DATASET = DATASETS_DIR / "nlu.yaml"


class NLUContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    journey: str | None = None
    step: str | None = None
    presented_step: str | None = None


class NLUExpect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: str | list[str]
    slots: dict[str, str] = Field(default_factory=dict)
    step_feedback: str | None = "unset"  # "unset": not graded; None: must be null
    hazards: list[str] | None = None

    @property
    def intents(self) -> list[str]:
        return [self.intent] if isinstance(self.intent, str) else self.intent


class NLUCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    context: NLUContext = Field(default_factory=NLUContext)
    expect: NLUExpect


def load_cases(path: Path = DATASET) -> list[NLUCase]:
    data = yaml.safe_load(path.read_text())
    return [NLUCase.model_validate(case) for case in data["cases"]]


def case_state(case: NLUCase) -> GraphState:
    ctx = case.context
    plan = (
        [PlanItem(id="p1", instruction=ctx.presented_step, status="presented")]
        if ctx.presented_step
        else []
    )
    agent = AgentState(
        conversation_id=f"nlu-{case.id}",
        release_id="eval",
        active_journey=ctx.journey,
        step_id=ctx.step,
        plan=plan,
    )
    return GraphState(agent=agent)


def _norm(value: str) -> str:
    return re.sub(r"[\s_\-/]+", "", value.strip().lower())


def grade(case: NLUCase, nlu: NLUResult) -> dict[str, Any]:
    expect = case.expect
    found = {u.name: u.value for u in nlu.slot_updates}
    result: dict[str, Any] = {
        "intent": nlu.intent in expect.intents,
        "slots": {
            name: name in found and _norm(found[name]) == _norm(value)
            for name, value in expect.slots.items()
        },
    }
    if expect.step_feedback != "unset":
        result["step_feedback"] = nlu.step_feedback == expect.step_feedback
    if expect.hazards is not None:
        wanted, got = set(expect.hazards), set(nlu.hazard_signals)
        result["hazards"] = {
            "missed": sorted(wanted - got),
            "extra": sorted(got - wanted),
            "exact": wanted == got,
        }
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def rate(values: list[bool]) -> float | None:
        return round(sum(values) / len(values), 3) if values else None

    slot_hits: dict[str, list[bool]] = {}
    for row in rows:
        for name, hit in row["grade"]["slots"].items():
            slot_hits.setdefault(name, []).append(hit)
    hazard_rows = [row["grade"]["hazards"] for row in rows if "hazards" in row["grade"]]
    expected = sum(len(row["expect_hazards"]) for row in rows if row["expect_hazards"])
    missed = sum(len(h["missed"]) for h in hazard_rows)
    extra = sum(len(h["extra"]) for h in hazard_rows)
    detected = expected - missed
    return {
        "cases": len(rows),
        "intent_accuracy": rate([row["grade"]["intent"] for row in rows]),
        "slot_accuracy": {name: rate(hits) for name, hits in sorted(slot_hits.items())},
        "step_feedback_accuracy": rate(
            [row["grade"]["step_feedback"] for row in rows if "step_feedback" in row["grade"]]
        ),
        "hazard_recall": round(detected / expected, 3) if expected else None,
        "hazard_precision": round(detected / (detected + extra), 3) if detected + extra else None,
        "hazard_exact": rate([h["exact"] for h in hazard_rows]),
        "errors": sum(1 for row in rows if row.get("error")),
        "intent_confusions": dict(
            Counter(
                f"{row['expect_intent']} -> {row['intent']}"
                for row in rows
                if not row.get("error") and not row["grade"]["intent"]
            )
        ),
    }


async def run(cases: list[NLUCase], llm: LLMClient, concurrency: int = 8) -> list[dict[str, Any]]:
    deps = AgentDeps(llm=llm, retriever=None, catalog=default_catalog())  # type: ignore[arg-type]
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: NLUCase) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": case.id,
            "expect_intent": "|".join(case.expect.intents),
            "expect_hazards": case.expect.hazards,
        }
        async with semaphore:
            try:
                messages = nlu_messages(case_state(case), deps, case.text)
                nlu = await llm.structured("nlu", messages, NLUResult)
            except Exception as exc:
                return {**row, "error": f"{type(exc).__name__}: {exc}", "grade": _failed(case)}
        return {**row, "intent": nlu.intent, "nlu": nlu.model_dump(), "grade": grade(case, nlu)}

    return list(await asyncio.gather(*(one(case) for case in cases)))


def _failed(case: NLUCase) -> dict[str, Any]:
    """An errored call counts as wrong on everything it was graded on."""
    expect = case.expect
    result: dict[str, Any] = {"intent": False, "slots": {name: False for name in expect.slots}}
    if expect.step_feedback != "unset":
        result["step_feedback"] = False
    if expect.hazards is not None:
        result["hazards"] = {"missed": list(expect.hazards), "extra": [], "exact": False}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m homehelper_evals.nlu")
    parser.add_argument("--models", type=Path, help="model overrides YAML (as in `evals run`)")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--out", type=Path, default=REPORTS_DIR / "nlu.json")
    args = parser.parse_args(argv)

    overrides = load_model_overrides(args.models) if args.models else {}
    registry = ModelRegistry.load(overrides=overrides)
    llm = build_llm_client(Settings(), registry=registry)
    rows = asyncio.run(run(load_cases(), llm, args.concurrency))
    summary = {"model": registry.for_task("nlu").model, **summarize(rows)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    for row in rows:
        g = row["grade"]
        bad_slots = [n for n, ok in g["slots"].items() if not ok]
        hazards = g.get("hazards", {})
        if row.get("error") or not g["intent"] or bad_slots or hazards.get("missed"):
            got = (
                row.get("error") or f"intent={row.get('intent')} slots={row['nlu']['slot_updates']}"
            )
            print(f"- {row['id']}: {got} missed_hazards={hazards.get('missed')}", file=sys.stderr)
    print(f"report: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
