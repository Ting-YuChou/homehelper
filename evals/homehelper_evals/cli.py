"""`uv run evals ...` (spec §16.4).

evals run --suite {smoke|safety|full} [--k 4] [--concurrency 8] [--agent stub] [--models x.yaml]
evals label-root-causes            # M2-01, one-time; writes the frozen labels file
evals render <report.json>         # Markdown transcripts for manual review
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from homehelper.core.config import Settings
from homehelper.llm import ModelRegistry, build_llm_client
from homehelper_evals import REPORTS_DIR, ROOT_CAUSES_PATH
from homehelper_evals.agents import AgentContext, load_agent_factory
from homehelper_evals.cases import EvalCase
from homehelper_evals.conversation import UsageRecorder
from homehelper_evals.graders import Grade, RubricJudge
from homehelper_evals.metrics import TrialResult
from homehelper_evals.render import render_markdown
from homehelper_evals.root_cause import LABEL_TASK, label_all, render_labels, write_labels
from homehelper_evals.runner import (
    STRICT_JUDGE_SUITES,
    SUITES,
    RunAborted,
    TrialLog,
    build_cases,
    build_report,
    is_run_report,
    report_path,
    run_cases,
    write_report,
)
from homehelper_evals.scenarios import load_variants
from homehelper_evals.simulator import LLMUserSimulator, ScriptedUserSimulator, UserSimulator
from homehelper_evals.transcript import Transcript


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evals", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a conversation-simulation suite")
    run.add_argument("--suite", choices=sorted(SUITES), required=True)
    run.add_argument("--k", type=int, help="trials per case (default: the suite's)")
    run.add_argument("--concurrency", type=int, default=8)
    run.add_argument("--agent", default="stub", help="echo | stub | package.module:builder")
    run.add_argument("--simulator", choices=["llm", "scripted"], default="llm")
    run.add_argument(
        "--judge",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="LLM rubric judge (default: on)",
    )
    run.add_argument("--release", help="release id (default: RELEASE_ID / 'dev')")
    run.add_argument(
        "--models",
        type=Path,
        help="YAML of per-task model overrides (task: model-id, or task: {model, fallbacks, ...})",
    )
    run.add_argument(
        "--per-category",
        type=int,
        help="scenarios per category (default: the suite's; spec §20 Q9)",
    )
    run.add_argument("--limit", type=int, help="cap the number of cases (cheap trial runs)")
    run.add_argument("--seed", default="v1", help="scenario sampling seed")
    run.add_argument("--out-dir", type=Path, default=REPORTS_DIR)
    run.add_argument(
        "--langfuse",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="publish a Langfuse experiment run (default: on when keys are set)",
    )

    label = commands.add_parser("label-root-causes", help="M2-01: label root_cause_step (LLM)")
    label.add_argument("--concurrency", type=int, default=8)
    label.add_argument("--out", type=Path, default=ROOT_CAUSES_PATH)

    render = commands.add_parser("render", help="Markdown transcripts from run reports")
    render.add_argument("reports", type=Path, nargs="+", help="report files or directories")
    render.add_argument("--limit", type=int)
    render.add_argument("--out", type=Path)
    return parser


def _progress(case: EvalCase, result: TrialResult) -> None:
    status = "pass" if result.success else "FAIL " + ",".join(result.grade.failed())
    print(f"  {case.id} #{result.transcript.trial}: {status}", file=sys.stderr, flush=True)


def _summary(report: dict) -> str:
    m = report["metrics"]

    def pct(value: float | None) -> str:
        return "-" if value is None else f"{value:.1%}"

    lines = [
        f"suite={report['suite']} release={report['release']} cases={m['cases']} "
        f"trials={m['trials']} errors={m['errors']} judge_unavailable={m['judge_unavailable']} "
        f"(failing {m['judge_unavailable_failed']})",
        f"success {pct(m['success_rate'])} | resolution {pct(m['resolution_rate'])} | "
        f"safety {pct(m['safety_pass_rate'])} | injection {pct(m['injection_resistance'])} | "
        f"out-of-scope {pct(m['out_of_scope_pass_rate'])} | "
        f"multi-issue {pct(m['multi_issue_pass_rate'])} "
        f"(issue outcomes {pct(m['issue_outcome_accuracy'])}) | "
        f"tools {pct(m['tool_scenario_pass_rate'])} | "
        f"multimodal {pct(m.get('multimodal_pass_rate'))}",
        "pass^k "
        + " | ".join(
            f"{kind} " + " ".join(f"{k}:{pct(v)}" for k, v in values.items())
            for kind, values in m["pass_hat_k_by_kind"].items()
        ),
        f"citation accuracy {pct(m['citation_accuracy'])} over {m['citation_trials']} trials",
        f"rubric {m['rubric']}",
        f"failed checks {m['failed_checks']}",
        f"latency {m['latency_ms']}",
        f"cost {m['cost_usd']}",
    ]
    return "\n".join(lines)


def load_model_overrides(path: Path) -> dict[str, dict[str, Any]]:
    """Per-task overrides for `ModelRegistry.load`. A bare model id replaces the task's whole
    chain (no fallbacks), so an experiment never silently falls back to the default model.
    A release manifest works too: its `models:` section is used."""
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping of task -> model")
    models = data.get("models", data)
    if not isinstance(models, dict):
        raise ValueError(f"{path}: `models` must be a mapping of task -> model")
    overrides: dict[str, dict[str, Any]] = {}
    for task, value in models.items():
        if isinstance(value, str):
            overrides[task] = {"model": value, "fallbacks": []}
        elif isinstance(value, dict):
            overrides[task] = dict(value)
        else:
            raise ValueError(f"{path}: override for {task!r} must be a model id or a mapping")
    return overrides


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    config = SUITES[args.suite]
    if args.per_category is not None:
        config = config.model_copy(update={"scenarios_per_category": args.per_category})
    k = args.k or config.k
    cases = build_cases(config, seed=args.seed)[: args.limit]
    try:
        overrides = load_model_overrides(args.models) if args.models else {}
        registry = ModelRegistry.load(overrides=overrides)
    except (OSError, ValueError) as exc:
        print(f"--models: {exc}", file=sys.stderr)
        return 2
    recorder = UsageRecorder()
    needs_llm = args.simulator == "llm" or args.judge
    if needs_llm and not settings.provider_api_keys():
        print("no LLM API key configured; use --simulator scripted --no-judge", file=sys.stderr)
        return 2
    llm = (
        build_llm_client(settings, registry=registry, usage_sink=recorder.sink)
        if needs_llm
        else None
    )
    simulator: UserSimulator = (
        LLMUserSimulator(llm) if llm and args.simulator == "llm" else ScriptedUserSimulator()
    )
    judge = RubricJudge(llm) if llm and args.judge else None
    factory = load_agent_factory(args.agent, AgentContext(settings, recorder.sink, registry))
    release = args.release or settings.release_id

    created_at = datetime.now(UTC)
    trial_log = TrialLog(
        report_path(release, args.suite, created_at, args.out_dir).with_suffix(".trials.jsonl")
    )

    def on_trial_done(case: EvalCase, result: TrialResult) -> None:
        trial_log(case, result)
        _progress(case, result)

    strict_judge = args.suite in STRICT_JUDGE_SUITES
    print(f"running {len(cases)} cases x {k} trials ({args.suite})", file=sys.stderr)
    try:
        results = await run_cases(
            cases,
            k=k,
            concurrency=args.concurrency,
            agent_factory=factory,
            simulator=simulator,
            judge=judge,
            recorder=recorder,
            strict_judge=strict_judge,
            on_trial_done=on_trial_done,
        )
    except RunAborted as exc:
        # No report: a mostly-broken run must never pass for a result. The trials that did
        # finish stay in the trial log for debugging.
        print(f"run aborted: {exc}", file=sys.stderr)
        print(f"finished trials: {trial_log.path}", file=sys.stderr)
        return 4
    report = build_report(
        results,
        release=release,
        suite=args.suite,
        k=k,
        config={
            "agent": args.agent,
            "simulator": args.simulator
            + (
                f" ({registry.for_task('user_simulator').model})" if args.simulator == "llm" else ""
            ),
            "judge": registry.for_task("judge").model if judge else None,
            "model_overrides": overrides or None,
            "concurrency": args.concurrency,
            "seed": args.seed,
            "scenario_split": config.scenario_split,
            "scenarios_per_category": config.scenarios_per_category,
            "limit": args.limit,
            "strict_judge": strict_judge,
        },
        created_at=created_at,
    )
    path = write_report(report, args.out_dir)
    trial_log.path.unlink(missing_ok=True)
    print(_summary(report))
    print(f"report: {path}")

    publish = settings.tracing_enabled if args.langfuse is None else args.langfuse
    if publish:
        from homehelper_evals.langfuse_export import publish as publish_run

        url = await asyncio.to_thread(publish_run, report, settings, run_name=path.stem)
        print(f"langfuse: {url}")
    if report["metrics"]["judge_unavailable_failed"]:
        print("the judge was unavailable for safety-critical trials", file=sys.stderr)
        return 3
    return 0


async def _label(args: argparse.Namespace, settings: Settings) -> int:
    recorder = UsageRecorder()
    registry = ModelRegistry.load()
    llm = build_llm_client(settings, registry=registry, usage_sink=recorder.sink)
    variants = load_variants()
    labels = await label_all(llm, variants, concurrency=args.concurrency)
    rendered = render_labels(variants, labels, model=registry.for_task(LABEL_TASK).model)
    write_labels(args.out, rendered)
    cost = sum(u.cost_usd for u in recorder.all)
    print(f"labeled {len(labels)} variants -> {args.out} (${cost:.4f}, {len(recorder.all)} calls)")
    return 0


def _run_reports(paths: list[Path]) -> list[dict]:
    files = [f for p in paths for f in (sorted(p.glob("*.json")) if p.is_dir() else [p])]
    reports = []
    for file in files:
        try:
            report = json.loads(file.read_text())
        except ValueError:
            report = None
        if is_run_report(report):
            reports.append(report)
        else:
            print(f"skipping {file}: not a conversation-simulation report", file=sys.stderr)
    return reports


def _render(args: argparse.Namespace) -> int:
    reports = _run_reports(args.reports)
    blocks = []
    for report in reports:
        blocks.append(_render_report(report, args.limit))
    text = "\n".join(blocks)
    if args.out:
        args.out.write_text(text)
    else:
        print(text)
    return 0 if reports else 1


def _render_report(report: dict, limit: int | None) -> str:
    blocks = [f"# {report['release']} / {report['suite']} ({report['created_at']})\n"]
    for entry in report["cases"][:limit]:
        case = EvalCase.model_validate(entry["case"])
        for trial in entry["trials"]:
            transcript = Transcript.model_validate(trial["transcript"])
            grade = Grade.model_validate(trial["grade"])
            summary = {"success": grade.success, "failed": grade.failed()}
            if grade.rubric:
                summary["rubric"] = grade.rubric.model_dump(exclude={"rationale"})
            blocks.append(render_markdown(case, transcript, summary))
    return "\n".join(blocks)


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "render":
        return _render(args)
    settings = settings or Settings()
    started = datetime.now(UTC)
    if args.command == "label-root-causes":
        code = asyncio.run(_label(args, settings))
    else:
        code = asyncio.run(_run(args, settings))
    print(f"done in {(datetime.now(UTC) - started).total_seconds():.0f}s", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
