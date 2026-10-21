"""M2-01: label each scenario variant's `root_cause_step` with an LLM, then freeze the result.

The simulated user (spec §16.3) reports "fixed" only when the agent proposes this step, so the
label decides what counts as a resolution. Labels are produced once, spot-checked by a human,
and committed as `data/scenarios/root_cause_steps.v1.json`; a new labeling run must use a new
version number instead of overwriting.
"""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from homehelper.llm import LLMClient, LLMError, Message
from homehelper_evals.scenarios import RootCause, ScenarioVariant

LABEL_TASK = "extract"

LABEL_PROMPT = """\
You label troubleshooting data for an appliance-repair support agent evaluation.

You get a symptom reported by a user and the ordered troubleshooting steps from the appliance's
manual. Pick the ONE step that most plausibly fixes this specific symptom, i.e. the step that
addresses its most likely root cause. A simulated user will say "that fixed it" only when the
agent suggests this step, and "I did it, but it didn't help" for every other step.

Rules:
- Prefer the step that directly targets the symptom over generic checks (power, plug, settings)
  unless the symptom itself points to that generic cause.
- Prefer an action the user can perform over a purely informational note.
- If the only step that could fix the symptom is contacting service, a technician, or the
  manufacturer, pick that step and set user_fixable to false. Otherwise user_fixable is true.
- root_cause_step is the 1-based number of the step in the list.
- troubleshootable: false when the "symptom" is a general warning, safety notice, or
  documentation note rather than a concrete malfunction or usage problem that a user would
  contact support about (e.g. "Placing flammable items inside the refrigerator is a fire
  risk"). Still pick the best step.
- rationale: one short English sentence.
"""


class RootCauseLabel(BaseModel):
    root_cause_step: int = Field(ge=1)
    user_fixable: bool
    troubleshootable: bool
    rationale: str


def label_messages(variant: ScenarioVariant) -> list[Message]:
    steps = "\n".join(f"{i}. {step}" for i, step in enumerate(variant.solution_steps, start=1))
    user = (
        f"Appliance: {variant.brand} {variant.category.value.replace('_', ' ')}\n"
        f"Symptom: {variant.scenario}\n\n"
        f"Troubleshooting steps from the manual:\n{steps}"
    )
    return [Message(role="system", content=LABEL_PROMPT), Message(role="user", content=user)]


async def label_variant(llm: LLMClient, variant: ScenarioVariant) -> RootCause:
    label = await llm.structured(LABEL_TASK, label_messages(variant), RootCauseLabel)
    if label.root_cause_step > len(variant.solution_steps):
        raise LLMError(
            f"{variant.variant_id}: step {label.root_cause_step} out of range "
            f"(1..{len(variant.solution_steps)})"
        )
    return RootCause(**label.model_dump())


async def label_all(
    llm: LLMClient, variants: list[ScenarioVariant], *, concurrency: int = 8
) -> dict[str, RootCause]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(variant: ScenarioVariant) -> tuple[str, RootCause]:
        async with semaphore:
            return variant.variant_id, await label_variant(llm, variant)

    results = await asyncio.gather(*(one(v) for v in variants))
    return dict(results)


def render_labels(
    variants: list[ScenarioVariant], labels: dict[str, RootCause], *, model: str
) -> str:
    entries = {}
    for variant in variants:
        label = labels[variant.variant_id]
        entries[variant.variant_id] = {
            **label.model_dump(),
            # Context for human review and joins; not used by the label itself.
            "root_cause_text": variant.solution_steps[label.root_cause_step - 1],
            "scenario": variant.scenario,
            "split": variant.split,
            "row_ids": [row.id for row in variant.rows],
        }
    document = {
        "version": 1,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%d"),
        "labeler": {
            "task": LABEL_TASK,
            "model": model,
            "prompt_sha256": hashlib.sha256(LABEL_PROMPT.encode()).hexdigest()[:12],
        },
        "counts": {
            "variants": len(entries),
            "user_fixable": sum(e["user_fixable"] for e in entries.values()),
            "troubleshootable": sum(e["troubleshootable"] for e in entries.values()),
        },
        "labels": entries,
    }
    return json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def write_labels(path: Path, rendered: str, *, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise SystemExit(f"{path} is frozen; bump the version instead of overwriting it")
    path.write_text(rendered)
