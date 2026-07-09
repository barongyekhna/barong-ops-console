"""Pydantic DTOs for the notification inbox."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NotificationLevel = Literal["info", "success", "warning", "error"]
NotificationStatus = Literal["unread", "read", "archived"]


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: str | None = None
    source: str
    event_type: str
    level: str
    title: str
    body: str | None = None
    product_id: UUID | None = None
    external_refs: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    status: str
    read_at: datetime | None = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationRead]
    count: int
    unread: int
    limit: int
    offset: int


class UnreadCountResponse(BaseModel):
    unread: int


class MarkReadResponse(BaseModel):
    updated: int


class NotificationIngest(BaseModel):
    """Payload posted by n8n / the P upload pipeline to record an event."""

    event_type: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    body: str | None = None
    level: NotificationLevel = "info"
    source: str = Field(default="n8n", min_length=1, max_length=128)
    org_id: str | None = Field(default=None, max_length=40)
    product_id: UUID | None = None
    external_refs: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
