"""Validated HTTP contract for the C19 record service."""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
ClientMessageIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
Reason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=500),
]
AssetIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^att_[0-9a-f]{32}$"),
]
Sha256Hex = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(UTC)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class RecordAssetReference(ContractModel):
    """Immutable, provider-neutral asset snapshot stored with a record."""

    asset_id: AssetIdentifier
    client_asset_id: ClientMessageIdentifier
    kind: Literal["image", "file"]
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=3, max_length=128)
    size_bytes: int = Field(gt=0, le=64 * 1024 * 1024)
    sha256_hex: Sha256Hex
    version: int = Field(ge=1)
    ordinal: int = Field(ge=0)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if value != unicodedata.normalize("NFC", value):
            raise ValueError("filename must be NFC-normalized")
        if value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("filename must be a basename")
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise ValueError("filename contains control characters")
        return value

    @field_validator("media_type")
    @classmethod
    def validate_media_type(cls, value: str) -> str:
        if value != value.strip().lower() or "/" not in value:
            raise ValueError("media_type must be a lowercase MIME type")
        major, minor = value.split("/", 1)
        if not major or not minor or any(character.isspace() for character in value):
            raise ValueError("media_type must be a lowercase MIME type")
        return value


class RecordAppendRequest(ContractModel):
    client_message_id: ClientMessageIdentifier
    conversation_id: Identifier
    sender_user_id: Identifier
    recipient_user_ids: list[Identifier] = Field(min_length=1, max_length=1000)
    content_type: Literal["text", "emoji", "image", "file"]
    content: str = ""
    created_at: datetime
    sender_org_id: Identifier | None = None
    recipient_org_ids: list[Identifier] = Field(default_factory=list, max_length=1000)
    metadata: dict[str, str] = Field(default_factory=dict)
    assets: list[RecordAssetReference] = Field(default_factory=list, max_length=1)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @field_validator("recipient_user_ids", "recipient_org_ids")
    @classmethod
    def validate_unique_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate identifiers are not allowed")
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 32:
            raise ValueError("metadata supports at most 32 entries")
        for key, item in value.items():
            if not key or len(key) > 64 or len(item) > 500:
                raise ValueError("metadata key or value exceeds its limit")
        return value

    @model_validator(mode="after")
    def validate_asset_shape(self) -> "RecordAppendRequest":
        if any(asset.ordinal != ordinal for ordinal, asset in enumerate(self.assets)):
            raise ValueError("asset ordinals must be contiguous and match list order")
        if self.content_type in {"text", "emoji"}:
            if self.assets:
                raise ValueError("text and emoji records cannot contain assets")
            return self
        if len(self.assets) != 1:
            raise ValueError("image and file records require exactly one asset")
        if self.assets[0].kind != self.content_type:
            raise ValueError("asset kind must match record content_type")
        return self


class RecordResponse(ContractModel):
    record_id: str
    client_message_id: str
    conversation_id: str
    sequence: int
    sender_user_id: str
    recipient_user_ids: list[str]
    content_type: Literal["text", "emoji", "image", "file"]
    content: str
    status: Literal["sent", "delivered", "read"] = "sent"
    created_at: datetime
    persisted_at: datetime
    sender_org_id: str | None = None
    recipient_org_ids: list[str]
    metadata: dict[str, str]
    assets: list[RecordAssetReference] = Field(default_factory=list)


class RecordPageResponse(ContractModel):
    records: list[RecordResponse]
    next_cursor: str | None
    latest_sequence: int


class PositionAdvanceRequest(ContractModel):
    user_id: Identifier
    through_sequence: int = Field(ge=0)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class ReceiptPositionResponse(ContractModel):
    conversation_id: str
    user_id: str
    delivered_through_sequence: int
    read_through_sequence: int
    updated_at: datetime


class UnreadPositionResponse(ContractModel):
    conversation_id: str
    user_id: str
    unread_count: int
    first_unread_sequence: int | None
    latest_sequence: int


class UnreadSummaryRequest(ContractModel):
    """Barong-authorized active conversations for one unread aggregation shard."""

    conversation_ids: list[Identifier] = Field(default_factory=list, max_length=1000)

    @field_validator("conversation_ids")
    @classmethod
    def validate_unique_conversation_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate conversation_ids are not allowed")
        return value


class UnreadSummaryResponse(ContractModel):
    total_unread_count: int = Field(ge=0)
    unread_conversation_count: int = Field(ge=0, le=1000)


class ResumePositionResponse(ContractModel):
    conversation_id: str
    user_id: str
    resume_cursor: str | None
    delivered_through_sequence: int
    read_through_sequence: int
    latest_sequence: int


class CombinedPositionResponse(ContractModel):
    unread: UnreadPositionResponse
    resume: ResumePositionResponse


class UserEventResponse(ContractModel):
    event_id: str
    user_id: str
    conversation_id: str
    record_id: str
    record_sequence: int
    event_sequence: int
    created_at: datetime


class UserEventPageResponse(ContractModel):
    events: list[UserEventResponse]
    next_cursor: str | None
    latest_event_sequence: int


class UserEventTailResponse(ContractModel):
    cursor: str
    latest_event_sequence: int


class DeleteRecordsRequest(ContractModel):
    conversation_id: Identifier
    record_ids: list[Identifier] = Field(min_length=1, max_length=500)
    requested_by_user_id: Identifier
    reason: Reason
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @field_validator("record_ids")
    @classmethod
    def validate_unique_record_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate record_ids are not allowed")
        return value


class RetentionRequest(ContractModel):
    operation_id: str = Field(pattern=r"^rtn_[0-9a-f]{64}$")
    batch_ordinal: int = Field(ge=0, le=100_000)
    approved_maximum_records: int = Field(ge=1, le=100_000)
    approved_maximum_asset_jobs: int = Field(ge=1, le=100_000)
    requested_by_user_id: Identifier
    reason: Reason
    requested_at: datetime
    delete_before: datetime
    conversation_id: Identifier | None = None
    maximum_records: int = Field(ge=1, le=1000)

    @field_validator("requested_at", "delete_before")
    @classmethod
    def validate_datetimes(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class MutationResultResponse(ContractModel):
    affected_count: int
    completed_at: datetime


class RetentionBatchResponse(ContractModel):
    operation_id: str = Field(pattern=r"^rtn_[0-9a-f]{64}$")
    batch_ordinal: int = Field(ge=0)
    affected_count: int = Field(ge=0)
    cumulative_affected_count: int = Field(ge=0)
    operation_complete: bool
    completed_at: datetime


class AssetDeletionClaimRequest(ContractModel):
    worker_id: Identifier
    retention_operation_id: str | None = Field(
        default=None, pattern=r"^rtn_[0-9a-f]{64}$"
    )
    requested_at: datetime
    limit: int = Field(default=100, ge=1, le=100)
    lease_seconds: int = Field(default=120, ge=30, le=300)

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class AssetDeletionJob(ContractModel):
    job_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    asset_id: AssetIdentifier
    record_id: str = Field(min_length=1, max_length=36)
    conversation_id: Identifier
    phase: Literal["prepare", "commit"]


class AssetDeletionClaimResponse(ContractModel):
    jobs: list[AssetDeletionJob] = Field(max_length=100)
    eligible_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    leased_count: int = Field(ge=0)


class AssetDeletionCompleteRequest(ContractModel):
    worker_id: Identifier
    outcome: Literal["accepted", "protected"]
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def validate_completed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class AssetDeletionCompleteResponse(ContractModel):
    job_id: str
    state: Literal["completed", "protected"]
    outcome: Literal["accepted", "protected"]


class AssetDeletionAuthorizeRequest(ContractModel):
    worker_id: Identifier
    authorized_at: datetime

    @field_validator("authorized_at")
    @classmethod
    def validate_authorized_at(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class AssetDeletionAuthorizeResponse(ContractModel):
    job_id: str
    state: Literal["authorized", "blocked"]


class HealthResponse(ContractModel):
    status: Literal["ok"]
    service: Literal["c19-record-service"]


class RecordOpsSnapshot(ContractModel):
    """Private aggregate telemetry; intentionally contains no user data."""

    status: Literal["ok"]
    service: Literal["c19-record-service"]
    generated_at: datetime
    chat_records: int = Field(ge=0)
    chat_delivery_events: int = Field(ge=0)
    idempotency_tombstones: int = Field(ge=0)
    mutation_audits: int = Field(ge=0)
    asset_deletion_pending: int = Field(ge=0)
    asset_deletion_authorized: int = Field(ge=0)
    asset_deletion_blocked: int = Field(ge=0)
    asset_deletion_leased: int = Field(ge=0)
    asset_deletion_completed: int = Field(ge=0)
    asset_deletion_protected: int = Field(ge=0)
    oldest_asset_deletion_pending_age_seconds: int | None = Field(
        default=None, ge=0
    )
    oldest_asset_deletion_authorized_age_seconds: int | None = Field(
        default=None, ge=0
    )
    moment_states: dict[Literal["draft", "published", "delete_pending", "deleted"], int]
    moment_likes: int = Field(ge=0)
    active_moment_comments: int = Field(ge=0)
    moment_events: int = Field(ge=0)
    oldest_draft_age_seconds: int | None = Field(default=None, ge=0)
    oldest_delete_pending_age_seconds: int | None = Field(default=None, ge=0)

    @field_validator("moment_states")
    @classmethod
    def validate_exact_moment_states(cls, value: dict[str, int]) -> dict[str, int]:
        if set(value) != {"draft", "published", "delete_pending", "deleted"}:
            raise ValueError("moment state telemetry is incomplete")
        if any(count < 0 for count in value.values()):
            raise ValueError("moment state telemetry is invalid")
        return value
