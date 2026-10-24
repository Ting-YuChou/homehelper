"""One turn's input, normalized into the signals predicates read.

A turn is either free text understood by NLU, or a card button (`StructuredAction`) that bypasses
NLU (spec §7.3). Both become the same `TurnSignals`, so predicates never care which it was. Text
typed with a step button may still add details about the appliance (`CARD_TEXT_SLOTS`): the
button decides the step's result, the words what the appliance is (ADR-013).
"""

from typing import Literal

from pydantic import BaseModel, Field

from homehelper.agent.engine.perception import MediaInput, PerceivedSlot
from homehelper.agent.guardrails.rules import ESCALATING_HAZARDS
from homehelper.agent.state import HazardSignal, Intent, NLUResult, SlotUpdate
from homehelper.channels.events import InboundMessage, StructuredAction

Feedback = Literal["fixed", "not_fixed", "cannot_do"]

CONFIRM_VALUES = frozenset({"yes", "y", "true", "confirm", "confirmed", "correct"})
DENY_VALUES = frozenset({"no", "n", "false", "deny", "denied", "incorrect", "wrong"})
FEEDBACK_VALUES: frozenset[str] = frozenset({"fixed", "not_fixed", "cannot_do"})
# What a message sent with a step button may still tell (its NLU is read only for these).
# Not the brand: words typed with a button may be about another appliance.
CARD_TEXT_SLOTS = ("model_number", "badge")
CARD_TEXT_PREFIXES = ("trait_",)


def appliance_detail(name: str) -> bool:
    return name in CARD_TEXT_SLOTS or name.startswith(CARD_TEXT_PREFIXES)


class TurnInput(BaseModel):
    text: str | None = None
    nlu: NLUResult | None = None
    action: StructuredAction | None = None
    media: MediaInput | None = None  # what the turn's photos and videos showed (spec §11)

    @classmethod
    def from_message(
        cls,
        message: InboundMessage,
        nlu: NLUResult | None = None,
        media: MediaInput | None = None,
    ) -> "TurnInput":
        return cls(text=message.text, nlu=nlu, action=message.action, media=media)


class TurnSignals(BaseModel):
    intent: Intent | None = None
    feedback: Feedback | None = None
    confirmed: bool | None = None  # True = confirm, False = deny
    booking_slot_id: str | None = None
    slot_updates: list[SlotUpdate] = Field(default_factory=list)
    hazards: list[HazardSignal] = Field(default_factory=list)
    # Non-escalating hazards that escalate this turn: G-SAFE-05 reported again after its warning.
    persisting: list[HazardSignal] = Field(default_factory=list)
    sentiment: Literal["neutral", "frustrated", "confused"] | None = None
    resume_issue: str | None = None  # issue id from an IssuesCard button (ADR-007)
    close_issue: str | None = None
    rejected_action: str | None = None  # why a structured action was ignored
    from_card: bool = False  # set by a card button rather than by what the user wrote
    perceived: list[PerceivedSlot] = Field(default_factory=list)  # from photos and videos

    @property
    def escalating_hazards(self) -> list[HazardSignal]:
        return [h for h in self.hazards if h in ESCALATING_HAZARDS or h in self.persisting]


def signals_from_input(turn: TurnInput) -> TurnSignals:
    """Map NLU output or a card action to signals. A card action wins over NLU if both are set."""
    signals = _from_words_or_card(turn)
    if turn.media is not None and turn.media.slot_updates:
        signals = signals.model_copy(update={"perceived": list(turn.media.slot_updates)})
    return signals


def _from_words_or_card(turn: TurnInput) -> TurnSignals:
    if turn.action is not None:
        signals = _from_action(turn.action)
        if turn.action.type == "step_result" and turn.nlu is not None:
            details = [u for u in turn.nlu.slot_updates if appliance_detail(u.name)]
            signals = signals.model_copy(update={"slot_updates": details})
        return signals
    nlu = turn.nlu
    if nlu is None:
        return TurnSignals()
    feedback: Feedback | None = None
    if nlu.step_feedback is not None and nlu.step_feedback != "unclear":
        feedback = nlu.step_feedback
    confirmed = {"confirm": True, "deny": False}.get(nlu.intent)
    return TurnSignals(
        intent=nlu.intent,
        feedback=feedback,
        confirmed=confirmed,
        slot_updates=list(nlu.slot_updates),
        sentiment=nlu.user_sentiment,
    )


def _from_action(action: StructuredAction) -> TurnSignals:
    return _action_signals(action).model_copy(update={"from_card": True})


def _action_signals(action: StructuredAction) -> TurnSignals:
    value = action.value.strip()
    match action.type:
        case "step_result":
            if value in FEEDBACK_VALUES:
                feedback: Feedback = value  # type: ignore[assignment]
                return TurnSignals(feedback=feedback)
        case "confirm_appliance":
            if value.lower() in CONFIRM_VALUES:
                return TurnSignals(intent="confirm", confirmed=True)
            if value.lower() in DENY_VALUES:
                return TurnSignals(intent="deny", confirmed=False)
        case "select_booking_slot":
            if value:
                return TurnSignals(booking_slot_id=value)
        case "resume_issue":
            if value:
                return TurnSignals(resume_issue=value)
        case "close_issue":
            if value:
                return TurnSignals(close_issue=value)
    return TurnSignals(rejected_action=f"unrecognized {action.type} value {action.value!r}")
