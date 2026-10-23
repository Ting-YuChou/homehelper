"""Graders (spec §16.3): state, deterministic, and the LLM rubric judge."""

from homehelper.llm import LLMError
from homehelper_evals.cases import EvalCase
from homehelper_evals.graders.base import Check, Grade, RubricScores
from homehelper_evals.graders.deterministic import deterministic_checks
from homehelper_evals.graders.rubric import (
    ExpectationVerdict,
    RubricJudge,
    expectation_check,
    judge_safety_check,
)
from homehelper_evals.graders.state import state_checks
from homehelper_evals.transcript import Transcript

__all__ = ["Check", "Grade", "RubricJudge", "RubricScores", "grade"]


# Cases where the LLM safety check must actually run; elsewhere a judge outage is only counted.
STRICT_JUDGE_KINDS = frozenset({"safety", "injection"})


async def grade(
    case: EvalCase,
    transcript: Transcript,
    judge: RubricJudge | None = None,
    *,
    strict_judge: bool = False,
) -> Grade:
    scores, unavailable = None, False
    if judge is not None and transcript.agent_turns:
        try:
            scores = await judge.score(case, transcript)
        except LLMError:
            unavailable = True
    expected = case.assertions.expected_behavior is not None
    verdict: ExpectationVerdict | None = None
    expectation_unavailable = False
    if judge is not None and expected and transcript.agent_turns:
        try:
            verdict = await judge.expectation(case, transcript)
        except LLMError:
            expectation_unavailable = unavailable = True
    strict = strict_judge or case.kind in STRICT_JUDGE_KINDS
    checks = [
        *state_checks(case, transcript),
        *deterministic_checks(case, transcript),
        judge_safety_check(
            scores,
            enabled=judge is not None,
            unavailable=scores is None and unavailable,
            strict=strict,
        ),
        expectation_check(
            verdict,
            applies=expected,
            enabled=judge is not None,
            unavailable=expectation_unavailable,
            strict=strict,
        ),
    ]
    return Grade(checks=checks, rubric=scores, judge_unavailable=unavailable)
