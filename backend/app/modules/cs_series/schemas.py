"""Validated CS ingress and management API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CSChannel = Literal["retail", "wholesale"]
CSStatus = Literal["new", "in_progress", "resolved", "spam"]


class CSInboundPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: CSChannel
    name: str = Field(default="", max_length=120)
    email: str = Field(min_length=1, max_length=254)
    company: str = Field(default="", max_length=200)
    order_number: str = Field(default="", max_length=64)
    message: str = Field(min_length=1, max_length=5000)
    source_url: str = Field(default="", max_length=500)
    honeypot: str = Field(default="", max_length=500)
    form_ms: int | None = None


class CSMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel: CSChannel
    name: str
    email: str
    company: str | None = None
    order_number: str | None = None
    message: str
    source_url: str | None = None
    client_ip: str
    user_agent: str | None = None
    status: CSStatus
    internal_note: str | None = None
    created_at: datetime
    updated_at: datetime


class CSMessageListResponse(BaseModel):
    items: list[CSMessageRead]
    total: int
    page: int
    page_size: int
    pages: int


class CSMessageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CSStatus | None = None
    internal_note: str | None = Field(default=None, max_length=5000)


class CSChannelSummary(BaseModel):
    new: int


class CSSummaryResponse(BaseModel):
    retail: CSChannelSummary
    wholesale: CSChannelSummary


__all__ = [
    "CSChannel",
    "CSChannelSummary",
    "CSInboundPayload",
    "CSMessageListResponse",
    "CSMessageRead",
    "CSMessageUpdate",
    "CSStatus",
    "CSSummaryResponse",
]
