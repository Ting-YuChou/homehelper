"""What one simulated conversation looked like, as recorded by the runner and read by graders."""

from typing import Annotated, Literal, TypeVar

from pydantic import BaseModel, Field

from homehelper.agent.protocol import AgentSnapshot, Outcome
from homehelper.channels.events import (
    BookingSlotsCard,
    Card,
    HandoffCard,
    SafetyCard,
    StepCard,
    StructuredAction,
)
from homehelper.knowledge.schemas import Citation
from homehelper.llm import LLMUsage

TERMINAL_OUTCOMES: frozenset[Outcome] = frozenset(
    {"resolved", "escalated", "abandoned", "out_of_scope"}
)

EndReason = Literal["outcome", "user_done", "turn_limit", "error"]

C = TypeVar("C")


class UserTurn(BaseModel):
    role: Literal["user"] = "user"
    text: str | None = None
    action: StructuredAction | None = None
    scripted: bool = False


class AgentTurn(BaseModel):
    role: Literal["agent"] = "agent"
    text: str = ""
    cards: list[Card] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    journey: str | None = None
    step: str | None = None
    error: str | None = None  # ErrorEvent code, or the exception the runtime raised
    latency_ms: float = 0
    # State right after this turn (from `AgentRuntime.snapshot`).
    outcome: Outcome | None = None
    hazard_flags: list[str] = Field(default_factory=list)

    def cards_of(self, card_type: type[C]) -> list[C]:
        return [card for card in self.cards if isinstance(card, card_type)]

    @property
    def step_cards(self) -> list[StepCard]:
        return self.cards_of(StepCard)

    @property
    def escalates(self) -> bool:
        """Hands off or stops DIY: escalated outcome, or a safety / handoff card."""
        return (
            self.outcome == "escalated"
            or bool(self.cards_of(SafetyCard))
            or bool(self.cards_of(HandoffCard))
        )

    @property
    def offers_booking(self) -> bool:
        return bool(self.cards_of(BookingSlotsCard))


Turn = Annotated[UserTurn | AgentTurn, Field(discriminator="role")]


class Transcript(BaseModel):
    case_id: str
    trial: int
    conversation_id: str
    turns: list[Turn] = Field(default_factory=list)
    end_reason: EndReason
    snapshot: AgentSnapshot | None = None
    error: str | None = None
    usage: list[LLMUsage] = Field(default_factory=list)
    duration_ms: float = 0

    @property
    def user_turns(self) -> list[UserTurn]:
        return [turn for turn in self.turns if isinstance(turn, UserTurn)]

    @property
    def agent_turns(self) -> list[AgentTurn]:
        return [turn for turn in self.turns if isinstance(turn, AgentTurn)]

    @property
    def outcome(self) -> Outcome | None:
        return self.snapshot.outcome if self.snapshot else None

    def reply_to(self, user_index: int) -> AgentTurn | None:
        """The agent turn that answered the `user_index`-th (0-based) user turn."""
        seen = -1
        for position, turn in enumerate(self.turns):
            if isinstance(turn, UserTurn):
                seen += 1
                if seen == user_index:
                    following = self.turns[position + 1 : position + 2]
                    if following and isinstance(following[0], AgentTurn):
                        return following[0]
                    return None
        return None

    def agent_turns_after(self, user_index: int) -> list[AgentTurn]:
        seen = -1
        result: list[AgentTurn] = []
        for turn in self.turns:
            if isinstance(turn, UserTurn):
                seen += 1
            elif seen >= user_index:
                result.append(turn)
        return result
