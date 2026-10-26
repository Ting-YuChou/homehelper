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
    "damaged_cord",
    "refrigerant",
    "high_voltage_internal",
    "injury",
]

StepFeedback = Literal["fixed", "not_fixed", "cannot_do", "unclear"]

PlanItemStatus = Literal["pending", "presented", "done_not_fixed", "fixed", "skipped"]

# What a plan was built on (ADR-013): the model number's manual, the one manual left once what
# the appliance looks like ruled out the others (or the brand has only one), or several.
PlanScope = Literal["model", "identified", "generic"]

DecisionKind = Literal[
    "route", "transition", "skip", "guardrail", "slot", "plan", "supervisor", "tool"
]


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
    requires_power: bool = False  # powered, running, given power back, or an outlet/plug/cord
    requires_tools: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    status: PlanItemStatus = "pending"
    warranty_warning: bool = False  # G-WARR-01: disassembly while under warranty
    safety_rule: str | None = None  # set on items inserted by code, e.g. "G-SAFE-06"
    general: bool = False  # from several models' manuals: not specific to the user's (ADR-013)


class PlanBasis(BaseModel):
    """The manuals a plan was built on and what identified them (ADR-013). A turn that tells
    the manuals apart better than this (a model number, what the appliance looks like) builds
    the plan again."""

    scope: PlanScope
    doc_ids: list[str] = Field(default_factory=list)
    brand: str | None = None
    model_number: str | None = None
    traits: dict[str, str] = Field(default_factory=dict)  # trait name -> value (features.yaml)
    badge: str | None = None


class Decision(BaseModel):
    """One explainable decision (spec P7): a transition, guardrail hit, skip, or plan edit."""

    kind: DecisionKind
    journey: str | None = None
    from_step: str | None = None
    to_step: str | None = None
    predicate: str | None = None
    rule_id: str | None = None  # guardrail rule, e.g. "G-SAFE-01"
    reason: str


class ProfileAppliance(BaseModel):
    """An appliance from the user's profile (MCP `user_profile`)."""

    appliance_id: str
    category: str
    brand: str
    model_number: str
    nickname: str | None = None


class UserContext(BaseModel):
    """The signed-in user's profile, read by `load_context` every turn (spec §12.2). Guests have
    none, so tools that act for a user are unavailable to them."""

    zip_code: str | None = None
    appliances: list[ProfileAppliance] = Field(default_factory=list)


class OfferedSlot(BaseModel):
    """A technician visit offered on a BookingSlots card (from `service_booking.list_slots`)."""

    slot_id: str
    starts_at: str  # ISO 8601
    technician: str


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
    plan_basis: PlanBasis | None = None
    appliance_id: str | None = None  # the profile appliance this issue is about


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
    profile: UserContext | None = None
    # The active issue owns the fields from `active_journey` to `appliance_id`. Journeys that
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
    # G-SAFE-08: hazards after which the user was told to cut the power, keyed by issue
    # ("issue:<id>"), by an appliance named in the text, "*" (a gas smell) or "unassigned".
    power_off: dict[str, list[str]] = Field(default_factory=dict)
    # G-SAFE-05's power-off warning was given for the current journey (once per problem).
    water_warning_given: bool = False
    frustrated_turns: int = 0  # consecutive turns with user_sentiment == "frustrated" (G-LOOP-01)
    selected_booking_slot: str | None = None  # from a BookingSlots card; read by the `book` action
    offered_slots: list[OfferedSlot] = Field(default_factory=list)  # only these can be booked
    last_retrieval: RetrievalResult | None = None
    plan_basis: PlanBasis | None = None
    appliance_id: str | None = None  # the profile appliance of the active issue, once linked
    # Appliance categories whose model number the user was asked for, once per conversation.
    model_asked: list[str] = Field(default_factory=list)
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
