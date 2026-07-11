"""Validated HTTP contract for the C19 record service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
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


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(UTC)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class RecordAppendRequest(ContractModel):
    client_message_id: ClientMessageIdentifier
    conversation_id: Identifier
    sender_user_id: Identifier
    recipient_user_ids: list[Identifier] = Field(min_length=1, max_length=1000)
    content_type: Literal["text", "emoji"]
    content: str
    created_at: datetime
    sender_org_id: Identifier | None = None
    recipient_org_ids: list[Identifier] = Field(default_factory=list, max_length=1000)
    metadata: dict[str, str] = Field(default_factory=dict)

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


class RecordResponse(ContractModel):
    record_id: str
    client_message_id: str
    conversation_id: str
    sequence: int
    sender_user_id: str
    recipient_user_ids: list[str]
    content_type: Literal["text", "emoji"]
    content: str
    status: Literal["sent", "delivered", "read"] = "sent"
    created_at: datetime
    persisted_at: datetime
    sender_org_id: str | None = None
    recipient_org_ids: list[str]
    metadata: dict[str, str]


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
    requested_by_user_id: Identifier
    reason: Reason
    requested_at: datetime
    delete_before: datetime
    conversation_id: Identifier | None = None
    maximum_records: int | None = Field(default=None, ge=1, le=100_000)

    @field_validator("requested_at", "delete_before")
    @classmethod
    def validate_datetimes(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class MutationResultResponse(ContractModel):
    affected_count: int
    completed_at: datetime


class HealthResponse(ContractModel):
    status: Literal["ok"]
    service: Literal["c19-record-service"]
