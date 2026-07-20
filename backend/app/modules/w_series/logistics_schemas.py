"""Pydantic contracts for W-S logistics APIs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic_core import PydanticCustomError


class LogisticsStrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


PublicOrderNumber = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=64),
]


class ZoneRate(LogisticsStrictRequest):
    zone_name: str = Field(min_length=1, max_length=255)
    base_cost: str = Field(max_length=64)
    class_cost: str = Field(max_length=64)

    @field_validator("zone_name")
    @classmethod
    def _zone_name_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise PydanticCustomError("string_too_short", "must not be blank")
        return normalized

    @field_validator("base_cost", "class_cost")
    @classmethod
    def _cost_trimmed(cls, value: str) -> str:
        return value.strip()


class ShippingSyncJobResponse(BaseModel):
    job_id: str
    status: str
    dispatched: bool


class SyncResultRequest(LogisticsStrictRequest):
    status: Literal["success", "failed"]
    woo_class_id: int | None = None
    error: str | None = None


class SyncResultResponse(BaseModel):
    job_id: str
    status: str


class WooOrderIngestItem(LogisticsStrictRequest):
    woo_order_id: int = Field(ge=1)
    order_number: str = Field(min_length=1, max_length=64)
    woo_status: str = Field(min_length=1, max_length=30)
    customer_name: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=8)
    total: Decimal | None = None
    currency: str | None = Field(default=None, max_length=8)
    items_json: list[dict[str, Any]] | None = Field(
        default=None,
        validation_alias=AliasChoices("items_json", "items"),
    )
    placed_at: datetime | None = None

    @field_validator("order_number", "woo_status")
    @classmethod
    def _required_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("customer_name", "country", "currency")
    @classmethod
    def _optional_trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class OrdersIngestRequest(LogisticsStrictRequest):
    orders: list[WooOrderIngestItem] = Field(min_length=1, max_length=500)


class OrdersIngestResponse(BaseModel):
    accepted: int
    created: int
    updated: int


class TrackingEvent(BaseModel):
    time: str | None = None
    location: str | None = None
    description: str | None = None


class PublicTrackLookupRequest(LogisticsStrictRequest):
    order_numbers: list[PublicOrderNumber] = Field(min_length=1, max_length=20)


class PublicTrackingEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: str | None = None
    location: str | None = None
    description: str | None = None


class PublicTrackResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_number: str
    state: Literal["tracked", "not_shipped", "unknown"]
    tracking_number: str | None
    carrier_code: int | None
    tracking_status: Literal[
        "not_found",
        "info_received",
        "in_transit",
        "out_for_delivery",
        "delivered",
        "exception",
        "expired",
    ] | None
    last_update: datetime | None
    events: list[PublicTrackingEvent]


class PublicTrackLookupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[PublicTrackResult]


class OrderItem(BaseModel):
    id: str
    woo_order_id: int
    order_number: str
    woo_status: str
    customer_name: str | None
    country: str | None
    total: Decimal | None
    currency: str | None
    items_json: list[dict[str, Any]] | None
    placed_at: datetime | None
    tracking_number: str | None
    carrier_code: int | None
    tracking_status: str
    tracking_events_json: list[TrackingEvent] | None
    tracking_registered: bool
    last_tracking_update: datetime | None
    writeback_status: str
    created_at: datetime | None
    updated_at: datetime | None


class OrderSummary(BaseModel):
    pending: int
    in_transit: int
    delivered: int
    exception: int


class OrderListResponse(BaseModel):
    summary: OrderSummary
    orders: list[OrderItem]


class TrackingPatchRequest(LogisticsStrictRequest):
    tracking_number: str | None = Field(max_length=128)
    carrier_code: int | None = None

    @field_validator("tracking_number")
    @classmethod
    def _tracking_number_trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class TrackingPatchResponse(BaseModel):
    order: OrderItem
    tracking_warning: str | None = None


class TrackingRefreshResponse(BaseModel):
    order: OrderItem
