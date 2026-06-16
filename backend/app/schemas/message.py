from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .attachment import Attachment


MESSAGE_ID_PATTERN = re.compile(r"^msg_[0-9a-f]{32}$")
CONVERSATION_ID_PATTERN = re.compile(r"^conv_[0-9a-f]{32}$")
ALLOWED_MESSAGE_CONTENT_TYPES = ("text", "emoji")
UNSUPPORTED_MESSAGE_CONTENT_TYPES = ("voice", "video", "file", "image")


class MessageContentType(StrEnum):
    TEXT = "text"
    EMOJI = "emoji"


class MessageStatus(StrEnum):
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"


class MessageOperation(StrEnum):
    SEND = "send"
    FETCH_BY_CONVERSATION = "fetch_by_conversation"
    MARK_READ = "mark_read"


def generate_message_id() -> str:
    return "msg_" + uuid4().hex


def generate_conversation_id() -> str:
    return "conv_" + uuid4().hex


def _normalize_non_empty(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


class Conversation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: str = Field(default_factory=generate_conversation_id)
    participants: tuple[str, str]

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str) -> str:
        normalized = value.strip()
        if not CONVERSATION_ID_PATTERN.fullmatch(normalized):
            raise ValueError("conversation_id must be generated as conv_ + uuid4().hex.")
        return normalized

    @field_validator("participants", mode="before")
    @classmethod
    def normalize_participants(cls, value: object) -> tuple[str, str]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("Conversation participants must be a two-user list.")
        normalized = tuple(str(user_id).strip() for user_id in value)
        if len(normalized) != 2:
            raise ValueError("C19C supports one-to-one conversations only.")
        if any(not user_id for user_id in normalized):
            raise ValueError("Conversation participant user_id must not be empty.")
        if normalized[0] == normalized[1]:
            raise ValueError("Conversation participants must be distinct users.")
        return normalized


class Message(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    message_id: str = Field(default_factory=generate_message_id)

    from_user_id: str = Field(min_length=1, max_length=255)
    to_user_id: str = Field(min_length=1, max_length=255)

    conversation_id: str = Field(min_length=1, max_length=64)

    content_type: MessageContentType
    content: str = Field(min_length=1, max_length=4000)

    status: MessageStatus = MessageStatus.SENT

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    attachments: list[Attachment] = Field(default_factory=list)
    media_type: MessageContentType | None = None

    @model_validator(mode="before")
    @classmethod
    def default_media_type_from_content_type(cls, value: object) -> object:
        if isinstance(value, dict) and "media_type" not in value:
            data = dict(value)
            if "content_type" in data:
                data["media_type"] = data["content_type"]
            return data
        return value

    @field_validator("message_id")
    @classmethod
    def validate_message_id(cls, value: str) -> str:
        normalized = value.strip()
        if not MESSAGE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("message_id must be generated as msg_ + uuid4().hex.")
        return normalized

    @field_validator("from_user_id", "to_user_id", "content")
    @classmethod
    def normalize_required_text(cls, value: str, info) -> str:
        return _normalize_non_empty(value, field_name=info.field_name)

    @field_validator("conversation_id")
    @classmethod
    def validate_message_conversation_id(cls, value: str) -> str:
        normalized = value.strip()
        if not CONVERSATION_ID_PATTERN.fullmatch(normalized):
            raise ValueError("conversation_id must reference a Conversation.")
        return normalized

    @model_validator(mode="after")
    def validate_message_shape(self) -> "Message":
        if self.from_user_id == self.to_user_id:
            raise ValueError("Message sender and recipient must be distinct users.")
        if self.media_type is None:
            object.__setattr__(self, "media_type", self.content_type)
        elif self.media_type != self.content_type:
            raise ValueError("media_type is reserved and must match content_type.")
        if self.updated_at < self.created_at:
            raise ValueError("Message updated_at must not be before created_at.")
        return self


class MessageSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_user_id: str = Field(min_length=1, max_length=255)
    to_user_id: str = Field(min_length=1, max_length=255)
    conversation_id: str = Field(min_length=1, max_length=64)
    content_type: MessageContentType
    content: str = Field(min_length=1, max_length=4000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=0)
    media_type: MessageContentType | None = None

    @field_validator("from_user_id", "to_user_id", "content")
    @classmethod
    def normalize_send_text(cls, value: str, info) -> str:
        return _normalize_non_empty(value, field_name=info.field_name)

    @field_validator("conversation_id")
    @classmethod
    def validate_send_conversation_id(cls, value: str) -> str:
        normalized = value.strip()
        if not CONVERSATION_ID_PATTERN.fullmatch(normalized):
            raise ValueError("conversation_id must reference a Conversation.")
        return normalized

    @model_validator(mode="after")
    def validate_send_request(self) -> "MessageSendRequest":
        if self.from_user_id == self.to_user_id:
            raise ValueError("Message sender and recipient must be distinct users.")
        if self.attachments:
            raise ValueError("C19C does not allow message attachments.")
        if self.media_type is not None and self.media_type != self.content_type:
            raise ValueError("media_type is reserved and must match content_type.")
        return self


class MessageReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1, max_length=64)
    reader_user_id: str = Field(min_length=1, max_length=255)
    message_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("conversation_id")
    @classmethod
    def validate_read_conversation_id(cls, value: str) -> str:
        normalized = value.strip()
        if not CONVERSATION_ID_PATTERN.fullmatch(normalized):
            raise ValueError("conversation_id must reference a Conversation.")
        return normalized

    @field_validator("reader_user_id")
    @classmethod
    def normalize_reader_user_id(cls, value: str) -> str:
        return _normalize_non_empty(value, field_name="reader_user_id")

    @field_validator("message_ids")
    @classmethod
    def validate_message_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for message_id in value:
            normalized_id = str(message_id).strip()
            if not MESSAGE_ID_PATTERN.fullmatch(normalized_id):
                raise ValueError("message_ids must reference Message.message_id.")
            normalized.append(normalized_id)
        if len(set(normalized)) != len(normalized):
            raise ValueError("message_ids must not contain duplicates.")
        return normalized


class MessageConversationBindingDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str = Field(min_length=1, max_length=64)
    conversation_id: str = Field(min_length=1, max_length=64)
    from_user_id: str = Field(min_length=1, max_length=255)
    to_user_id: str = Field(min_length=1, max_length=255)
    participants: tuple[str, str]
    allowed: bool
    denied: bool
    denial_code: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=500)
    message_must_bind_conversation_id: Literal[True] = True
    participants_must_include_sender_and_recipient: Literal[True] = True
    group_chat_logic_implemented: Literal[False] = False

    @model_validator(mode="after")
    def validate_decision(self) -> "MessageConversationBindingDecision":
        if self.allowed == self.denied:
            raise ValueError("Message binding decision allowed/denied mismatch.")
        if self.allowed and self.denial_code is not None:
            raise ValueError("Allowed message binding decisions must not be denied.")
        if self.denied and self.denial_code is None:
            raise ValueError("Denied message binding decisions need denial_code.")
        return self


class MessageBindingError(PermissionError):
    pass


def evaluate_message_conversation_binding(
    *,
    message: Message,
    conversation: Conversation,
) -> MessageConversationBindingDecision:
    participants = conversation.participants

    def decision(
        *,
        allowed: bool,
        denial_code: str | None,
        reason: str,
    ) -> MessageConversationBindingDecision:
        return MessageConversationBindingDecision(
            message_id=message.message_id,
            conversation_id=message.conversation_id,
            from_user_id=message.from_user_id,
            to_user_id=message.to_user_id,
            participants=participants,
            allowed=allowed,
            denied=not allowed,
            denial_code=denial_code,
            reason=reason,
        )

    if message.conversation_id != conversation.conversation_id:
        return decision(
            allowed=False,
            denial_code="c19c_conversation_id_mismatch",
            reason="Message conversation_id must match the target Conversation.",
        )

    required_participants = {message.from_user_id, message.to_user_id}
    if required_participants != set(participants):
        return decision(
            allowed=False,
            denial_code="c19c_message_participants_denied",
            reason="Message sender and recipient must be Conversation participants.",
        )

    return decision(
        allowed=True,
        denial_code=None,
        reason="Message is bound to the conversation and both users participate.",
    )


def enforce_message_conversation_binding(
    *,
    message: Message,
    conversation: Conversation,
) -> MessageConversationBindingDecision:
    decision = evaluate_message_conversation_binding(
        message=message,
        conversation=conversation,
    )
    if decision.denied:
        raise MessageBindingError(decision.reason)
    return decision


class MessageStatusTransitionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current_status: MessageStatus
    target_status: MessageStatus
    allowed: bool
    denied: bool
    denial_code: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=500)
    flow: tuple[Literal["sent"], Literal["delivered"], Literal["read"]] = (
        "sent",
        "delivered",
        "read",
    )

    @model_validator(mode="after")
    def validate_transition_decision(self) -> "MessageStatusTransitionDecision":
        if self.allowed == self.denied:
            raise ValueError("Message status decision allowed/denied mismatch.")
        if self.allowed and self.denial_code is not None:
            raise ValueError("Allowed status decisions must not include denial_code.")
        if self.denied and self.denial_code is None:
            raise ValueError("Denied status decisions need denial_code.")
        return self


class MessageStatusTransitionError(ValueError):
    pass


_NEXT_STATUS: dict[MessageStatus, MessageStatus] = {
    MessageStatus.SENT: MessageStatus.DELIVERED,
    MessageStatus.DELIVERED: MessageStatus.READ,
}


def evaluate_message_status_transition(
    *,
    current_status: MessageStatus | str,
    target_status: MessageStatus | str,
) -> MessageStatusTransitionDecision:
    current = MessageStatus(current_status)
    target = MessageStatus(target_status)

    def decision(
        *,
        allowed: bool,
        denial_code: str | None,
        reason: str,
    ) -> MessageStatusTransitionDecision:
        return MessageStatusTransitionDecision(
            current_status=current,
            target_status=target,
            allowed=allowed,
            denied=not allowed,
            denial_code=denial_code,
            reason=reason,
        )

    if current == target:
        return decision(
            allowed=True,
            denial_code=None,
            reason="Message status transition is idempotent.",
        )
    if _NEXT_STATUS.get(current) == target:
        return decision(
            allowed=True,
            denial_code=None,
            reason="Message status follows sent -> delivered -> read.",
        )
    return decision(
        allowed=False,
        denial_code="c19c_invalid_message_status_transition",
        reason="Message status can only progress sent -> delivered -> read.",
    )


def enforce_message_status_transition(
    *,
    current_status: MessageStatus | str,
    target_status: MessageStatus | str,
) -> MessageStatusTransitionDecision:
    decision = evaluate_message_status_transition(
        current_status=current_status,
        target_status=target_status,
    )
    if decision.denied:
        raise MessageStatusTransitionError(decision.reason)
    return decision


class MessageContentRestrictionRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c19c_message_content_restrictions_v1"] = (
        "c19c_message_content_restrictions_v1"
    )
    allowed_content_types: tuple[Literal["text"], Literal["emoji"]] = (
        "text",
        "emoji",
    )
    unsupported_content_types: tuple[
        Literal["voice"],
        Literal["video"],
        Literal["file"],
        Literal["image"],
    ] = ("voice", "video", "file", "image")
    unsupported_content_type_rule: Literal["DENY"] = "DENY"
    attachments_allowed: Literal[False] = False
    file_image_voice_video_implemented: Literal[False] = False


class MessageStateMachine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state_machine_id: Literal["c19c_message_state_machine_v1"] = (
        "c19c_message_state_machine_v1"
    )
    flow: tuple[Literal["sent"], Literal["delivered"], Literal["read"]] = (
        "sent",
        "delivered",
        "read",
    )
    sent_definition: Literal["message accepted by internal send boundary"] = (
        "message accepted by internal send boundary"
    )
    delivered_definition: Literal["recipient internal client received message"] = (
        "recipient internal client received message"
    )
    read_definition: Literal["recipient opened or read message"] = (
        "recipient opened or read message"
    )
    backwards_transition_allowed: Literal[False] = False
    skip_transition_allowed: Literal[False] = False


class MessageDatabaseSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["c19c_messages_table_v1"] = "c19c_messages_table_v1"
    table_name: Literal["messages"] = "messages"
    primary_key: Literal["message_id"] = "message_id"
    columns: tuple[
        Literal["message_id"],
        Literal["from_user_id"],
        Literal["to_user_id"],
        Literal["conversation_id"],
        Literal["content_type"],
        Literal["content"],
        Literal["status"],
        Literal["created_at"],
        Literal["updated_at"],
    ] = (
        "message_id",
        "from_user_id",
        "to_user_id",
        "conversation_id",
        "content_type",
        "content",
        "status",
        "created_at",
        "updated_at",
    )
    required_indexes: tuple[
        Literal["conversation_id"],
        Literal["from_user_id"],
        Literal["to_user_id"],
    ] = ("conversation_id", "from_user_id", "to_user_id")
    content_type_check_values: tuple[Literal["text"], Literal["emoji"]] = (
        "text",
        "emoji",
    )
    status_check_values: tuple[Literal["sent"], Literal["delivered"], Literal["read"]] = (
        "sent",
        "delivered",
        "read",
    )
    attachments_column_implemented: Literal[False] = False
    media_type_column_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


class MessageApiEndpointDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["POST", "GET"]
    path: str = Field(min_length=1, max_length=120)
    operation: MessageOperation
    authenticated_internal_user_required: Literal[True] = True
    external_access_allowed: Literal[False] = False
    notes: str = Field(min_length=1, max_length=500)


class MessageApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c19c_message_api_design_v1"] = (
        "c19c_message_api_design_v1"
    )
    endpoints: tuple[
        MessageApiEndpointDesign,
        MessageApiEndpointDesign,
        MessageApiEndpointDesign,
    ] = (
        MessageApiEndpointDesign(
            method="POST",
            path="/messages/send",
            operation=MessageOperation.SEND,
            notes="Send accepts only text or emoji and requires a valid conversation.",
        ),
        MessageApiEndpointDesign(
            method="GET",
            path="/messages/{conversation_id}",
            operation=MessageOperation.FETCH_BY_CONVERSATION,
            notes="Fetch returns messages only for a conversation participant.",
        ),
        MessageApiEndpointDesign(
            method="POST",
            path="/messages/read",
            operation=MessageOperation.MARK_READ,
            notes="Mark read can only progress delivered messages to read.",
        ),
    )
    mounted_under_application_api_prefix: Literal[True] = True
    public_api_exposure_allowed: Literal[False] = False
    websocket_implemented: Literal[False] = False
    group_chat_implemented: Literal[False] = False
    file_image_voice_video_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


class MessageIntegrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c19c_c18_c19_integration_v1"] = (
        "c19c_c18_c19_integration_v1"
    )
    c19a_contact_identity_source: Literal["contact_identities"] = (
        "contact_identities"
    )
    c19b_contact_directory_source: Literal["GlobalContactDirectory"] = (
        "GlobalContactDirectory"
    )
    c18c_org_membership_source: Literal["org_memberships"] = "org_memberships"
    c18h_future_org_context_source: Literal["future org context routing"] = (
        "future org context routing"
    )
    c18g_future_org_isolation_binding: Literal["future org isolation enforcement"] = (
        "future org isolation enforcement"
    )
    modifies_c19a: Literal[False] = False
    modifies_c19b: Literal[False] = False
    modifies_c18_system: Literal[False] = False


class MessageSecurityModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    security_id: Literal["c19c_message_security_v1"] = (
        "c19c_message_security_v1"
    )
    internal_only: Literal[True] = True
    external_api_exposure_allowed: Literal[False] = False
    public_api_mount_allowed: Literal[False] = False
    authenticated_user_required: Literal[True] = True
    sender_and_recipient_must_be_conversation_participants: Literal[True] = True
    user_must_exist_in_c18c: Literal[True] = True
    org_isolation_enforced_via_c18g_future_binding: Literal[True] = True
    stores_passwords_tokens_or_external_channels: Literal[False] = False
    file_image_voice_video_allowed: Literal[False] = False


class MessageCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19C"] = "C19C"
    component: Literal["Message System Schema"] = "Message System Schema"
    completion_status: Literal["complete"] = "complete"
    message_schema_defined: Literal[True] = True
    conversation_binding_logic_defined: Literal[True] = True
    content_restriction_rules_defined: Literal[True] = True
    message_state_machine_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    database_schema_defined: Literal[True] = True
    c19a_integrated: Literal[True] = True
    c19b_integrated: Literal[True] = True
    c18c_integrated: Literal[True] = True
    c18h_future_routing_reserved: Literal[True] = True
    security_boundary_defined: Literal[True] = True
    ui_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False
    group_chat_implemented: Literal[False] = False
    file_image_voice_video_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


class MessageApiRuntimeNotice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19C"] = "C19C"
    schema_only: Literal[True] = True
    operation: MessageOperation
    detail: Literal[
        "C19C defines the internal message schema and API contract only."
    ] = "C19C defines the internal message schema and API contract only."
    persistence_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False


MESSAGE_SQL_SCHEMA = """
CREATE TABLE messages (
    message_id TEXT PRIMARY KEY,
    from_user_id TEXT,
    to_user_id TEXT,
    conversation_id TEXT,
    content_type TEXT CHECK (content_type IN ('text', 'emoji')),
    content TEXT,
    status TEXT CHECK (status IN ('sent', 'delivered', 'read')),
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX ix_messages_conversation_id
    ON messages (conversation_id);

CREATE INDEX ix_messages_from_user_id
    ON messages (from_user_id);

CREATE INDEX ix_messages_to_user_id
    ON messages (to_user_id);
""".strip()


MESSAGE_DATA_FLOW_DIAGRAM = """
POST /messages/send
  -> authenticated internal user
  -> C19A contact identity exists
  -> C19B directory can resolve recipient identity
  -> active C18C membership exists for sender and recipient
  -> future C18G org isolation and C18H org context apply
  -> validate Conversation.participants
  -> validate content_type in text, emoji
  -> Message(status = sent)
""".strip()


def get_message_content_restriction_rules() -> MessageContentRestrictionRules:
    return MessageContentRestrictionRules()


def get_message_state_machine() -> MessageStateMachine:
    return MessageStateMachine()


def get_message_database_schema() -> MessageDatabaseSchema:
    return MessageDatabaseSchema()


def get_message_api_design() -> MessageApiDesign:
    return MessageApiDesign()


def get_message_integration_model() -> MessageIntegrationModel:
    return MessageIntegrationModel()


def get_message_security_model() -> MessageSecurityModel:
    return MessageSecurityModel()


def get_message_completion_status() -> MessageCompletionStatus:
    return MessageCompletionStatus()
