"""Records served by the MCP servers and the `data/mock/` files they are seeded from (spec §12.2).

These models are both the JSON file schema and the tools' structured output schema, so the agent
side (M5-07) can validate tool results with the same classes.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from homehelper.knowledge.schemas import CategoryId


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserProfile(_Record):
    user_id: str
    display_name: str
    persona: str  # novice, diy_enthusiast, renter, ...
    diy_skill: Literal["beginner", "intermediate", "advanced"]
    housing: Literal["homeowner", "renter"]
    zip_code: str
    notes: str | None = None


class Appliance(_Record):
    appliance_id: str
    user_id: str
    category: CategoryId
    brand: str
    model_number: str  # matches a manual's `model_patterns` in data/manuals/manifest.yaml
    nickname: str | None = None
    purchase_date: date | None = None
    warranty_until: date | None = None  # None = unknown (e.g. landlord-owned)


class WarrantyState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class WarrantyStatus(_Record):
    appliance_id: str
    status: WarrantyState
    warranty_until: date | None = None
    days_remaining: int | None = None  # set while active


RepairOutcome = Literal["resolved", "unresolved", "technician_booked"]


class RepairRecord(_Record):
    record_id: str
    user_id: str
    appliance_id: str
    date: date
    issue: str
    error_code: str | None = None
    resolution: str
    outcome: RepairOutcome
    performed_by: Literal["self", "technician"]


class Part(_Record):
    part_id: str
    kind: Literal["part", "tool"]
    name: str
    category: CategoryId | None = None  # None = general-purpose tool
    brands: list[str] = Field(default_factory=list)  # empty = any brand
    compatible_models: list[str] = Field(default_factory=list)  # model patterns; empty = any model
    symptoms: list[str] = Field(default_factory=list)
    price_usd: float
    image_url: str
    description: str


Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class Technician(_Record):
    technician_id: str
    name: str
    company: str
    categories: list[CategoryId]
    service_zip_prefixes: list[str]
    timezone: str  # IANA name; weekly slot times are local
    rating: float
    visit_fee_usd: float
    weekly_slots: dict[Weekday, list[str]]  # weekday -> ["09:00", ...]
    slot_minutes: int

    def serves(self, zip_code: str, category: CategoryId) -> bool:
        return category in self.categories and any(
            zip_code.startswith(prefix) for prefix in self.service_zip_prefixes
        )


class Slot(_Record):
    slot_id: str
    technician_id: str
    technician_name: str
    company: str
    rating: float
    visit_fee_usd: float
    starts_at: datetime
    ends_at: datetime


BookingStatus = Literal["booked", "cancelled"]


class Booking(_Record):
    booking_id: str
    user_id: str
    appliance_id: str
    slot_id: str
    technician_id: str
    starts_at: datetime
    issue: str
    status: BookingStatus
    created_at: datetime
    cancelled_at: datetime | None = None


class Video(_Record):
    video_id: str
    title: str
    channel: str
    url: str
    thumbnail_url: str | None = None
    duration_seconds: int | None = None
    source: Literal["youtube", "mock"]


class MockVideo(_Record):
    """An entry of `videos.json`, served by `tutorials` in mock mode."""

    video_id: str
    title: str
    channel: str
    category: CategoryId
    brands: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    duration_seconds: int | None = None
