"""Per-conversation agent state and the NLU output schema (spec §7.2, §7.3)."""

from typing import Literal

from pydantic import BaseModel, Field

from homehelper.agent.protocol import Outcome
from homehelper.knowledge.schemas import RetrievalResult

SlotSource = Literal["user", "vision", "video", "profile", "inferred"]

Intent = Literal[
    "report_problem",
    "ask_how_to",
    "step_feedback",
    "ask_parts",
    "my_appliances",
    "book_technician",
    "confirm",
    "deny",
    "small_talk",
    "out_of_scope",
    "other",
]

HazardSignal = Literal[
    "gas_smell",
    "smoke_or_burning",
    "sparks",
    "water_near_electric",
    "refrigerant",
    "high_voltage_internal",
    "injury",
]

StepFeedback = Literal["fixed", "not_fixed", "cannot_do", "unclear"]

PlanItemStatus = Literal["pending", "presented", "done_not_fixed", "fixed", "skipped"]

DecisionKind = Literal["route", "transition", "skip", "guardrail", "slot", "plan", "supervisor"]


class SlotValue(BaseModel):
    value: str
    source: SlotSource
    confidence: float = Field(ge=0, le=1)
    confirmed: bool = False  # low-confidence values must be confirmed by the user


class PlanItem(BaseModel):
    id: str
    instruction: str
    citation_ids: list[str] = Field(default_factory=list)  # KB chunk ids
    requires_disassembly: bool = False
    requires_tools: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    status: PlanItemStatus = "pending"
    warranty_warning: bool = False  # G-WARR-01: disassembly while under warranty
    safety_rule: str | None = None  # set on items inserted by code, e.g. "G-SAFE-06"


class Decision(BaseModel):
    """One explainable decision (spec P7): a transition, guardrail hit, skip, or plan edit."""

    kind: DecisionKind
    journey: str | None = None
    from_step: str | None = None
    to_step: str | None = None
    predicate: str | None = None
    rule_id: str | None = None  # guardrail rule, e.g. "G-SAFE-01"
    reason: str


class PausedIssue(BaseModel):
    """An unfinished issue set aside by a topic or appliance switch (spec §7.4, ADR-007): the
    progress of its journey, restored as-is when the user comes back to it."""

    issue_id: str
    journey: str
    summary: str
    step_id: str | None
    slots: dict[str, SlotValue] = Field(default_factory=dict)
    plan: list[PlanItem] = Field(default_factory=list)
    plan_cursor: int = 0
    step_attempts: dict[str, int] = Field(default_factory=dict)
    last_retrieval: RetrievalResult | None = None  # the excerpts its plan cites


class IssueRecord(BaseModel):
    """Every issue opened in the conversation; `outcome` is set when it ends."""

    issue_id: str  # "iss_1", "iss_2", ... in opening order
    journey: str
    summary: str = ""  # built by code from the slots, e.g. "Bosch washing machine: not draining"
    appliance_category: str | None = None
    outcome: Outcome | None = None


class AgentState(BaseModel):
    conversation_id: str
    release_id: str
    user_id: str | None = None
    # The active issue owns the fields from `active_journey` to `last_retrieval`. Journeys that
    # end on entry (the out-of-scope decline) are replies, not issues, and have no id.
    active_issue_id: str | None = None
    active_journey: str | None = None
    paused_issues: list[PausedIssue] = Field(default_factory=list)  # oldest first
    issues: list[IssueRecord] = Field(default_factory=list)
    step_id: str | None = None
    slots: dict[str, SlotValue] = Field(default_factory=dict)
    plan: list[PlanItem] = Field(default_factory=list)
    plan_cursor: int = 0
    step_attempts: dict[str, int] = Field(default_factory=dict)
    hazard_flags: list[str] = Field(default_factory=list)
    # G-SAFE-05's power-off warning was given for the current journey (once per problem).
    water_warning_given: bool = False
    frustrated_turns: int = 0  # consecutive turns with user_sentiment == "frustrated" (G-LOOP-01)
    selected_booking_slot: str | None = None  # from a BookingSlots card; read by the `book` action
    last_retrieval: RetrievalResult | None = None
    # The once-per-issue reminder about paused issues was given, or the user declined an offer.
    paused_reminder_used: bool = False
    outcome: Outcome | None = None  # summary over all issues (spec §7.4)
    decision_log: list[Decision] = Field(default_factory=list)


class SlotUpdate(BaseModel):
    name: str
    value: str


class NLUResult(BaseModel):
    """What the user's message means for the conversation."""

    intent: Intent
    # A list of name/value items, not dict[str, str]: free-form maps become `additionalProperties`
    # in JSON schema, which strict structured-output modes reject.
    slot_updates: list[SlotUpdate] = Field(default_factory=list)
    step_feedback: StepFeedback | None = None
    hazard_signals: list[HazardSignal] = Field(default_factory=list)
    search_query_en: str | None = None
    user_sentiment: Literal["neutral", "frustrated", "confused"] = "neutral"
