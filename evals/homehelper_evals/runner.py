"""Suite assembly, k trials per case in parallel, grading, and the JSON report (spec §16.4)."""

import asyncio
import json
import re
import subprocess
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from homehelper_evals import REPO_ROOT, REPORTS_DIR
from homehelper_evals.agents import AgentFactory
from homehelper_evals.cases import CaseKind, EvalCase, load_dataset, scenario_case
from homehelper_evals.conversation import UsageRecorder, run_conversation
from homehelper_evals.graders import Check, Grade, RubricJudge, grade
from homehelper_evals.manifest import load_manuals
from homehelper_evals.metrics import CaseResult, TrialResult, compute_metrics
from homehelper_evals.scenarios import load_root_causes, load_variants, sample_variants
from homehelper_evals.simulator import UserSimulator
from homehelper_evals.splits import Split
from homehelper_evals.transcript import Transcript

SuiteName = Literal["smoke", "safety", "full"]
REPORT_TYPE = "conversation_simulation"
# Release gates: here an unavailable judge fails the trial and the run exits non-zero.
STRICT_JUDGE_SUITES: frozenset[str] = frozenset({"safety", "full"})


class SuiteConfig(BaseModel):
    k: int
    scenario_split: Split = "test"
    # Q9 (spec §20): conversation simulation uses a stratified sample, not all 971 scenarios.
    scenarios_per_category: int = 0
    datasets: list[CaseKind] = []
    dataset_limit: int | None = None  # per dataset; spread across hazard types


SUITES: dict[SuiteName, SuiteConfig] = {
    # Every PR with the `run-eval` label: 20 dev scenarios + 10 safety cases, one trial each.
    "smoke": SuiteConfig(
        k=1, scenario_split="dev", scenarios_per_category=2, datasets=["safety"], dataset_limit=10
    ),
    # Before a release: every safety, injection and out-of-scope case, four trials.
    "safety": SuiteConfig(k=4, datasets=["safety", "injection", "out_of_scope"]),
    # Before a release: 10 test scenarios per category (100), four trials.
    "full": SuiteConfig(k=4, scenario_split="test", scenarios_per_category=10),
}


def spread(cases: list[EvalCase], limit: int | None) -> list[EvalCase]:
    """First `limit` cases taken round-robin across hazard types (or as-is without hazards)."""
    if limit is None or limit >= len(cases):
        return cases
    groups: dict[str, list[EvalCase]] = defaultdict(list)
    for case in cases:
        groups[case.hazard or ""].append(case)
    queues = [groups[key] for key in sorted(groups)]
    picked: list[EvalCase] = []
    while len(picked) < limit:
        for queue in queues:
            if queue and len(picked) < limit:
                picked.append(queue.pop(0))
    return picked


def build_cases(config: SuiteConfig, *, seed: str = "v1") -> list[EvalCase]:
    cases: list[EvalCase] = []
    if config.scenarios_per_category:
        root_causes = load_root_causes()
        manuals = load_manuals()
        candidates = [v for v in load_variants() if root_causes[v.variant_id].troubleshootable]
        for variant in sample_variants(
            candidates,
            split=config.scenario_split,
            per_category=config.scenarios_per_category,
            seed=seed,
        ):
            cases.append(
                scenario_case(variant, root_causes[variant.variant_id], manuals=manuals, seed=seed)
            )
    for kind in config.datasets:
        cases.extend(spread(load_dataset(kind), config.dataset_limit))
    return cases


async def run_trial(
    case: EvalCase,
    trial: int,
    *,
    agent_factory: AgentFactory,
    simulator: UserSimulator,
    judge: RubricJudge | None,
    recorder: UsageRecorder,
    strict_judge: bool = False,
) -> TrialResult:
    """Never raises: a crash anywhere (agent factory, conversation, grading) becomes a failed
    trial with end_reason="error", so one bad case cannot abort the run."""
    transcript = None
    try:
        transcript = await run_conversation(
            case, agent_factory(case), simulator, trial=trial, recorder=recorder
        )
        with recorder.collect() as judge_usage:
            result = await grade(case, transcript, judge, strict_judge=strict_judge)
        transcript.usage.extend(judge_usage)
        return TrialResult(transcript=transcript, grade=result)
    except Exception as exc:
        stage = "grading" if transcript is not None else "conversation"
        error = f"{stage}: {type(exc).__name__}: {exc}"
        if transcript is None:
            transcript = Transcript(
                case_id=case.id,
                trial=trial,
                conversation_id=f"eval-{case.id}-{trial}-crashed",
                end_reason="error",
            )
        transcript.end_reason, transcript.error = "error", error
        return TrialResult(
            transcript=transcript,
            grade=Grade(checks=[Check(name="completed", passed=False, detail=error)]),
        )


class TrialLog:
    """Appends each finished trial to `<report>.trials.jsonl`, so a run that dies midway still
    leaves its results on disk. Removed once the full report is written."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    def __call__(self, case: EvalCase, result: TrialResult) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(_trial_entry(case.id, result), ensure_ascii=False) + "\n")


async def run_cases(
    cases: list[EvalCase],
    *,
    k: int,
    concurrency: int,
    agent_factory: AgentFactory,
    simulator: UserSimulator,
    judge: RubricJudge | None,
    recorder: UsageRecorder | None = None,
    strict_judge: bool = False,
    on_trial_done: Callable[[EvalCase, TrialResult], None] | None = None,
) -> list[CaseResult]:
    recorder = recorder or UsageRecorder()
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: EvalCase, trial: int) -> TrialResult:
        async with semaphore:
            result = await run_trial(
                case,
                trial,
                agent_factory=agent_factory,
                simulator=simulator,
                judge=judge,
                recorder=recorder,
                strict_judge=strict_judge,
            )
        if on_trial_done is not None:
            on_trial_done(case, result)
        return result

    per_case = await asyncio.gather(
        *(asyncio.gather(*(one(case, t) for t in range(k))) for case in cases)
    )
    return [
        CaseResult(case=case, trials=list(trials))
        for case, trials in zip(cases, per_case, strict=True)
    ]


def git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def _trial_entry(case_id: str, t: TrialResult) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "success": t.success,
        "failed_checks": t.grade.failed(),
        "grade": t.grade.model_dump(mode="json"),
        "transcript": t.transcript.model_dump(mode="json"),
    }


def build_report(
    results: list[CaseResult],
    *,
    release: str,
    suite: str,
    k: int,
    config: dict[str, Any],
    created_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "report_type": REPORT_TYPE,
        "schema_version": 1,
        "release": release,
        "suite": suite,
        "created_at": (created_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config": {"k": k, **config},
        "metrics": compute_metrics(results, k),
        "cases": [
            {
                "case": r.case.model_dump(mode="json", exclude_defaults=True),
                "successes": r.successes,
                "trials": [_trial_entry(r.case.id, t) for t in r.trials],
            }
            for r in results
        ],
    }


def report_path(
    release: str, suite: str, created_at: datetime, directory: Path = REPORTS_DIR
) -> Path:
    safe_release = re.sub(r"[^A-Za-z0-9._-]", "_", release).strip(".") or "release"
    stamp = created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return directory / f"{safe_release}_{suite}_{stamp}.json"


def is_run_report(report: Any) -> bool:
    """Conversation-simulation reports only; `evals/reports/` also holds retrieval reports."""
    return isinstance(report, dict) and report.get("report_type") == REPORT_TYPE


def write_report(report: dict[str, Any], directory: Path = REPORTS_DIR) -> Path:
    created_at = datetime.fromisoformat(report["created_at"])
    path = report_path(report["release"], report["suite"], created_at, directory)
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    return path
