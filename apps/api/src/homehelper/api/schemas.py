"""Request and response bodies of the `/v1` REST API (spec §13.2). These become the OpenAPI
schema the web app's TypeScript types are generated from."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from homehelper.channels.events import Card, StructuredAction
from homehelper.knowledge.schemas import CategoryId, Citation
from homehelper.mcp_servers.schemas import RepairOutcome, WarrantyState

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
    """`user_id` is a demo user's id; null signs in as an anonymous guest (no personalization)."""

    user_id: str | None = None


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
    url: str  # where the PDF is served; append `#page=N` to open a cited page


class AnnotationCreate(BaseModel):
    message_id: str
    verdict: Literal["correct", "incorrect"]
    issue_types: list[str] = Field(default_factory=list)
    expected_response: str | None = None
    notes: str | None = None


class ErrorOut(BaseModel):
    detail: str


class UploadErrorOut(ErrorOut):
    code: str  # unsupported_type, too_large, too_long, unreadable, empty, rate_limited
