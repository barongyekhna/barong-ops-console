"""Friendship and private block schemas for the C19 application API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .identity_schemas import C19ProfileRead, C19ProfileSummaryRead


class C19FriendRequestStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class C19FriendRequestDirection(StrEnum):
    ALL = "all"
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class C19FriendRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    addressee_user_id: int = Field(gt=0)
    request_message: str | None = Field(default=None, max_length=500)

    @field_validator("request_message")
    @classmethod
    def normalize_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class C19FriendRequestRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    requester: C19ProfileSummaryRead
    addressee: C19ProfileSummaryRead
    status: C19FriendRequestStatus
    request_message: str | None = None
    responded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class C19FriendRequestPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[C19FriendRequestRead]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class C19FriendRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relationship_id: str
    profile: C19ProfileRead
    established_at: datetime


class C19FriendPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[C19FriendRead]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class C19BlockRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str
    profile: C19ProfileRead
    blocked_at: datetime


class C19BlockPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[C19BlockRead]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class C19UserChangeRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: int
    changed: bool


__all__ = [
    "C19BlockPage",
    "C19BlockRead",
    "C19FriendPage",
    "C19FriendRead",
    "C19FriendRequestCreate",
    "C19FriendRequestDirection",
    "C19FriendRequestPage",
    "C19FriendRequestRead",
    "C19FriendRequestStatus",
    "C19UserChangeRead",
]
