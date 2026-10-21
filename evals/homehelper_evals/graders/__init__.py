"""Graders (spec §16.3): state, deterministic, and the LLM rubric judge."""

from homehelper_evals.cases import EvalCase
from homehelper_evals.graders.base import Check, Grade, RubricScores
from homehelper_evals.graders.deterministic import deterministic_checks
from homehelper_evals.graders.rubric import RubricJudge, judge_safety_check
from homehelper_evals.graders.state import state_checks
from homehelper_evals.transcript import Transcript

__all__ = ["Check", "Grade", "RubricJudge", "RubricScores", "grade"]


async def grade(case: EvalCase, transcript: Transcript, judge: RubricJudge | None = None) -> Grade:
    scores = await judge.score(case, transcript) if judge else None
    checks = [
        *state_checks(case, transcript),
        *deterministic_checks(case, transcript),
        judge_safety_check(scores, enabled=judge is not None),
    ]
    return Grade(checks=checks, rubric=scores)
