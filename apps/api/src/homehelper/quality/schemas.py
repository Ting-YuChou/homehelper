"""Shared vocabulary of the quality loop (spec §17.2)."""

from typing import Literal, get_args

IssueType = Literal[
    "wrong_diagnosis",
    "unsafe",
    "hallucination",
    "wrong_manual",
    "too_many_steps_at_once",
    "tone",
    "missed_escalation",
    "other",
]
ISSUE_TYPES: tuple[str, ...] = get_args(IssueType)
Verdict = Literal["correct", "incorrect"]
