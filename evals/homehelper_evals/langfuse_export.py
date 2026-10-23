"""Publish a finished report to Langfuse as a dataset experiment run (spec §16.4).

Conversations run first, under the runner's own concurrency and trial control; this step then
upserts one dataset item per case (`homehelper-<suite>`) and records an experiment run whose
task output is that case's recorded trials. Runs of the same suite across releases share the
dataset items, so Langfuse can compare them side by side (e.g. baseline vs. journey agent).

Reads only use the dataset endpoints; nothing here reads traces back (`GET /api/public/traces`
is deprecated; use the v2 observations API for that).
"""

import statistics
from typing import Any

from langfuse import Evaluation, Langfuse
from langfuse.api import NotFoundError

from homehelper.core.config import Settings
from homehelper_evals.render import render_dialogue
from homehelper_evals.transcript import Transcript

PUBLISHED_METRICS = (
    "success_rate",
    "resolution_rate",
    "safety_pass_rate",
    "injection_resistance",
    "out_of_scope_pass_rate",
    "multi_issue_pass_rate",
    "tool_scenario_pass_rate",
    "multimodal_pass_rate",
    "regression_pass_rate",
    "issue_outcome_accuracy",
    "citation_accuracy",
    "avg_turns_to_resolution",
    "citation_trials",
    "judge_unavailable",
)


def dataset_name(suite: str) -> str:
    return f"homehelper-{suite}"


def item_id(suite: str, case_id: str) -> str:
    # Item ids are global across datasets, so they carry the suite.
    return f"{suite}-{case_id}"


def _case_output(entry: dict[str, Any]) -> dict[str, Any]:
    trials = entry["trials"]
    first = Transcript.model_validate(trials[0]["transcript"])
    rubrics = [t["grade"]["rubric"] for t in trials if t["grade"]["rubric"]]
    return {
        "successes": entry["successes"],
        "trials": len(trials),
        "outcomes": [
            t["transcript"]["snapshot"]["outcome"] if t["transcript"]["snapshot"] else None
            for t in trials
        ],
        "failed_checks": [t["failed_checks"] for t in trials],
        "rubric_mean": (
            statistics.fmean(
                (r["one_step_at_a_time"] + r["clarity"] + r["empathy"] + r["english"]) / 4
                for r in rubrics
            )
            if rubrics
            else None
        ),
        "agent_cost_usd": sum(
            u["cost_usd"]
            for t in trials
            for u in t["transcript"]["usage"]
            if u["task"] not in ("user_simulator", "judge")
        ),
        "transcript_trial_0": render_dialogue(first.turns, user="User", agent="Agent"),
    }


def _item_evaluators() -> list[Any]:
    def success_rate(*, output: dict[str, Any], **_: Any) -> Evaluation:
        return Evaluation(name="success_rate", value=output["successes"] / output["trials"])

    def all_trials_pass(*, output: dict[str, Any], **_: Any) -> Evaluation:
        return Evaluation(
            name="pass_all_trials",
            value=output["successes"] == output["trials"],
            data_type="BOOLEAN",
        )

    def rubric(*, output: dict[str, Any], **_: Any) -> list[Evaluation]:
        if output["rubric_mean"] is None:
            return []
        return [Evaluation(name="rubric_mean", value=round(output["rubric_mean"], 2))]

    return [success_rate, all_trials_pass, rubric]


def _run_evaluator(metrics: dict[str, Any]) -> Any:
    def report_metrics(**_: Any) -> list[Evaluation]:
        evaluations = [
            Evaluation(name=name, value=metrics[name])
            for name in PUBLISHED_METRICS
            if metrics.get(name) is not None
        ]
        for kind, values in metrics["pass_hat_k_by_kind"].items():
            for k, value in values.items():
                if value is not None:
                    evaluations.append(Evaluation(name=f"{kind} pass^{k}", value=value))
        evaluations.append(Evaluation(name="cost_usd_total", value=metrics["cost_usd"]["total"]))
        return evaluations

    return report_metrics


def publish(report: dict[str, Any], settings: Settings, *, run_name: str) -> str | None:
    """Upsert the suite's dataset items and record this run; returns the experiment URL."""
    suite = report["suite"]
    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
        environment=settings.app_env,
        release=report["release"],
    )
    name = dataset_name(suite)
    try:
        # One request; `get_dataset` would also page through every item.
        client.api.datasets.get(dataset_name=name)
    except NotFoundError:
        client.create_dataset(name=name, description=f"HomeHelper eval suite '{suite}'")

    outputs: dict[str, dict[str, Any]] = {}
    items = []
    for entry in report["cases"]:
        case = entry["case"]
        identifier = item_id(suite, case["id"])
        # Upsert by id; the returned item is what the experiment run links to.
        item = client.create_dataset_item(
            dataset_name=name,
            id=identifier,
            input={
                key: case.get(key)
                for key in ("id", "kind", "persona", "scenario", "user_turns", "category")
            },
            expected_output={
                "outcomes": case["expected_outcomes"],
                "assertions": case.get("assertions", {}),
            },
            metadata={key: case.get(key) for key in ("kind", "category", "split", "hazard")},
        )
        items.append(item)
        outputs[identifier] = _case_output(entry)

    def task(*, item: Any, **_: Any) -> dict[str, Any]:
        return outputs[item.id]

    result = client.run_experiment(
        name=f"homehelper-{suite}",
        run_name=run_name,
        description=f"{report['release']} {suite} (k={report['config']['k']})",
        data=items,
        task=task,
        evaluators=_item_evaluators(),
        run_evaluators=[_run_evaluator(report["metrics"])],
        max_concurrency=8,
        metadata={
            "release": report["release"],
            "suite": suite,
            "agent": str(report["config"].get("agent")),
            "git_sha": str(report.get("git_sha")),
        },
    )
    client.flush()
    return result.experiment_url
