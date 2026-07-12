"""Strict private HTTP contracts for Stage 5 C19 Moments.

Current identity, affiliation, friendship, and block state is supplied only by
the trusted Barong service.  Moment content never enters those policy lists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .schemas import (
    ClientMessageIdentifier,
    ContractModel,
    Identifier,
    RecordAssetReference,
    _aware_utc,
)


MomentState = Literal["draft", "published", "delete_pending", "deleted"]
MomentVisibility = Literal["public", "org", "friends", "private"]
MomentEventType = Literal[
    "published",
    "deleted",
    "liked",
    "unliked",
    "commented",
    "comment_deleted",
]


class MomentAssetReference(RecordAssetReference):
    kind: Literal["image"] = "image"
    ordinal: int = Field(ge=0, le=8)

    @field_validator("media_type")
    @classmethod
    def require_image_media_type(cls, value: str) -> str:
        if not value.startswith("image/"):
            raise ValueError("Moment assets must use an image media type")
        return value


class MomentViewerContext(ContractModel):
    """Barong-derived current policy facts; never accepted from a browser."""

    viewer_user_id: Identifier
    active_user_ids: list[Identifier] = Field(min_length=1, max_length=20_000)
    active_org_ids: list[Identifier] = Field(default_factory=list, max_length=1_000)
    friend_user_ids: list[Identifier] = Field(default_factory=list, max_length=20_000)
    blocked_user_ids: list[Identifier] = Field(default_factory=list, max_length=20_000)

    @field_validator(
        "active_user_ids",
        "active_org_ids",
        "friend_user_ids",
        "blocked_user_ids",
    )
    @classmethod
    def require_unique_context_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("relationship context identifiers must be unique")
        return value

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        active = set(self.active_user_ids)
        if self.viewer_user_id not in active:
            raise ValueError("viewer must be an active user")
        if not set(self.friend_user_ids) <= active:
            raise ValueError("friends must be active users")
        if self.viewer_user_id in self.blocked_user_ids:
            raise ValueError("viewer cannot block themselves")
        if set(self.friend_user_ids) & set(self.blocked_user_ids):
            raise ValueError("friends and blocked users must be disjoint")
        return self


class MomentDraftCreateRequest(ContractModel):
    client_moment_id: ClientMessageIdentifier
    author_user_id: Identifier


class MomentDraftResponse(ContractModel):
    moment_id: str = Field(pattern=r"^mom_[0-9a-f]{32}$")
    client_moment_id: str
    author_user_id: str
    state: MomentState
    created_at: datetime
    persisted_at: datetime


class MomentDraftQueryRequest(ContractModel):
    author_user_id: Identifier


class MomentPublishRequest(ContractModel):
    author_user_id: Identifier
    author_org_id: Identifier | None = None
    content: str = Field(default="", max_length=4_000)
    visibility: MomentVisibility
    audience_user_ids: list[Identifier] = Field(min_length=1, max_length=20_000)
    audience_org_ids: list[Identifier] = Field(default_factory=list, max_length=32)
    assets: list[MomentAssetReference] = Field(default_factory=list, max_length=9)

    @field_validator("content")
    @classmethod
    def reject_control_content(cls, value: str) -> str:
        if any(
            ord(character) < 32 and character not in {"\n", "\t"}
            for character in value
        ):
            raise ValueError("Moment content contains control characters")
        return value

    @field_validator("audience_user_ids", "audience_org_ids")
    @classmethod
    def require_unique_audience(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("audience identifiers must be unique")
        return value

    @model_validator(mode="after")
    def validate_publication(self) -> Self:
        if self.author_user_id not in self.audience_user_ids:
            raise ValueError("author must belong to the audience snapshot")
        if not self.content.strip() and not self.assets:
            raise ValueError("Moment requires text or at least one image")
        if any(asset.ordinal != index for index, asset in enumerate(self.assets)):
            raise ValueError("asset ordinals must be contiguous and ordered")
        if len({asset.asset_id for asset in self.assets}) != len(self.assets):
            raise ValueError("Moment assets must be unique")
        if len({asset.client_asset_id for asset in self.assets}) != len(self.assets):
            raise ValueError("Moment client asset IDs must be unique")
        if self.visibility == "private":
            if set(self.audience_user_ids) != {self.author_user_id}:
                raise ValueError("private Moment audience must contain only author")
            if self.audience_org_ids:
                raise ValueError("private Moment cannot contain organization audience")
        elif self.visibility == "org":
            if not self.audience_org_ids:
                raise ValueError("organization Moment requires audience_org_ids")
            if (
                self.author_org_id is not None
                and self.author_org_id not in self.audience_org_ids
            ):
                raise ValueError("author_org_id must belong to the org audience")
        elif self.audience_org_ids:
            raise ValueError("audience_org_ids are valid only for org visibility")
        return self


class MomentRead(ContractModel):
    moment_id: str
    client_moment_id: str
    author_user_id: str
    author_org_id: str | None
    visibility: MomentVisibility
    audience_org_ids: list[str]
    content: str
    state: Literal["published"]
    created_at: datetime
    published_at: datetime
    assets: list[MomentAssetReference]
    like_count: int = Field(ge=0)
    comment_count: int = Field(ge=0)
    viewer_has_liked: bool


class MomentContextQuery(ContractModel):
    context: MomentViewerContext


class MomentFeedQuery(MomentContextQuery):
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class MomentPageResponse(ContractModel):
    moments: list[MomentRead]
    next_cursor: str | None
    latest_event_sequence: int = Field(ge=0)


class MomentLikeMutationRequest(MomentContextQuery):
    user_id: Identifier
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def actor_matches_context(self) -> Self:
        if self.user_id != self.context.viewer_user_id:
            raise ValueError("like actor must match viewer context")
        return self


class MomentLikeResponse(ContractModel):
    moment_id: str
    user_id: str
    liked: bool
    changed: bool
    like_count: int = Field(ge=0)
    updated_at: datetime


class MomentLikeRead(ContractModel):
    user_id: str
    sequence: int = Field(ge=1)
    liked_at: datetime


class MomentInteractionPageQuery(MomentContextQuery):
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class MomentLikePageResponse(ContractModel):
    items: list[MomentLikeRead]
    count: int = Field(ge=0)
    next_cursor: str | None


class MomentCommentCreateRequest(MomentContextQuery):
    client_comment_id: ClientMessageIdentifier
    author_user_id: Identifier
    content: str = Field(min_length=1, max_length=1_000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("comment content cannot be blank")
        if any(
            ord(character) < 32 and character not in {"\n", "\t"}
            for character in value
        ):
            raise ValueError("comment content contains control characters")
        return value

    @model_validator(mode="after")
    def actor_matches_context(self) -> Self:
        if self.author_user_id != self.context.viewer_user_id:
            raise ValueError("comment author must match viewer context")
        return self


class MomentCommentRead(ContractModel):
    comment_id: str = Field(pattern=r"^cmt_[0-9a-f]{32}$")
    client_comment_id: str
    moment_id: str
    author_user_id: str
    content: str
    state: Literal["active"]
    sequence: int = Field(ge=1)
    created_at: datetime
    persisted_at: datetime


class MomentCommentPageResponse(ContractModel):
    items: list[MomentCommentRead]
    count: int = Field(ge=0)
    next_cursor: str | None


class MomentCommentDeleteRequest(MomentContextQuery):
    requested_by_user_id: Identifier
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def actor_matches_context(self) -> Self:
        if self.requested_by_user_id != self.context.viewer_user_id:
            raise ValueError("comment deletion actor must match viewer context")
        return self


class MomentCommentDeleteResponse(ContractModel):
    moment_id: str
    comment_id: str
    changed: bool
    comment_count: int = Field(ge=0)
    deleted_at: datetime


class MomentDeleteRequest(MomentContextQuery):
    requested_by_user_id: Identifier
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def actor_matches_context(self) -> Self:
        if self.requested_by_user_id != self.context.viewer_user_id:
            raise ValueError("Moment deletion actor must match viewer context")
        return self


class MomentDeleteResponse(ContractModel):
    moment_id: str
    state: Literal["delete_pending", "deleted"]
    changed: bool
    assets: list[MomentAssetReference]
    updated_at: datetime


class MomentDeleteCompleteRequest(ContractModel):
    requested_by_user_id: Identifier
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def validate_completed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class MomentEventRead(ContractModel):
    event_id: str
    event_sequence: int = Field(ge=1)
    event_type: MomentEventType
    moment_id: str
    actor_user_id: str
    comment_id: str | None
    created_at: datetime


class MomentEventQuery(MomentContextQuery):
    limit: int = Field(default=100, ge=1, le=500)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class MomentEventPageResponse(ContractModel):
    events: list[MomentEventRead]
    next_cursor: str
    latest_event_sequence: int = Field(ge=0)


class MomentEventTailResponse(ContractModel):
    cursor: str
    latest_event_sequence: int = Field(ge=0)
