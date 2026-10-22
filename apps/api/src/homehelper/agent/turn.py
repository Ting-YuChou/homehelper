"""LangGraph state for one conversation (spec §7.3): the journey `AgentState` plus what the graph
itself needs to remember (transcript, retrieved citations), and per-turn scratch data.

Only the fields of `GraphState` are checkpointed. `TurnScratch` is reset by `load_context` at
the start of every turn, so nothing in it outlives the turn that produced it.
"""

from typing import Literal

from pydantic import BaseModel, Field

from homehelper.agent.guardrails.templates import FixedReply
from homehelper.agent.protocol import ToolCall
from homehelper.agent.state import AgentState, NLUResult
from homehelper.agent.tools import ToolOutcome
from homehelper.channels.events import InboundMessage
from homehelper.knowledge.schemas import CategoryId, Citation, RetrievalResult

MAX_TRANSCRIPT_LINES = 24  # what NLU and the responder see of the conversation


class TranscriptLine(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class AgentReply(BaseModel):
    """The responder's output. Cards are built by code from state, never by the LLM."""

    message: str = Field(description="The reply shown to the user.")
    citation_ids: list[str] = Field(
        default_factory=list,
        description="Ids of the manual excerpts that support technical statements in the reply.",
    )


class SupervisorVerdict(BaseModel):
    action: Literal["pass", "revise", "block"]
    reasons: list[str] = Field(default_factory=list)


class TurnScratch(BaseModel):
    message: InboundMessage | None = None
    nlu: NLUResult | None = None
    fixed_replies: list[FixedReply] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)
    side_question: bool = False
    # Retrieval the responder may cite this turn: the step's own, or a side question's.
    retrieval: RetrievalResult | None = None
    # MCP results this turn (step actions, then the responder's calls); facts the reply may use.
    tool_results: list[ToolOutcome] = Field(default_factory=list)
    reply: AgentReply | None = None
    verdict: SupervisorVerdict | None = None
    revisions: int = 0


class GraphState(BaseModel):
    agent: AgentState | None = None  # created by `load_context` on the first turn
    transcript: list[TranscriptLine] = Field(default_factory=list)
    # Every chunk retrieved in this conversation, so plan items can cite across turns.
    citations: dict[str, Citation] = Field(default_factory=dict)
    # The latest English search query NLU wrote for a problem or how-to message.
    search_query: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    turn: TurnScratch = Field(default_factory=TurnScratch)

    @property
    def state(self) -> AgentState:
        assert self.agent is not None, "load_context runs first"
        return self.agent


# Types the checkpointer may revive (LangGraph's msgpack allowlist).
CHECKPOINT_TYPES: list[type] = [
    AgentState,
    CategoryId,
    TurnScratch,
    TranscriptLine,
    Citation,
    ToolCall,
    ToolOutcome,
]
