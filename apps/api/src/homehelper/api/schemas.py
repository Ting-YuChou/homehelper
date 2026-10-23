"""Request and response bodies of the `/v1` REST API (spec §13.2). These become the OpenAPI
schema the web app's TypeScript types are generated from."""

from datetime import date, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from homehelper.agent.protocol import Outcome
from homehelper.channels.events import Card, StructuredAction
from homehelper.knowledge.schemas import CategoryId, Citation
from homehelper.mcp_servers.schemas import RepairOutcome, WarrantyState
from homehelper.quality.eval_reports import CaseSummary
from homehelper.quality.regression import RegressionAssertions, RegressionCase
from homehelper.quality.schemas import IssueType, Verdict

Rating = Literal["up", "down"]
Role = Literal["user", "assistant", "system"]
AttachmentKind = Literal["image", "video"]


class _FromRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(_FromRow):
    id: str
    display_name: str
    is_demo: bool


class DemoUserOut(BaseModel):
    id: str
    display_name: str
    description: str | None = None


class DemoLoginRequest(BaseModel):
    """`user_id` is a demo user's id; null signs in as an anonymous guest (no personalization).
    `access_code` is required when the API has a demo access code (`/v1/meta`)."""

    user_id: str | None = None
    access_code: str | None = Field(default=None, max_length=200)


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(_FromRow):
    id: str
    title: str | None
    release_id: str
    outcome: str | None
    active_journey: str | None
    created_at: datetime
    updated_at: datetime


class AttachmentRef(_FromRow):
    """An attachment as listed on its message; fetch `/v1/attachments/{id}` for a URL."""

    id: str
    kind: AttachmentKind
    mime: str


class AttachmentOut(AttachmentRef):
    size: int
    width: int | None
    height: int | None
    duration_s: float | None
    status: str
    created_at: datetime


class AttachmentUrlOut(AttachmentRef):
    url: str  # signed; expires at `expires_at`
    expires_at: datetime


class MessageOut(_FromRow):
    id: str
    role: Role
    content: str
    cards: list[Card]
    citations: list[Citation]
    action: StructuredAction | None
    created_at: datetime
    feedback: Rating | None = None
    attachments: list[AttachmentRef] = Field(default_factory=list)


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class FeedbackCreate(BaseModel):
    rating: Rating
    reason: str | None = Field(default=None, max_length=1000)


class FeedbackOut(_FromRow):
    message_id: str
    rating: Rating
    reason: str | None


class WarrantyOut(BaseModel):
    """`user_profile.get_warranty_status`, as of today."""

    status: WarrantyState
    warranty_until: date | None = None  # None = unknown (e.g. landlord-owned)
    days_remaining: int | None = None  # set while active


class RepairOut(BaseModel):
    """One `user_profile.list_repair_history` record."""

    record_id: str
    date: date
    issue: str
    error_code: str | None = None
    resolution: str
    outcome: RepairOutcome
    performed_by: Literal["self", "technician"]


class ApplianceOut(BaseModel):
    """A registered appliance with its warranty and latest repairs (newest first)."""

    appliance_id: str
    category: CategoryId
    brand: str
    model_number: str
    nickname: str | None = None
    purchase_date: date | None = None
    warranty: WarrantyOut
    recent_repairs: list[RepairOut]


class ManualOut(BaseModel):
    doc_id: str
    title: str
    brand: str
    category: CategoryId
    pages: int
    # Where the PDF is served (append `#page=N` for a cited page); null when it isn't (spec Q10).
    url: str | None


class AnnotationFields(BaseModel):
    """A reviewer's verdict (spec §17.2). `incorrect` names at least one issue type; `correct`
    names none."""

    verdict: Verdict
    issue_types: list[IssueType] = Field(default_factory=list, max_length=8)
    expected_response: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _issues_match_the_verdict(self) -> Self:
        if len(set(self.issue_types)) != len(self.issue_types):
            raise ValueError("issue_types must not repeat")
        if self.verdict == "incorrect" and not self.issue_types:
            raise ValueError("an incorrect reply needs at least one issue type")
        if self.verdict == "correct" and self.issue_types:
            raise ValueError("a correct reply has no issue types")
        return self


class AnnotationCreate(AnnotationFields):
    message_id: str = Field(max_length=64)


class AnnotationUpdate(AnnotationFields):
    """Replaces every field of an annotation that hasn't been exported."""


class AnnotationOut(_FromRow):
    id: str
    message_id: str
    verdict: Verdict
    issue_types: list[IssueType]
    expected_response: str | None
    notes: str | None
    exported_case_id: str | None
    created_at: datetime
    updated_at: datetime


class AdminLogin(BaseModel):
    token: str = Field(max_length=500)


class AdminConversationRow(ConversationOut):
    user_id: str
    user_display_name: str
    user_is_demo: bool
    message_count: int
    up_count: int
    down_count: int
    annotation_count: int
    cost_usd: float


class AdminConversationPage(BaseModel):
    items: list[AdminConversationRow]
    next_before: str | None  # pass as `before` for the next page; None on the last page


class AdminAttachmentRef(AttachmentRef):
    status: str
    analysis: dict[str, Any] | None  # what the vision or video model saw (cached per upload)


class AdminMessageOut(MessageOut):
    trace_id: str | None
    trace_url: str | None = None  # Langfuse, when its project id is configured
    latency_ms: int | None
    cost_usd: float | None
    feedback_reason: str | None = None
    attachments: list[AdminAttachmentRef] = Field(default_factory=list)  # type: ignore[assignment]
    annotations: list[AnnotationOut] = Field(default_factory=list)


class AdminConversationDetail(ConversationOut):
    user_id: str
    user_display_name: str
    user_is_demo: bool
    messages: list[AdminMessageOut]


class RegressionExportRequest(BaseModel):
    """What the exported case checks. A field left out takes the suggestion for the annotation's
    issue types (see `homehelper.quality.export.suggest`)."""

    expected_outcomes: list[Outcome] | None = None
    expected_doc_id: str | None = Field(default=None, max_length=100)
    assertions: RegressionAssertions | None = None


class RegressionExportOut(BaseModel):
    case: RegressionCase
    yaml: str  # what `evals regression pull` writes to evals/datasets/regression/<id>.yaml
    exported: bool  # False for a dry run


class EvalMetricsOut(BaseModel):
    """The metrics `/admin/evals` charts (spec §16.3). Older reports may lack some (null); the
    rest of a report's metrics come through as extra keys."""

    model_config = ConfigDict(extra="allow")

    cases: int | None = None
    trials: int | None = None
    success_rate: float | None = None
    resolution_rate: float | None = None
    pass_hat_k: dict[str, float | None] = Field(default_factory=dict)
    safety_pass_rate: float | None = None
    injection_resistance: float | None = None
    out_of_scope_pass_rate: float | None = None
    multi_issue_pass_rate: float | None = None
    tool_scenario_pass_rate: float | None = None
    multimodal_pass_rate: float | None = None
    regression_pass_rate: float | None = None
    citation_accuracy: float | None = None
    avg_turns_to_resolution: float | None = None
    errors: int | None = None
    judge_unavailable: int | None = None
    latency_ms: dict[str, float | None] = Field(default_factory=dict)
    cost_usd: dict[str, float | None] = Field(default_factory=dict)
    rubric: dict[str, float | None] = Field(default_factory=dict)
    failed_checks: dict[str, int] = Field(default_factory=dict)


class EvalReportOut(BaseModel):
    id: str
    release_id: str
    suite: str
    created_at: datetime
    git_sha: str | None
    kb_version: str | None  # from the release's row, once published
    config: dict[str, Any]
    metrics: EvalMetricsOut
    weakened: str | None  # why this run can't gate a release (no judge, --limit, ...), or None


class EvalReportDetail(EvalReportOut):
    cases: list[CaseSummary]


class AdminManualOut(BaseModel):
    doc_id: str
    title: str
    brand: str
    category: CategoryId


class ErrorOut(BaseModel):
    detail: str


class UploadErrorOut(ErrorOut):
    code: str  # unsupported_type, too_large, too_long, unreadable, empty, rate_limited
