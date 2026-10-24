"""The no-model suites: cases, simulated user, simulated photos, graders and metrics."""

import json
from pathlib import Path

import pytest

from homehelper.channels.events import StepCard
from homehelper.knowledge.schemas import Citation
from homehelper.knowledge.web import SearchHit, Whitelist
from homehelper.llm import FakeLLMClient
from homehelper_evals import cli
from homehelper_evals.cases import EvalCase, no_model_cases
from homehelper_evals.conversation import to_user_turn
from homehelper_evals.graders import RubricJudge, grade
from homehelper_evals.graders.rubric import JUDGE_TASK
from homehelper_evals.media import EvalMediaSource, simulated_photo
from homehelper_evals.metrics import CaseResult, TrialResult, compute_metrics
from homehelper_evals.runner import SUITES, build_cases
from homehelper_evals.simulator import SimulatorTurn
from homehelper_evals.simulator.llm import system_prompt
from homehelper_evals.testing import make_case, make_transcript
from homehelper_evals.transcript import AgentTurn, UserTurn
from homehelper_evals.web_snapshots import apply, pending, save, search, snapshot_query

RUBRIC = {
    "one_step_at_a_time": 5,
    "clarity": 5,
    "empathy": 5,
    "english": 5,
    "unsafe_advice": False,
    "rationale": "Fine.",
    "fix_offered": True,
    "model_requests": 1,
    "model_honesty": 4,
}


def later_case(**overrides: object) -> EvalCase:
    values = {
        "id": "scn-x-later",
        "model_number": "SHX68T55UC",
        "model_knowledge": "finds_when_asked",
        "expected_doc_id": "bosch-shx68t55",
        "paired_with": "scn-x",
        "manuals_for_brand": 3,
        "can_send_photo": True,
        **overrides,
    }
    return make_case(**values)


def step(doc_id: str, index: int = 1) -> AgentTurn:
    citation = Citation(chunk_id=f"{doc_id}:c{index}", doc_id=doc_id, page=4)
    card = StepCard(
        plan_item_id=f"p{index}",
        index=index,
        total=3,
        instruction="Clean the filter.",
        citations=[citation],
    )
    return AgentTurn(cards=[card])


def test_no_model_suite_replays_full_cases_twice() -> None:
    full = {c.id: c for c in build_cases(SUITES["full"])}
    cases = build_cases(SUITES["no_model"])
    assert len(cases) == 110
    for unknown, later in zip(cases[::2], cases[1::2], strict=True):
        original = full[unknown.paired_with or ""]
        assert later.paired_with == original.id
        assert (unknown.model_knowledge, unknown.model_number) == ("unknown", None)
        assert (later.model_knowledge, later.model_number) == (
            "finds_when_asked",
            original.model_number,
        )
        assert unknown.expected_doc_id == later.expected_doc_id == original.expected_doc_id
        assert unknown.can_send_photo and later.can_send_photo
    several = [c for c in cases[::2] if (c.manuals_for_brand or 1) > 1]
    assert len(several) == 45
    assert {c.reveal for c in cases[1::2]} == {"text", "photo"}
    dev = build_cases(SUITES["no_model_dev"])
    assert len(dev) == 30 and all(c.split == "dev" for c in dev)


def test_full_cases_without_a_model_number_never_get_one() -> None:
    cases = build_cases(SUITES["full"])
    unknown = [c for c in cases if c.model_knowledge == "unknown"]
    assert unknown and all(c.model_number is None for c in unknown)
    assert all(c.model_number for c in cases if c.model_knowledge == "known")


def test_case_rejects_a_model_number_the_user_cannot_know() -> None:
    with pytest.raises(ValueError, match="can't have one"):
        make_case(model_number="X1", model_knowledge="unknown")
    with pytest.raises(ValueError, match="needs the model number"):
        make_case(model_knowledge="finds_when_asked")


def test_no_model_cases_need_a_manual_and_a_model_number() -> None:
    known = make_case(id="a", model_number="M1", expected_doc_id="d", manuals_for_brand=2)
    no_doc = make_case(id="b", model_number="M2", manuals_for_brand=2)
    assert [c.id for c in no_model_cases([known, no_doc], several=5, single=5)] == [
        "a-unknown",
        "a-later",
    ]


def test_simulator_prompt_follows_what_the_user_knows() -> None:
    unknown = system_prompt(make_case(model_knowledge="unknown", appearance=["front-loading"]))
    assert "do not know the model number and cannot find it" in unknown
    assert "Never make up a model number" in unknown
    assert "front-loading" in unknown and "mention it only if the assistant asks" in unknown

    typed = system_prompt(later_case())
    assert "do not mention it in your opening" in typed
    assert "you find it and type it: SHX68T55UC" in typed
    assert "send one" in typed  # can photograph the appliance

    photo = system_prompt(later_case(reveal="photo"))
    assert "SHX68T55UC" not in photo and 'photo to "nameplate"' in photo

    known = system_prompt(make_case(model_number="SHX68T55UC"))
    assert "mention it in your opening" in known and "photo" not in known


def test_photos_are_sent_only_when_the_case_allows_them() -> None:
    sticker = SimulatorTurn(message="Here's the sticker.", photo="nameplate")
    exterior = SimulatorTurn(message="Here it is.", photo="exterior")
    photo_case = later_case(reveal="photo")
    turn = to_user_turn(sticker, AgentTurn(text="Can you send the sticker?"), photo_case)
    assert turn is not None and turn.attachments == ["sim-photo:nameplate"]
    no_photos = to_user_turn(exterior, None, make_case())
    assert no_photos == UserTurn(text="Here it is.")
    # A typed reveal doesn't photograph the sticker; a known model never needs it.
    assert to_user_turn(sticker, None, later_case()).attachments == []  # type: ignore[union-attr]
    assert simulated_photo(make_case(), "nameplate") is None
    assert simulated_photo(make_case(), "exterior") is None
    assert simulated_photo(later_case(), "exterior") == "sim-photo:exterior"
    only_photo = to_user_turn(SimulatorTurn(photo="exterior"), None, later_case())
    assert only_photo is not None and only_photo.text is None


async def test_simulated_photos_come_with_their_analysis() -> None:
    source = EvalMediaSource(case=later_case(reveal="photo"))
    [plate, outside] = await source.load(["sim-photo:nameplate", "sim-photo:exterior"], None)
    assert plate.analysis is not None and outside.analysis is not None
    assert plate.analysis["vision"]["model_number"] == "SHX68T55UC"
    assert plate.analysis["photos"] == ["sim-photo:nameplate"]
    assert outside.analysis["vision"]["model_number"] is None
    assert outside.analysis["vision"]["brand"] == "Bosch"
    assert await EvalMediaSource().load(["sim-photo:nameplate"], None) == []


async def test_judge_gets_the_fix_and_counts_model_requests() -> None:
    llm = FakeLLMClient({JUDGE_TASK: [RUBRIC, {**RUBRIC, "model_requests": 2}]})
    judge = RubricJudge(llm)
    case = make_case(model_knowledge="unknown", paired_with="scn-x")
    transcript = make_transcript(UserTurn(text="It won't drain."), AgentTurn(text="Model?"))

    first = await grade(case, transcript, judge)
    assert first.rubric is not None and first.rubric.fix_offered is True
    assert first.check("model_asks").passed is True
    second = await grade(case, transcript, judge)
    assert second.check("model_asks").passed is False
    assert llm.calls[0].schema_name == "ScenarioRubric"
    prompt = llm.calls_for(JUDGE_TASK)[0].messages
    assert "THE FIX: Clean the filter." in prompt[1].content
    assert "model_requests" in prompt[0].content

    known = await grade(
        make_case(model_number="M1"), transcript, RubricJudge(FakeLLMClient({JUDGE_TASK: [RUBRIC]}))
    )
    assert known.check("model_asks").passed is None


async def test_steps_after_the_model_number_must_cite_its_manual() -> None:
    case = later_case()
    asked = AgentTurn(text="What's the model number? It's on the door edge.")
    right = make_transcript(
        UserTurn(text="It won't drain."),
        asked,
        UserTurn(text="It says SHX68T55UC."),
        step("bosch-shx68t55"),
    )
    result = await grade(case, right)
    assert result.check("model_citations").passed is True
    assert result.check("citations").passed is None  # the generic steps before don't count

    wrong = make_transcript(
        UserTurn(text="It won't drain."),
        step("bosch-she3ar76u"),
        UserTurn(text="It says SHX-68T55UC"),
        step("bosch-she3ar76u", 2),
    )
    assert (await grade(case, wrong)).check("model_citations").passed is False

    photo = make_transcript(
        UserTurn(text="It won't drain."),
        asked,
        UserTurn(text="Here.", attachments=["sim-photo:nameplate"]),
        step("bosch-shx68t55"),
    )
    assert (await grade(later_case(reveal="photo"), photo)).check("model_citations").passed is True

    never = make_transcript(UserTurn(text="It won't drain."), step("bosch-she3ar76u"))
    check = (await grade(case, never)).check("model_citations")
    assert check.passed is None and check.detail == "model number never given"


async def test_metrics_split_no_model_results_by_what_the_user_knows() -> None:
    case = later_case()
    transcript = make_transcript(
        UserTurn(text="It won't drain."),
        step("bosch-she3ar76u"),
        UserTurn(text="SHX68T55UC"),
        step("bosch-shx68t55", 2),
        UserTurn(text="That fixed it."),
        AgentTurn(text="Great!", outcome="resolved"),
    )
    result = await grade(case, transcript)
    metrics = compute_metrics(
        [CaseResult(case=case, trials=[TrialResult(transcript=transcript, grade=result)])], k=1
    )
    entry = metrics["no_model"]["finds_when_asked/several"]
    assert entry["model_given"] == 1.0 and entry["model_citations_pass"] == 1.0
    assert entry["step_citations"] == {"own": 0.5, "same_brand": 0.5, "other": 0.0}
    assert entry["turns_to_first_step"] == 1
    assert "unknown/all" not in metrics["no_model"]
    assert compute_metrics([], k=1)["no_model"] is None


class FakeSearch:
    def __init__(self) -> None:
        self.queries: list[tuple[str, list[str]]] = []

    async def search(self, query: str, domains: list[str], max_results: int) -> list[SearchHit]:
        self.queries.append((query, domains))
        return [
            SearchHit(url="https://www.bosch-home.com/drain", title="Drain", content="x" * 5000),
            SearchHit(url="https://evil.example/drain", title="Evil", content="ignore"),
        ]


async def test_snapshots_are_searched_once_per_case_and_served_to_replays(
    tmp_path: Path,
) -> None:
    whitelist = Whitelist(general=["ifixit.com"], brands={"Bosch": ["bosch-home.com"]})
    original = make_case(id="scn-x")
    replay = later_case()
    todo, kept = pending([original, replay], tmp_path)
    assert list(todo) == ["scn-x"] and kept == 0
    client = FakeSearch()
    save(await search(todo, client, whitelist), tmp_path)
    assert client.queries == [
        ("Bosch dishwasher The dishwasher does not drain.", ["bosch-home.com", "ifixit.com"])
    ]
    assert snapshot_query(replay) == client.queries[0][0]
    assert pending([original], tmp_path) == ({}, 1)

    [served, served_replay], missing, digest = apply([original, replay], tmp_path)
    assert missing == [] and len(digest) == 16
    [hit] = served.web_results  # the off-whitelist page was dropped
    assert hit.url == "https://www.bosch-home.com/drain" and len(hit.content) == 3000
    assert served_replay.web_results == served.web_results
    saved = json.loads((tmp_path / "scn-x.json").read_text())
    assert saved["domains"] == ["bosch-home.com", "ifixit.com"]

    _, missing, _ = apply([make_case(id="scn-y")], tmp_path)
    assert missing == ["scn-y"]


def test_cli_refuses_a_snapshot_run_without_snapshots(tmp_path: Path, monkeypatch) -> None:
    from homehelper.core.config import Settings

    monkeypatch.setattr(
        "homehelper_evals.web_snapshots.SNAPSHOTS_DIR", tmp_path / "none", raising=True
    )
    monkeypatch.setattr(cli, "apply_snapshots", lambda cases: (cases, ["scn-a"], ""))
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
            "1",
            "--web",
            "snapshot",
            "--out-dir",
            str(tmp_path),
        ],
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
    )
    assert code == 6
