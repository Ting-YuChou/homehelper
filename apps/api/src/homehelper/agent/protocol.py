"""The interface every agent implementation exposes: the journey agent, the baseline agent (M2-06),
and the HTTP client the eval runner uses for end-to-end runs."""

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from homehelper.channels.events import AgentEvent, InboundMessage

Outcome = Literal["resolved", "escalated", "abandoned", "out_of_scope"]


class ToolCall(BaseModel):
    name: str  # e.g. "service_booking.book"
    arguments: dict[str, Any] = Field(default_factory=dict)  # never includes `user_id`
    source: Literal["action", "llm"] = "action"  # a step action (code) or the responder
    ok: bool = True


IssueStatus = Literal["active", "paused", "ended"]


class IssueSnapshot(BaseModel):
    """One problem the user raised (ADR-007). `outcome` is final once ended; for the active issue
    it is the current step's provisional outcome (e.g. `escalated` at a handoff)."""

    issue_id: str
    journey: str
    appliance_category: str | None = None
    summary: str
    status: IssueStatus
    outcome: Outcome | None = None


class AgentSnapshot(BaseModel):
    """What graders may inspect after a conversation (spec §16.3 state grader)."""

    conversation_id: str
    outcome: Outcome | None = None  # summary over all issues (spec §7.4)
    journey: str | None = None
    step: str | None = None
    hazard_flags: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    decision_log: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[IssueSnapshot] = Field(default_factory=list)


class AgentRuntime(Protocol):
    def handle(self, message: InboundMessage) -> AsyncIterator[AgentEvent]:
        """Process one user turn and stream events until `message.completed` or `error`."""
        ...

    async def snapshot(self, conversation_id: str) -> AgentSnapshot: ...
