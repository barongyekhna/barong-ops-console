from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ConversationType = Literal["direct", "group"]
ConversationStatus = Literal["active", "archived", "closed"]
ConversationMemberRole = Literal["owner", "admin", "member"]
ConversationMemberStatus = Literal[
    "invited",
    "active",
    "left",
    "removed",
    "banned",
]
NotificationLevel = Literal["all", "mentions", "none"]


class ConversationMemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(gt=0)
    affiliation_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("affiliation_id")
    @classmethod
    def normalize_affiliation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("affiliation_id must not be blank.")
        return normalized


class DirectConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    peer_user_id: int = Field(gt=0)
    actor_affiliation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )
    peer_affiliation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )

    @field_validator("actor_affiliation_id", "peer_affiliation_id")
    @classmethod
    def normalize_affiliation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("affiliation_id must not be blank.")
        return normalized


class GroupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    actor_affiliation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )
    members: list[ConversationMemberInput] = Field(min_length=2, max_length=199)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank.")
        return normalized

    @field_validator("actor_affiliation_id")
    @classmethod
    def normalize_actor_affiliation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("actor_affiliation_id must not be blank.")
        return normalized

    @model_validator(mode="after")
    def validate_unique_members(self) -> "GroupCreateRequest":
        user_ids = [member.user_id for member in self.members]
        if len(user_ids) != len(set(user_ids)):
            raise ValueError("members must not contain duplicate users.")
        return self


class GroupUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank.")
        return normalized


class GroupMembersAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    members: list[ConversationMemberInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_members(self) -> "GroupMembersAddRequest":
        user_ids = [member.user_id for member in self.members]
        if len(user_ids) != len(set(user_ids)):
            raise ValueError("members must not contain duplicate users.")
        return self


class GroupOwnerTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_owner_user_id: int = Field(gt=0)


class ConversationSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_pinned: bool | None = None
    is_muted: bool | None = None
    is_archived: bool | None = None
    notification_level: NotificationLevel | None = None

    @model_validator(mode="after")
    def require_update(self) -> "ConversationSettingsUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one setting must be supplied.")
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError("Conversation setting values must not be null.")
        return self


class ConversationSettingsView(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    conversation_id: str
    user_id: int
    is_pinned: bool
    is_muted: bool
    is_archived: bool
    notification_level: NotificationLevel
    created_at: datetime
    updated_at: datetime


class ConversationMemberView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int
    affiliation_id: str | None
    org_id: str | None
    role: ConversationMemberRole
    status: ConversationMemberStatus
    joined_at: datetime
    left_at: datetime | None


class DirectPeerView(BaseModel):
    """Read-only card of the other participant in a direct conversation."""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    display_name: str
    avatar_ref: str | None


class ConversationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    type: ConversationType
    title: str | None
    status: ConversationStatus
    actor_role: ConversationMemberRole
    actor_org_id: str | None
    active_member_count: int = Field(ge=0)
    direct_peer: DirectPeerView | None = None
    settings: ConversationSettingsView
    created_at: datetime
    updated_at: datetime


class ConversationDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    type: ConversationType
    title: str | None
    status: ConversationStatus
    created_by_user_id: int | None
    members: list[ConversationMemberView]
    settings: ConversationSettingsView
    created_at: datetime
    updated_at: datetime


class ConversationPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ConversationSummary]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class GroupDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    status: Literal["closed"] = "closed"


class GroupLeaveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    member_status: Literal["left"] = "left"
    conversation_status: Literal["active"] = "active"


class C19ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


__all__ = [
    "C19ErrorDetail",
    "ConversationDetail",
    "ConversationMemberInput",
    "ConversationMemberView",
    "ConversationPage",
    "ConversationSettingsUpdateRequest",
    "ConversationSettingsView",
    "ConversationSummary",
    "DirectConversationCreateRequest",
    "DirectPeerView",
    "GroupCreateRequest",
    "GroupDeleteResponse",
    "GroupLeaveResponse",
    "GroupMembersAddRequest",
    "GroupOwnerTransferRequest",
    "GroupUpdateRequest",
]
