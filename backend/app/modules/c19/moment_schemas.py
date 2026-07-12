"""Authenticated application schemas for C19 Stage 5 Moments."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .asset_schemas import (
    ASSET_ID_PATTERN,
    ChatAssetAccessIntentRead,
    ChatAssetAccessIntentRequest,
    ChatAssetRead,
    ChatAssetReferenceRead,
    ChatAssetUploadIntentRead,
    ChatAssetUploadIntentRequest,
)
from .identity_schemas import C19ProfileSummaryRead


MOMENT_ID_PATTERN = r"^mom_[0-9a-f]{32}$"
COMMENT_ID_PATTERN = r"^cmt_[0-9a-f]{32}$"
CLIENT_CONTENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"

MomentVisibility = Literal["public", "org", "friends", "private"]


def _validate_social_text(value: str, *, maximum: int) -> str:
    normalized = unicodedata.normalize("NFC", value)
    if len(normalized) > maximum or any(
        unicodedata.category(character).startswith("C")
        and character not in {"\n", "\t"}
        for character in normalized
    ):
        raise ValueError("Moment text contains unsupported characters.")
    return normalized


class MomentDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_moment_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=CLIENT_CONTENT_ID_PATTERN,
    )


class MomentDraftRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moment_id: str = Field(pattern=MOMENT_ID_PATTERN)
    client_moment_id: str
    state: Literal["draft", "published", "delete_pending", "deleted"]
    created_at: datetime
    persisted_at: datetime


class MomentAssetUploadIntentRequest(ChatAssetUploadIntentRequest):
    kind: Literal["image"] = "image"


class MomentAssetUploadIntentRead(ChatAssetUploadIntentRead):
    moment_id: str = Field(pattern=MOMENT_ID_PATTERN)


class MomentPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(default="", max_length=4000)
    visibility: MomentVisibility = "public"
    audience_affiliation_ids: list[str] = Field(default_factory=list, max_length=32)
    asset_ids: list[str] = Field(default_factory=list, max_length=9)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return _validate_social_text(value, maximum=4000)

    @field_validator("audience_affiliation_ids", "asset_ids")
    @classmethod
    def validate_unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Duplicate identifiers are not allowed.")
        return value

    @field_validator("asset_ids")
    @classmethod
    def validate_asset_ids(cls, value: list[str]) -> list[str]:
        import re

        if any(re.fullmatch(ASSET_ID_PATTERN, item) is None for item in value):
            raise ValueError("Moment asset ID is invalid.")
        return value

    @model_validator(mode="after")
    def validate_visibility_and_content(self) -> Self:
        if self.visibility == "org":
            if not self.audience_affiliation_ids:
                raise ValueError("Organization visibility requires affiliations.")
        elif self.audience_affiliation_ids:
            raise ValueError("Only organization visibility accepts affiliations.")
        if not self.content.strip() and not self.asset_ids:
            raise ValueError("A Moment requires text or at least one image.")
        return self


class MomentAudienceOrganizationRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    org_id: str
    org_name: str


class MomentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moment_id: str = Field(pattern=MOMENT_ID_PATTERN)
    client_moment_id: str
    author: C19ProfileSummaryRead
    author_org_id: str | None
    visibility: MomentVisibility
    audience_organizations: list[MomentAudienceOrganizationRead]
    content: str = Field(max_length=4000)
    state: Literal["published"]
    created_at: datetime
    published_at: datetime
    assets: list[ChatAssetReferenceRead] = Field(default_factory=list, max_length=9)
    like_count: int = Field(ge=0)
    comment_count: int = Field(ge=0)
    viewer_has_liked: bool


class MomentFeedPageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moments: list[MomentRead]
    next_cursor: str | None
    latest_event_sequence: int = Field(ge=0)


class MomentLikeMutationRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moment_id: str = Field(pattern=MOMENT_ID_PATTERN)
    liked: bool
    changed: bool
    like_count: int = Field(ge=0)
    updated_at: datetime


class MomentLikeRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: C19ProfileSummaryRead
    sequence: int = Field(ge=1)
    created_at: datetime


class MomentLikePageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    likes: list[MomentLikeRead]
    next_cursor: str | None


class MomentCommentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_comment_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=CLIENT_CONTENT_ID_PATTERN,
    )
    content: str = Field(min_length=1, max_length=1000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = _validate_social_text(value, maximum=1000)
        if not normalized.strip():
            raise ValueError("Comment text cannot be blank.")
        return normalized


class MomentCommentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment_id: str = Field(pattern=COMMENT_ID_PATTERN)
    client_comment_id: str
    moment_id: str = Field(pattern=MOMENT_ID_PATTERN)
    author: C19ProfileSummaryRead
    content: str = Field(max_length=1000)
    state: Literal["active"]
    sequence: int = Field(ge=1)
    created_at: datetime
    persisted_at: datetime


class MomentCommentPageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comments: list[MomentCommentRead]
    next_cursor: str | None


class MomentCommentDeleteRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moment_id: str = Field(pattern=MOMENT_ID_PATTERN)
    comment_id: str = Field(pattern=COMMENT_ID_PATTERN)
    state: Literal["deleted"]
    changed: bool
    comment_count: int = Field(ge=0)
    deleted_at: datetime


class MomentDeleteRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moment_id: str = Field(pattern=MOMENT_ID_PATTERN)
    state: Literal["deleted"]


class MomentEventRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_sequence: int = Field(ge=1)
    event_type: Literal[
        "published",
        "deleted",
        "liked",
        "unliked",
        "commented",
        "comment_deleted",
    ]
    moment_id: str = Field(pattern=MOMENT_ID_PATTERN)
    actor_user_id: int | str
    comment_id: str | None = Field(default=None, pattern=COMMENT_ID_PATTERN)
    created_at: datetime


class MomentEventPageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[MomentEventRead]
    next_cursor: str | None
    latest_event_sequence: int = Field(ge=0)


class MomentEventTailRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cursor: str
    latest_event_sequence: int = Field(ge=0)


MomentAssetRead = ChatAssetRead
MomentAssetAccessIntentRequest = ChatAssetAccessIntentRequest
MomentAssetAccessIntentRead = ChatAssetAccessIntentRead


__all__ = [name for name in globals() if name.startswith("Moment")]
