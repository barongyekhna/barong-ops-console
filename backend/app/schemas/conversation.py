from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CONVERSATION_ID_PATTERN = re.compile(r"^conv_[0-9a-f]{32}$")
DIRECT_CONVERSATION_HASH_VERSION = "c19d_direct_sha256_sorted_pair_v1"


class ConversationType(StrEnum):
    DIRECT = "direct"
    GROUP = "group"


class ConversationOperation(StrEnum):
    CREATE = "create"
    GET = "get"
    LIST_BY_USER = "list_by_user"


def _normalize_user_id(value: str | int, *, field_name: str = "user_id") -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


def normalize_conversation_participants(
    participants: list[str] | tuple[str, ...],
) -> list[str]:
    if not isinstance(participants, (list, tuple)):
        raise ValueError("participants must be a list of user IDs.")

    normalized = [
        _normalize_user_id(user_id, field_name="participant user_id")
        for user_id in participants
    ]
    if len(set(normalized)) != len(normalized):
        raise ValueError("participants must not contain duplicate user IDs.")
    return normalized


def canonical_direct_participants(user_a: str | int, user_b: str | int) -> list[str]:
    participants = normalize_conversation_participants([str(user_a), str(user_b)])
    if len(participants) != 2:
        raise ValueError("direct conversations require exactly two participants.")
    return sorted(participants)


def generate_direct_conversation_id(user_a: str | int, user_b: str | int) -> str:
    participants = canonical_direct_participants(user_a, user_b)
    digest = hashlib.sha256("|".join(participants).encode("utf-8")).hexdigest()
    return "conv_" + digest[:32]


def generate_group_conversation_id() -> str:
    return "conv_" + uuid4().hex


class Conversation(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    conversation_id: str
    type: ConversationType = ConversationType.DIRECT
    participants: list[str] = Field(min_length=2, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="before")
    @classmethod
    def default_conversation_id(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        if data.get("conversation_id"):
            return data

        raw_type = data.get("type", ConversationType.DIRECT)
        conversation_type = (
            raw_type.value
            if isinstance(raw_type, ConversationType)
            else str(raw_type).strip()
        )
        participants = data.get("participants")
        if participants is None:
            return data

        if conversation_type == ConversationType.DIRECT.value:
            normalized = normalize_conversation_participants(participants)
            if len(normalized) == 2:
                data["conversation_id"] = generate_direct_conversation_id(
                    normalized[0],
                    normalized[1],
                )
        elif conversation_type == ConversationType.GROUP.value:
            data["conversation_id"] = generate_group_conversation_id()
        return data

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str) -> str:
        normalized = value.strip()
        if not CONVERSATION_ID_PATTERN.fullmatch(normalized):
            raise ValueError("conversation_id must be conv_ + 32 lowercase hex chars.")
        return normalized

    @field_validator("participants", mode="before")
    @classmethod
    def validate_participants(cls, value: object) -> list[str]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("participants must be a list of user IDs.")
        return normalize_conversation_participants(value)

    @model_validator(mode="after")
    def validate_conversation_shape(self) -> "Conversation":
        if self.type == ConversationType.DIRECT:
            if len(self.participants) != 2:
                raise ValueError("direct conversations require exactly two participants.")
            canonical = canonical_direct_participants(
                self.participants[0],
                self.participants[1],
            )
            expected_conversation_id = generate_direct_conversation_id(
                canonical[0],
                canonical[1],
            )
            if self.conversation_id != expected_conversation_id:
                raise ValueError(
                    "direct conversation_id must be generated from the sorted pair."
                )
            object.__setattr__(self, "participants", canonical)

        if self.type == ConversationType.GROUP and len(self.participants) < 3:
            raise ValueError("group conversations require at least three participants.")

        if self.updated_at < self.created_at:
            raise ValueError("Conversation updated_at must not be before created_at.")
        return self


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ConversationType = ConversationType.DIRECT
    participants: list[str] = Field(min_length=2, max_length=200)

    @field_validator("participants", mode="before")
    @classmethod
    def validate_request_participants(cls, value: object) -> list[str]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("participants must be a list of user IDs.")
        return normalize_conversation_participants(value)

    @model_validator(mode="after")
    def validate_request_shape(self) -> "ConversationCreateRequest":
        if self.type == ConversationType.DIRECT:
            if len(self.participants) != 2:
                raise ValueError("direct conversations require exactly two participants.")
            object.__setattr__(self, "participants", sorted(self.participants))
        elif len(self.participants) < 3:
            raise ValueError("group conversations require at least three participants.")
        return self


class ConversationParticipantResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)
    org_id: str = Field(min_length=1, max_length=40)
    c19a_identity_found: Literal[True] = True
    c19b_directory_contact_resolved: Literal[True] = True
    c18c_active_membership_found: Literal[True] = True


class DirectConversationGenerationLogic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    logic_id: Literal["c19d_direct_conversation_generation_v1"] = (
        "c19d_direct_conversation_generation_v1"
    )
    hash_version: Literal["c19d_direct_sha256_sorted_pair_v1"] = (
        DIRECT_CONVERSATION_HASH_VERSION
    )
    input_rule: Literal["two distinct internal user IDs"] = (
        "two distinct internal user IDs"
    )
    canonicalization_rule: Literal["strip user IDs, reject blanks, sort ascending"] = (
        "strip user IDs, reject blanks, sort ascending"
    )
    algorithm: Literal["conv_ + sha256('|'.join(sorted_pair))[:32]"] = (
        "conv_ + sha256('|'.join(sorted_pair))[:32]"
    )
    same_pair_reuses_same_conversation: Literal[True] = True
    participant_order_changes_id: Literal[False] = False
    group_generation_logic_implemented: Literal[False] = False


class ConversationUniquenessStrategy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: Literal["c19d_conversation_uniqueness_v1"] = (
        "c19d_conversation_uniqueness_v1"
    )
    direct_conversation_id_is_deterministic: Literal[True] = True
    direct_pair_duplicate_creation_allowed: Literal[False] = False
    direct_pair_lookup_key: Literal["sorted participant pair hash"] = (
        "sorted participant pair hash"
    )
    persistence_unique_key: Literal["conversation_id"] = "conversation_id"
    current_runtime_storage: Literal["process registry; no migration executed"] = (
        "process registry; no migration executed"
    )
    future_database_strategy: Literal[
        "conversation_id primary key plus participant indexes"
    ] = "conversation_id primary key plus participant indexes"


class ConversationDatabaseSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["c19d_conversations_table_v1"] = (
        "c19d_conversations_table_v1"
    )
    table_name: Literal["conversations"] = "conversations"
    primary_key: Literal["conversation_id"] = "conversation_id"
    columns: tuple[
        Literal["conversation_id"],
        Literal["type"],
        Literal["participants"],
        Literal["created_at"],
        Literal["updated_at"],
    ] = (
        "conversation_id",
        "type",
        "participants",
        "created_at",
        "updated_at",
    )
    type_check_values: tuple[Literal["direct"], Literal["group"]] = (
        "direct",
        "group",
    )
    direct_participant_count: Literal[2] = 2
    group_minimum_participant_count: Literal[3] = 3
    direct_conversation_id_is_unique: Literal[True] = True
    participant_indexing_reserved: Literal[True] = True
    group_logic_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


class ConversationApiEndpointDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["POST", "GET"]
    path: str = Field(min_length=1, max_length=160)
    operation: ConversationOperation
    authenticated_internal_user_required: Literal[True] = True
    c18c_active_member_required: Literal[True] = True
    external_access_allowed: Literal[False] = False
    notes: str = Field(min_length=1, max_length=500)


class ConversationApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c19d_conversation_api_design_v1"] = (
        "c19d_conversation_api_design_v1"
    )
    endpoints: tuple[
        ConversationApiEndpointDesign,
        ConversationApiEndpointDesign,
        ConversationApiEndpointDesign,
    ] = (
        ConversationApiEndpointDesign(
            method="POST",
            path="/conversations/create",
            operation=ConversationOperation.CREATE,
            notes=(
                "Creates or reuses a direct conversation from a valid two-user "
                "C19B contact pair."
            ),
        ),
        ConversationApiEndpointDesign(
            method="GET",
            path="/conversations/{conversation_id}",
            operation=ConversationOperation.GET,
            notes="Reads a conversation only for an authenticated participant.",
        ),
        ConversationApiEndpointDesign(
            method="GET",
            path="/conversations/user/{user_id}",
            operation=ConversationOperation.LIST_BY_USER,
            notes="Lists conversations only for the requesting participant user.",
        ),
    )
    mounted_under_application_api_prefix: Literal[True] = True
    public_api_exposure_allowed: Literal[False] = False
    websocket_implemented: Literal[False] = False
    group_api_expansion_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


class ConversationIntegrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c19d_c18_c19_integration_v1"] = (
        "c19d_c18_c19_integration_v1"
    )
    c19a_identity_validation_source: Literal["contact_identities"] = (
        "contact_identities"
    )
    c19b_contact_resolution_source: Literal["GlobalContactDirectory"] = (
        "GlobalContactDirectory"
    )
    c19c_message_binding_rule: Literal[
        "Message.conversation_id must reference Conversation.conversation_id"
    ] = "Message.conversation_id must reference Conversation.conversation_id"
    c18c_org_membership_source: Literal["org_memberships"] = "org_memberships"
    c18g_future_cross_org_leakage_guard: Literal["future C18G enforcement"] = (
        "future C18G enforcement"
    )
    modifies_c19a: Literal[False] = False
    modifies_c19b: Literal[False] = False
    modifies_c19c: Literal[False] = False
    modifies_c18_system: Literal[False] = False


class GroupConversationReservedDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c19d_group_conversation_reserved_v1"] = (
        "c19d_group_conversation_reserved_v1"
    )
    schema_type_value: Literal["group"] = "group"
    minimum_participants: Literal[3] = 3
    schema_validation_defined: Literal[True] = True
    creation_logic_implemented: Literal[False] = False
    message_logic_implemented: Literal[False] = False
    api_expansion_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False


class ConversationSecurityModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    security_id: Literal["c19d_conversation_security_v1"] = (
        "c19d_conversation_security_v1"
    )
    internal_only: Literal[True] = True
    external_api_exposure_allowed: Literal[False] = False
    authenticated_user_required: Literal[True] = True
    actor_must_be_conversation_participant: Literal[True] = True
    participants_must_exist_in_c19b_directory: Literal[True] = True
    participants_must_have_c19a_identity: Literal[True] = True
    participants_must_have_active_c18c_membership: Literal[True] = True
    cross_org_leakage_allowed: Literal[False] = False
    c18g_full_cross_org_enforcement_reserved: Literal[True] = True
    stores_external_channels_or_tokens: Literal[False] = False


class ConversationCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19D"] = "C19D"
    component: Literal["Conversation System"] = "Conversation System"
    completion_status: Literal["complete"] = "complete"
    conversation_schema_defined: Literal[True] = True
    direct_generation_logic_defined: Literal[True] = True
    uniqueness_strategy_defined: Literal[True] = True
    database_schema_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    c19b_contact_resolution_integrated: Literal[True] = True
    c19c_message_binding_integrated: Literal[True] = True
    c19a_identity_validation_integrated: Literal[True] = True
    c18c_membership_validation_integrated: Literal[True] = True
    group_chat_reserved: Literal[True] = True
    group_chat_implemented: Literal[False] = False
    ui_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


class ConversationApiRuntimeNotice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19D"] = "C19D"
    operation: ConversationOperation
    detail: str = Field(min_length=1, max_length=500)
    group_chat_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


CONVERSATION_SQL_SCHEMA = """
CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY,
    type TEXT CHECK (type IN ('direct', 'group')) NOT NULL,
    participants TEXT NOT NULL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX ix_conversations_updated_at
    ON conversations(updated_at);
""".strip()


CONVERSATION_DATA_FLOW_DIAGRAM = """
POST /conversations/create
  -> authenticated internal user
  -> request type must be direct
  -> normalize and sort two participant user IDs
  -> actor user_id must be one of the participants
  -> C19A contact identity exists for each participant
  -> C19B contact directory resolves each participant
  -> active C18C membership exists for each participant
  -> generate conv_ + sha256('|'.join(sorted_pair))[:32]
  -> reuse existing conversation when the deterministic ID is already present
  -> return Conversation(conversation_id, type, participants, created_at, updated_at)
  -> C19C messages must bind Message.conversation_id to this conversation_id
""".strip()


def get_direct_conversation_generation_logic() -> DirectConversationGenerationLogic:
    return DirectConversationGenerationLogic()


def get_conversation_uniqueness_strategy() -> ConversationUniquenessStrategy:
    return ConversationUniquenessStrategy()


def get_conversation_database_schema() -> ConversationDatabaseSchema:
    return ConversationDatabaseSchema()


def get_conversation_api_design() -> ConversationApiDesign:
    return ConversationApiDesign()


def get_conversation_integration_model() -> ConversationIntegrationModel:
    return ConversationIntegrationModel()


def get_group_conversation_reserved_design() -> GroupConversationReservedDesign:
    return GroupConversationReservedDesign()


def get_conversation_security_model() -> ConversationSecurityModel:
    return ConversationSecurityModel()


def get_conversation_completion_status() -> ConversationCompletionStatus:
    return ConversationCompletionStatus()
