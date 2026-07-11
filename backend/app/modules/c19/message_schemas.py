"""Public request/response schemas for the external C19 chat runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CLIENT_MESSAGE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class MessageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=CLIENT_MESSAGE_ID_PATTERN,
    )
    content_type: Literal["text", "emoji"]
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def reject_blank_or_control_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content must not be blank.")
        if any(ord(character) < 32 and character not in {"\n", "\t"} for character in value):
            raise ValueError("Message content contains control characters.")
        return value

    @model_validator(mode="after")
    def enforce_content_type_limit(self) -> Self:
        if self.content_type == "emoji" and (
            len(self.content) > 64 or "\n" in self.content or "\t" in self.content
        ):
            raise ValueError("Emoji messages must be at most 64 characters.")
        return self


class ChatRecordRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    client_message_id: str
    conversation_id: str
    sequence: int = Field(ge=1)
    sender_user_id: str
    recipient_user_ids: list[str]
    content_type: Literal["text", "emoji"]
    content: str
    status: Literal["sent", "delivered", "read"]
    created_at: datetime
    persisted_at: datetime
    sender_org_id: str | None
    recipient_org_ids: list[str]
    metadata: dict[str, str]


class ChatRecordPageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[ChatRecordRead]
    next_cursor: str | None
    latest_sequence: int = Field(ge=0)


class ChatPositionAdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    through_sequence: int = Field(ge=0)


class ChatReceiptPositionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    user_id: str
    delivered_through_sequence: int = Field(ge=0)
    read_through_sequence: int = Field(ge=0)
    updated_at: datetime


class ChatUnreadPositionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    user_id: str
    unread_count: int = Field(ge=0)
    first_unread_sequence: int | None = Field(default=None, ge=1)
    latest_sequence: int = Field(ge=0)


class ChatResumePositionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    user_id: str
    resume_cursor: str | None
    delivered_through_sequence: int = Field(ge=0)
    read_through_sequence: int = Field(ge=0)
    latest_sequence: int = Field(ge=0)


class ChatUserEventRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    user_id: str
    conversation_id: str
    record_id: str
    record_sequence: int = Field(ge=1)
    event_sequence: int = Field(ge=1)
    created_at: datetime


class ChatUserEventPageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[ChatUserEventRead]
    next_cursor: str | None
    latest_event_sequence: int = Field(ge=0)


class ChatUserEventTailRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cursor: str = Field(min_length=1, max_length=2048)
    latest_event_sequence: int = Field(ge=0)


__all__ = [
    "CLIENT_MESSAGE_ID_PATTERN",
    "ChatPositionAdvanceRequest",
    "ChatReceiptPositionRead",
    "ChatRecordPageRead",
    "ChatRecordRead",
    "ChatResumePositionRead",
    "ChatUnreadPositionRead",
    "ChatUserEventPageRead",
    "ChatUserEventRead",
    "ChatUserEventTailRead",
    "MessageCreateRequest",
]
