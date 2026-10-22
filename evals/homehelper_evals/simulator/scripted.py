"""Deterministic, LLM-free simulated user for CI and pipeline tests.

It matches step instructions to the root-cause step by word overlap, which is much cruder than
the LLM simulator's semantic match; use it to exercise the runner, not to score an agent.
"""

import re

from homehelper.channels.events import ApplianceConfirmCard, BookingSlotsCard
from homehelper.knowledge.model_numbers import normalize_model
from homehelper_evals.cases import EvalCase
from homehelper_evals.simulator.base import SimulatorTurn
from homehelper_evals.transcript import AgentTurn, Turn, UserTurn

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "be",
        "by",
        "check",
        "do",
        "does",
        "for",
        "from",
        "if",
        "in",
        "is",
        "it",
        "make",
        "of",
        "on",
        "or",
        "sure",
        "that",
        "the",
        "this",
        "to",
        "with",
        "you",
        "your",
    ]
)
MATCH_THRESHOLD = 0.6
MAX_IDLE_REPLIES = 2  # free-text answers before giving up when the agent offers no step


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}


def same_step(instruction: str, root_cause: str) -> bool:
    """True when most of the root-cause step's content words appear in the instruction."""
    target = content_words(root_cause)
    if not target:
        return False
    return len(target & content_words(instruction)) / len(target) >= MATCH_THRESHOLD


def opening_message(case: EvalCase) -> str:
    appliance = " ".join(
        p
        for p in [case.brand, case.category.value.replace("_", " ") if case.category else None]
        if p
    )
    if not appliance:
        return case.scenario
    model = f" (model {case.model_number})" if case.model_number else ""
    return f"Hi, I have a problem with my {appliance}{model}. {case.scenario}"


class ScriptedUserSimulator:
    async def next_turn(self, case: EvalCase, history: list[Turn]) -> SimulatorTurn:
        if not history:
            return SimulatorTurn(message=opening_message(case))
        last = history[-1]
        if not isinstance(last, AgentTurn):
            return SimulatorTurn(done=True)
        if last.step_cards:
            instruction = last.step_cards[-1].instruction
            fixed = (
                case.user_fixable
                and case.root_cause_text is not None
                and same_step(instruction, case.root_cause_text)
            )
            return SimulatorTurn(step_result="fixed" if fixed else "not_fixed")
        for card in last.cards_of(ApplianceConfirmCard):
            matches = (
                card.category in (None, case.category)
                and (card.brand is None or (case.brand or "").lower() == card.brand.lower())
                and (
                    card.model_number is None
                    or case.model_number is None
                    or normalize_model(card.model_number) == normalize_model(case.model_number)
                )
            )
            return SimulatorTurn(confirm_appliance="yes" if matches else "no")
        slots = [slot for card in last.cards_of(BookingSlotsCard) for slot in card.slots]
        if slots:
            return SimulatorTurn(booking_slot_id=slots[0].slot_id)
        idle = 0
        for turn in reversed(history):
            if isinstance(turn, UserTurn):
                if turn.action is not None or turn.scripted:
                    break
                idle += 1
        if idle > MAX_IDLE_REPLIES:
            return SimulatorTurn(done=True)
        return SimulatorTurn(message="I'm not sure. What should I try?")
