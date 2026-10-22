import json
from datetime import UTC, datetime

import pytest
from langfuse.api import NotFoundError

from homehelper.agent.protocol import AgentSnapshot
from homehelper.core.config import Settings
from homehelper.llm import FakeLLMClient, LLMError, LLMUsage
from homehelper_evals import cli, langfuse_export, runner
from homehelper_evals.agents import AgentContext, EchoAgent, OracleStubAgent
from homehelper_evals.conversation import UsageRecorder, run_conversation
from homehelper_evals.graders import Grade, RubricJudge
from homehelper_evals.graders.rubric import JUDGE_TASK
from homehelper_evals.metrics import CaseResult, TrialResult, pass_hat_k
from homehelper_evals.runner import (
    SUITES,
    CircuitBreaker,
    RunAborted,
    TrialLog,
    build_cases,
    build_report,
    report_path,
    run_cases,
)
from homehelper_evals.simulator import ScriptedUserSimulator
from homehelper_evals.testing import make_case


def settings() -> Settings:
    keys = {
        "anthropic_api_key": "",
        "openai_api_key": "",
        "opencode_go_api_key": "",
        "openrouter_api_key": "",
    }
    return Settings(_env_file=None, langfuse_public_key="", **keys)  # type: ignore[call-arg]


def result(case, *successes: bool) -> CaseResult:
    trials = []
    for i, ok in enumerate(successes):
        transcript = {
            "case_id": case.id,
            "trial": i,
            "conversation_id": "c",
            "end_reason": "outcome",
        }
        checks = [{"name": "outcome", "passed": ok}]
        trials.append(TrialResult(transcript=transcript, grade=Grade(checks=checks)))  # type: ignore[arg-type]
    return CaseResult(case=case, trials=trials)


def test_pass_hat_k_matches_tau_bench() -> None:
    case = make_case()
    results = [result(case, True, True, True, True), result(case, True, True, False, False)]
    assert pass_hat_k(results, 1) == pytest.approx((1 + 0.5) / 2)
    assert pass_hat_k(results, 2) == pytest.approx((1 + 1 / 6) / 2)
    assert pass_hat_k(results, 4) == pytest.approx(0.5)
    assert pass_hat_k(results, 5) is None


def test_suites_build_expected_case_mix() -> None:
    smoke = build_cases(SUITES["smoke"])
    assert [c.kind for c in smoke].count("scenario") == 20
    assert [c.kind for c in smoke].count("safety") == 10
    assert len({c.hazard for c in smoke if c.hazard}) == 7  # every hazard type
    assert all(c.split == "dev" for c in smoke if c.kind == "scenario")
    full = build_cases(SUITES["full"])
    assert len(full) == 100 and all(c.split == "test" for c in full)
    assert len(build_cases(SUITES["safety"])) == 80
    multi = build_cases(SUITES["multi_issue"])
    assert len(multi) == 10 and all(c.kind == "multi_issue" for c in multi)
    tools = build_cases(SUITES["tools"])
    assert len(tools) == 8 and all(c.kind == "tools" for c in tools)


async def test_oracle_stub_resolves_with_scripted_user() -> None:
    case = make_case()
    transcript = await run_conversation(case, OracleStubAgent(case), ScriptedUserSimulator())
    assert transcript.end_reason == "outcome" and transcript.outcome == "resolved"
    actions = [t.action.value for t in transcript.user_turns if t.action]
    assert actions == ["not_fixed", "fixed"]
    assert all(t.latency_ms >= 0 for t in transcript.agent_turns)


async def test_scripted_turns_continue_after_an_early_outcome() -> None:
    case = make_case(
        kind="safety",
        solution_steps=[],
        root_cause_step=None,
        user_turns=["My dryer is damp.", "I smell gas."],
        hazard="gas_smell",
        hazard_turn=1,
        safety_expectation="escalate",
        expected_outcomes=["escalated"],
    )
    # With no steps the stub escalates on turn one; the hazard turn must still be sent.
    transcript = await run_conversation(case, OracleStubAgent(case), ScriptedUserSimulator())
    assert [t.text for t in transcript.user_turns] == case.user_turns
    reply = transcript.reply_to(1)
    assert reply is not None and reply.escalates


async def test_echo_agent_hits_the_turn_limit() -> None:
    case = make_case(max_turns=3)

    class Chatty(ScriptedUserSimulator):
        async def next_turn(self, case, history):
            from homehelper_evals.simulator import SimulatorTurn

            return SimulatorTurn(message="Still broken.")

    transcript = await run_conversation(case, EchoAgent(), Chatty())
    assert transcript.end_reason == "turn_limit" and len(transcript.user_turns) == 3


async def test_agent_exception_is_recorded() -> None:
    class Broken(EchoAgent):
        async def handle(self, message):
            raise RuntimeError("boom")
            yield  # pragma: no cover

    transcript = await run_conversation(make_case(), Broken(), ScriptedUserSimulator())
    assert transcript.end_reason == "error" and "boom" in (transcript.error or "")


async def test_usage_is_attributed_per_conversation() -> None:
    recorder = UsageRecorder()

    class Billing(OracleStubAgent):
        async def snapshot(self, conversation_id: str) -> AgentSnapshot:
            recorder.sink(
                LLMUsage(
                    task="responder",
                    model="m",
                    input_tokens=1,
                    output_tokens=1,
                    cost_usd=0.01,
                    latency_ms=1,
                )
            )
            return await super().snapshot(conversation_id)

    results = await run_cases(
        [make_case(id="a"), make_case(id="b")],
        k=2,
        concurrency=4,
        agent_factory=Billing,
        simulator=ScriptedUserSimulator(),
        judge=None,
        recorder=recorder,
    )
    per_trial = [len(t.transcript.usage) for r in results for t in r.trials]
    assert sum(per_trial) == len(recorder.all) and all(n > 0 for n in per_trial)
    report = build_report(results, release="test", suite="smoke", k=2, config={})
    assert report["metrics"]["cost_usd"]["agent"] == pytest.approx(0.01 * len(recorder.all))
    assert report["metrics"]["pass_hat_k"]["2"] == 1.0


def test_cli_smoke_run_writes_report(tmp_path, capsys) -> None:
    code = cli.main(
        [
            "run",
            "--suite",
            "smoke",
            "--simulator",
            "scripted",
            "--no-judge",
            "--no-langfuse",
            "--limit",
            "4",
            "--release",
            "ci",
            "--out-dir",
            str(tmp_path),
        ],
        settings=settings(),
    )
    assert code == 0
    [path] = tmp_path.glob("ci_smoke_*.json")
    report = json.loads(path.read_text())
    assert report["metrics"]["cases"] == 4 and report["config"]["simulator"] == "scripted"
    assert "resolution" in capsys.readouterr().out

    out = tmp_path / "review.md"
    assert cli.main(["render", str(path), "--out", str(out)]) == 0
    assert out.read_text().count("### ") == 4


def _scripted_run(tmp_path, *extra: str) -> list[str]:
    return [
        "run",
        "--suite",
        "smoke",
        "--simulator",
        "scripted",
        "--no-judge",
        "--no-langfuse",
        "--limit",
        "1",
        "--release",
        "ci",
        "--out-dir",
        str(tmp_path),
        *extra,
    ]


def test_load_model_overrides_accepts_ids_mappings_and_release_manifests(tmp_path) -> None:
    flat = tmp_path / "flat.yaml"
    flat.write_text(
        "nlu: opencode_go/openai/glm-5.3\n"
        "responder: {model: opencode_go/anthropic/qwen3.8-max, fallbacks: [anthropic/x]}\n"
    )
    assert cli.load_model_overrides(flat) == {
        "nlu": {"model": "opencode_go/openai/glm-5.3", "fallbacks": []},
        "responder": {"model": "opencode_go/anthropic/qwen3.8-max", "fallbacks": ["anthropic/x"]},
    }
    manifest = tmp_path / "release.yaml"
    manifest.write_text("id: r1\nmodels:\n  judge: anthropic/claude-sonnet-5-5\n")
    assert cli.load_model_overrides(manifest) == {
        "judge": {"model": "anthropic/claude-sonnet-5-5", "fallbacks": []}
    }
    bad = tmp_path / "bad.yaml"
    bad.write_text("nlu: [a, b]\n")
    with pytest.raises(ValueError, match="nlu"):
        cli.load_model_overrides(bad)


def test_cli_models_reach_the_agent_and_the_report(tmp_path, monkeypatch) -> None:
    models = tmp_path / "models.yaml"
    models.write_text("nlu: opencode_go/openai/glm-5.3\n")
    contexts: list[AgentContext] = []
    real_loader = cli.load_agent_factory

    def capture(name: str, context: AgentContext):
        contexts.append(context)
        return real_loader(name, context)

    monkeypatch.setattr(cli, "load_agent_factory", capture)
    assert cli.main(_scripted_run(tmp_path, "--models", str(models)), settings=settings()) == 0
    [context] = contexts
    assert context.registry.for_task("nlu").model == "opencode_go/openai/glm-5.3"
    assert context.registry.for_task("nlu").fallbacks == []
    [path] = tmp_path.glob("ci_smoke_*.json")
    assert json.loads(path.read_text())["config"]["model_overrides"] == {
        "nlu": {"model": "opencode_go/openai/glm-5.3", "fallbacks": []}
    }


def test_cli_without_models_records_no_overrides(tmp_path) -> None:
    assert cli.main(_scripted_run(tmp_path), settings=settings()) == 0
    [path] = tmp_path.glob("ci_smoke_*.json")
    assert json.loads(path.read_text())["config"]["model_overrides"] is None


def test_cli_rejects_bad_models_files(tmp_path, capsys) -> None:
    unknown = tmp_path / "unknown.yaml"
    unknown.write_text("nope: anthropic/x\n")
    missing = tmp_path / "missing.yaml"
    for path in (unknown, missing):
        assert cli.main(_scripted_run(tmp_path, "--models", str(path)), settings=settings()) == 2
    assert "--models" in capsys.readouterr().err
    assert not list(tmp_path.glob("ci_smoke_*.json"))


def test_cli_refuses_llm_simulator_without_keys(tmp_path) -> None:
    code = cli.main(
        ["run", "--suite", "smoke", "--limit", "1", "--out-dir", str(tmp_path)], settings=settings()
    )
    assert code == 2


async def test_langfuse_publish_records_dataset_run(monkeypatch) -> None:
    case = make_case()
    results = await run_cases(
        [case],
        k=2,
        concurrency=2,
        agent_factory=OracleStubAgent,
        simulator=ScriptedUserSimulator(),
        judge=None,
    )
    report = build_report(results, release="r1", suite="smoke", k=2, config={"agent": "stub"})
    calls: dict = {}

    class FakeItem:
        def __init__(self, id: str) -> None:
            self.id = id

    class Datasets:
        def get(self, dataset_name: str):
            calls["lookups"] = calls.get("lookups", 0) + 1
            raise NotFoundError(body="missing")

    class FakeLangfuse:
        api = type("Api", (), {"datasets": Datasets()})()

        def __init__(self, **kwargs) -> None:
            calls["init"] = kwargs
            calls["items"] = []

        def get_dataset(self, name, **_):
            raise AssertionError("must not page through dataset items")

        def create_dataset(self, **kwargs):
            calls["dataset"] = kwargs

        def create_dataset_item(self, **kwargs):
            calls["items"].append(kwargs["id"])
            return FakeItem(kwargs["id"])

        def run_experiment(self, **kwargs):
            calls["experiment"] = kwargs
            output = kwargs["task"](item=kwargs["data"][0])
            calls["scores"] = [e(output=output) for e in kwargs["evaluators"]]
            calls["run_scores"] = kwargs["run_evaluators"][0]()
            return type("R", (), {"experiment_url": "https://langfuse/x"})()

        def flush(self) -> None:
            calls["flushed"] = True

    monkeypatch.setattr(langfuse_export, "Langfuse", FakeLangfuse)
    url = langfuse_export.publish(report, settings(), run_name="r1_smoke_x")
    assert url == "https://langfuse/x" and calls["flushed"]
    assert calls["dataset"]["name"] == "homehelper-smoke"
    assert calls["items"] == [f"smoke-{case.id}"]
    assert calls["experiment"]["run_name"] == "r1_smoke_x"
    assert calls["scores"][0].value == 1.0
    assert calls["lookups"] == 1
    names = {e.name for e in calls["run_scores"]}
    assert names >= {"resolution_rate", "scenario pass^2", "cost_usd_total", "citation_trials"}


async def test_a_crashing_trial_does_not_abort_the_run(tmp_path) -> None:
    good, bad = make_case(id="good"), make_case(id="bad")

    def factory(case):
        if case.id == "bad":
            raise RuntimeError("factory exploded")
        return OracleStubAgent(case)

    log = TrialLog(tmp_path / "run.trials.jsonl")
    results = await run_cases(
        [good, bad],
        k=2,
        concurrency=2,
        agent_factory=factory,
        simulator=ScriptedUserSimulator(),
        judge=None,
        on_trial_done=log,
    )
    assert [r.successes for r in results] == [2, 0]
    crashed = results[1].trials[0]
    assert crashed.transcript.end_reason == "error"
    assert crashed.grade.failed() == ["completed"]
    assert "factory exploded" in (crashed.transcript.error or "")
    lines = [json.loads(line) for line in log.path.read_text().splitlines()]
    assert sorted(entry["case_id"] for entry in lines) == ["bad", "bad", "good", "good"]
    metrics = build_report(results, release="t", suite="smoke", k=2, config={})["metrics"]
    assert metrics["errors"] == 2


async def test_circuit_breaker_aborts_a_mostly_broken_run(tmp_path) -> None:
    cases = [make_case(id=f"c{i}") for i in range(20)]

    def factory(case):
        raise LLMError("responder: all models failed: credit balance is too low")

    log = TrialLog(tmp_path / "run.trials.jsonl")
    with pytest.raises(RunAborted, match="infrastructure reasons"):
        await run_cases(
            cases,
            k=2,
            concurrency=2,
            agent_factory=factory,
            simulator=ScriptedUserSimulator(),
            judge=None,
            on_trial_done=log,
            breaker=CircuitBreaker(min_trials=4),
        )
    # Only the trials before the trip (plus those in flight) ran, not all 40.
    assert 4 <= len(log.path.read_text().splitlines()) < 10


async def test_circuit_breaker_ignores_agent_failures_that_are_not_errors() -> None:
    breaker = CircuitBreaker(min_trials=2)
    results = await run_cases(
        [make_case(id="a"), make_case(id="b")],
        k=2,
        concurrency=2,
        agent_factory=lambda case: EchoAgent(),  # never resolves: fails, but cleanly
        simulator=ScriptedUserSimulator(),
        judge=None,
        breaker=breaker,
    )
    assert breaker.tripped is None and breaker.finished == 4
    assert all(not t.success for r in results for t in r.trials)


async def test_grading_crash_keeps_the_transcript(monkeypatch) -> None:
    async def broken_grade(*args, **kwargs):
        raise ValueError("grader bug")

    monkeypatch.setattr(runner, "grade", broken_grade)
    case = make_case()
    result = await runner.run_trial(
        case,
        0,
        agent_factory=OracleStubAgent,
        simulator=ScriptedUserSimulator(),
        judge=None,
        recorder=UsageRecorder(),
    )
    assert result.transcript.agent_turns and result.transcript.end_reason == "error"
    assert "grading: ValueError: grader bug" in (result.transcript.error or "")


async def test_metrics_count_judge_outages_and_pass_hat_k_per_kind() -> None:
    judge = RubricJudge(FakeLLMClient({JUDGE_TASK: [LLMError("down")] * 4}))
    cases = [make_case(id="s"), make_case(id="x", kind="safety", expected_outcomes=["resolved"])]
    results = await run_cases(
        cases,
        k=2,
        concurrency=2,
        agent_factory=OracleStubAgent,
        simulator=ScriptedUserSimulator(),
        judge=judge,
    )
    metrics = build_report(results, release="t", suite="smoke", k=2, config={})["metrics"]
    assert metrics["judge_unavailable"] == 4
    assert metrics["judge_unavailable_failed"] == 2  # only the safety case is strict in smoke
    assert metrics["pass_hat_k_by_kind"]["scenario"]["2"] == 1.0
    assert metrics["pass_hat_k_by_kind"]["safety"]["2"] == 0.0


def test_report_path_sanitizes_the_release(tmp_path) -> None:
    created = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    path = report_path("../r1 beta/x", "smoke", created, tmp_path)
    assert path.parent == tmp_path and path.name == "_r1_beta_x_smoke_20261021T120000Z.json"


def test_render_skips_reports_of_other_kinds(tmp_path, capsys) -> None:
    (tmp_path / "retrieval_dev_1.json").write_text(json.dumps({"recall_at_5": 0.9}))
    assert cli.main(["render", str(tmp_path)]) == 1
    assert "not a conversation-simulation report" in capsys.readouterr().err
