"""Channel-agnostic inbound messages and outbound agent events (spec §13.1, §13.3).

The agent runtime only knows these types; the web adapter maps events to SSE (`event:` = `type`).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from homehelper.knowledge.schemas import Citation

Channel = Literal["web"]

StepResult = Literal["fixed", "not_fixed", "cannot_do"]


class StructuredAction(BaseModel):
    """A button press from a card; bypasses NLU (spec §7.3)."""

    type: Literal["step_result", "confirm_appliance", "select_booking_slot"]
    value: str


class InboundMessage(BaseModel):
    conversation_id: str
    channel: Channel = "web"
    text: str | None = None
    attachments: list[str] = Field(default_factory=list)  # attachment ids
    action: StructuredAction | None = None
    user_id: str | None = None


# --- Cards ---------------------------------------------------------------------------------


class StepCard(BaseModel):
    type: Literal["step"] = "step"
    plan_item_id: str
    index: int  # 1-based
    total: int
    instruction: str
    citations: list[Citation] = Field(default_factory=list)
    actions: list[StepResult] = Field(default_factory=lambda: ["fixed", "not_fixed", "cannot_do"])
    warranty_warning: bool = False


class CitationCard(BaseModel):
    type: Literal["citation"] = "citation"
    citation: Citation
    title: str


class SafetyCard(BaseModel):
    type: Literal["safety"] = "safety"
    hazard: str
    instructions: list[str]


class ApplianceConfirmCard(BaseModel):
    type: Literal["appliance_confirm"] = "appliance_confirm"
    category: str | None = None
    brand: str | None = None
    model_number: str | None = None
    confidence: float


class PartCard(BaseModel):
    type: Literal["part"] = "part"
    part_id: str
    name: str
    price_usd: float | None = None
    image_url: str | None = None


class VideoCard(BaseModel):
    type: Literal["video"] = "video"
    title: str
    url: str
    thumbnail_url: str | None = None


class BookingSlot(BaseModel):
    slot_id: str
    starts_at: str  # ISO 8601
    technician: str


class BookingSlotsCard(BaseModel):
    type: Literal["booking_slots"] = "booking_slots"
    slots: list[BookingSlot]


class HandoffCard(BaseModel):
    type: Literal["handoff"] = "handoff"
    reason: str
    booking_available: bool


Card = Annotated[
    StepCard
    | CitationCard
    | SafetyCard
    | ApplianceConfirmCard
    | PartCard
    | VideoCard
    | BookingSlotsCard
    | HandoffCard,
    Field(discriminator="type"),
]


# --- Events --------------------------------------------------------------------------------

StatusStage = Literal[
    "understanding", "analyzing_media", "retrieving", "planning", "responding", "checking"
]


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    stage: StatusStage
    label: str


class MessageDeltaEvent(BaseModel):
    type: Literal["message.delta"] = "message.delta"
    message_id: str
    text: str


class CardEvent(BaseModel):
    type: Literal["card"] = "card"
    message_id: str
    card: Card


class MessageCompletedEvent(BaseModel):
    type: Literal["message.completed"] = "message.completed"
    message_id: str
    citations: list[Citation] = Field(default_factory=list)
    journey: str | None = None
    step: str | None = None


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


AgentEvent = Annotated[
    StatusEvent | MessageDeltaEvent | CardEvent | MessageCompletedEvent | ErrorEvent,
    Field(discriminator="type"),
]
