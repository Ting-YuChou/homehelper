"""Multi-issue cases (ADR-007): the dataset, the runner's switch and return turns, and grading."""

import pytest

from homehelper.agent.protocol import IssueSnapshot
from homehelper.channels.events import IssueOption, IssuesCard, StepCard, StructuredAction
from homehelper.knowledge.schemas import Citation
from homehelper_evals.agents import MultiIssueOracleAgent
from homehelper_evals.cases import EvalCase, IssueSpec, load_dataset
from homehelper_evals.conversation import run_conversation
from homehelper_evals.graders import grade
from homehelper_evals.multi_issue import RETURN, SWITCH, focus, runner_turn
from homehelper_evals.simulator import ScriptedUserSimulator
from homehelper_evals.transcript import AgentTurn, Transcript, UserTurn


def spec(category: str, brand: str, fix: str, doc_id: str, **extra: object) -> IssueSpec:
    return IssueSpec.model_validate(
        {
            "category": category,
            "brand": brand,
            "model_number": "M1",
            "scenario": f"The {category} is broken.",
            "solution_steps": ["Check the power.", fix],
            "root_cause_step": 2,
            "expected_outcomes": ["resolved"],
            "expected_doc_id": doc_id,
            **extra,
        }
    )


def multi_case(return_via: str = "card", **first: object) -> EvalCase:
    issues = [
        spec("dishwasher", "Bosch", "Clean the filter.", "bosch-1", **first),
        spec("dryer", "LG", "Clean the lint screen.", "lg-1"),
    ]
    return EvalCase.model_validate(
        {
            "id": "multi-test",
            "kind": "multi_issue",
            **issues[0].model_dump(),
            "issues": [i.model_dump() for i in issues],
            "return_via": return_via,
            "max_turns": 20,
        }
    )


def issue(issue_id: str, status: str, outcome: str | None = None) -> IssueSnapshot:
    return IssueSnapshot.model_validate(
        {
            "issue_id": issue_id,
            "journey": "troubleshoot",
            "summary": "x",
            "status": status,
            "outcome": outcome,
        }
    )


def step_card(issue_id: str, doc_id: str) -> StepCard:
    citation = Citation(chunk_id="c", doc_id=doc_id, page=1)
    return StepCard(
        plan_item_id="p1",
        index=1,
        total=2,
        instruction="Do it.",
        issue_id=issue_id,
        citations=[citation],
    )


def test_dataset_pairs_two_appliances() -> None:
    cases = load_dataset("multi_issue")
    assert len(cases) >= 10
    for case in cases:
        assert case.kind == "multi_issue" and len(case.issues) == 2
        assert case.issues[0].category != case.issues[1].category
        assert all(i.model_number and i.expected_doc_id for i in case.issues)
    assert {case.return_via for case in cases} == {"card", "appliance", "confirm", "close"}
    closed = [case for case in cases if case.return_via == "close"]
    assert all(case.issues[0].expected_outcomes == ["abandoned"] for case in closed)
    assert len({case.persona for case in cases}) > 1  # each keeps its first scenario's persona


def test_only_multi_issue_cases_list_issues() -> None:
    with pytest.raises(ValueError, match="2\\+ issues"):
        EvalCase.model_validate({**multi_case().model_dump(), "kind": "scenario", "max_turns": 12})


def test_runner_switches_after_the_first_step_card() -> None:
    case = multi_case()
    opening = [UserTurn(text="My dishwasher is broken")]
    assert runner_turn(case, [*opening, AgentTurn(text="Which model?")]) is None
    first_step = AgentTurn(cards=[step_card("iss_1", "bosch-1")], issues=[issue("iss_1", "active")])
    switch = runner_turn(case, [*opening, first_step])
    assert switch is not None and switch.script == SWITCH
    assert switch.text and switch.text.startswith("Also, my LG dryer (model M1)")
    assert focus(case, [*opening, first_step, switch]).category == case.issues[1].category


def test_runner_returns_once_the_second_issue_is_settled() -> None:
    switched = [UserTurn(text="hi"), UserTurn(text="Also...", script=SWITCH)]
    busy = AgentTurn(issues=[issue("iss_1", "paused"), issue("iss_2", "active")])
    assert runner_turn(multi_case(), [*switched, busy]) is None
    card = IssuesCard(issues=[IssueOption(issue_id="iss_1", summary="Bosch dishwasher")])
    done = AgentTurn(
        cards=[card], issues=[issue("iss_1", "paused"), issue("iss_2", "ended", "resolved")]
    )
    no_card = done.model_copy(update={"cards": []})

    def back(return_via: str, last: AgentTurn) -> UserTurn:
        turn = runner_turn(multi_case(return_via), [*switched, last])
        assert turn is not None and turn.script == RETURN
        return turn

    assert back("card", done).action == StructuredAction(type="resume_issue", value="iss_1")
    assert back("card", no_card).text == "Now, back to my Bosch dishwasher from before."
    assert back("close", done).action == StructuredAction(type="close_issue", value="iss_1")
    assert back("confirm", done).text == "Yes, let's go back to the other problem."
    assert back("appliance", done).text and "Bosch dishwasher" in (
        back("appliance", done).text or ""
    )
    # The first problem was already finished, so there is nothing to go back to.
    finished = done.model_copy(
        update={
            "issues": [issue("iss_1", "ended", "resolved"), issue("iss_2", "ended", "resolved")]
        }
    )
    assert runner_turn(multi_case(), [*switched, finished]) is None
    after = [*switched, done, back("card", done)]
    assert focus(multi_case(), after).category == multi_case().issues[0].category


async def test_oracle_pipeline_passes_every_return_path() -> None:
    for return_via in ("card", "appliance", "confirm", "close"):
        first = {"expected_outcomes": ["abandoned"]} if return_via == "close" else {}
        case = multi_case(return_via, **first)
        transcript = await run_conversation(
            case, MultiIssueOracleAgent(case), ScriptedUserSimulator()
        )
        result = await grade(case, transcript)
        assert result.success, (return_via, result.failed(), transcript.end_reason)


def _graded_checks(case: EvalCase, transcript: Transcript) -> dict[str, bool | None]:
    from homehelper_evals.graders.deterministic import citation_check
    from homehelper_evals.graders.state import issue_outcomes_check, issues_offered_check

    return {
        "issue_outcomes": issue_outcomes_check(case, transcript).passed,
        "issues_offered": issues_offered_check(case, transcript).passed,
        "citations": citation_check(case, transcript).passed,
    }


def test_per_issue_grading_catches_wrong_outcomes_offers_and_manuals() -> None:
    from homehelper.agent.protocol import AgentSnapshot

    case = multi_case()
    turns = [
        UserTurn(text="hi"),
        AgentTurn(cards=[step_card("iss_1", "bosch-1")], issues=[issue("iss_1", "active")]),
        UserTurn(text="Also...", script=SWITCH),
        # Cites the dishwasher manual while working on the dryer: cross-contaminated retrieval.
        AgentTurn(
            cards=[step_card("iss_2", "bosch-1")],
            issues=[issue("iss_1", "paused"), issue("iss_2", "active")],
        ),
    ]
    snapshot = AgentSnapshot(
        conversation_id="c",
        issues=[issue("iss_1", "paused"), issue("iss_2", "ended", "resolved")],
    )
    transcript = Transcript(
        case_id=case.id,
        trial=0,
        conversation_id="c",
        turns=turns,
        end_reason="user_done",
        snapshot=snapshot,
    )
    assert _graded_checks(case, transcript) == {
        "issue_outcomes": False,  # iss_1 never finished
        "issues_offered": False,
        "citations": False,
    }
