from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .cross_org_communication import CrossOrgDecision


class MessagingFeature(StrEnum):
    TEXT = "text"
    EMOJI = "emoji"
    IMAGE = "image"
    FILE = "file"
    VOICE = "voice"
    VIDEO = "video"


class FriendStatus(StrEnum):
    NONE = "none"
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class FriendRequestStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


BASE_MESSAGING_FEATURES: tuple[MessagingFeature, MessagingFeature] = (
    MessagingFeature.TEXT,
    MessagingFeature.EMOJI,
)
ADVANCED_MESSAGING_FEATURES: tuple[
    MessagingFeature,
    MessagingFeature,
    MessagingFeature,
    MessagingFeature,
] = (
    MessagingFeature.IMAGE,
    MessagingFeature.FILE,
    MessagingFeature.VOICE,
    MessagingFeature.VIDEO,
)
FULL_MESSAGING_FEATURES: tuple[
    MessagingFeature,
    MessagingFeature,
    MessagingFeature,
    MessagingFeature,
    MessagingFeature,
    MessagingFeature,
] = BASE_MESSAGING_FEATURES + ADVANCED_MESSAGING_FEATURES


def _normalize_user_id(value: str | int, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


def _friend_status(value: FriendStatus | FriendRequestStatus | str) -> FriendStatus:
    if isinstance(value, FriendStatus):
        return value
    return FriendStatus(str(value).strip())


def _content_type(value: MessagingFeature | str) -> MessagingFeature:
    if isinstance(value, MessagingFeature):
        return value
    return MessagingFeature(str(value).strip())


def unlocked_features_for_status(
    friend_status: FriendStatus | FriendRequestStatus | str,
    *,
    can_chat: bool = True,
) -> tuple[MessagingFeature, ...]:
    status = _friend_status(friend_status)
    if not can_chat or status == FriendStatus.REJECTED:
        return ()
    if status == FriendStatus.ACCEPTED:
        return FULL_MESSAGING_FEATURES
    return BASE_MESSAGING_FEATURES


class MessagingPermission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)
    target_user_id: str = Field(min_length=1, max_length=255)
    can_chat: bool = True
    friend_status: FriendStatus = FriendStatus.NONE
    unlocked_features: list[MessagingFeature] = Field(default_factory=list)

    @field_validator("user_id", "target_user_id")
    @classmethod
    def normalize_user_id(cls, value: str, info) -> str:
        return _normalize_user_id(value, field_name=info.field_name)

    @field_validator("unlocked_features", mode="before")
    @classmethod
    def normalize_unlocked_features(cls, value: object) -> list[MessagingFeature]:
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise ValueError("unlocked_features must be a list.")
        normalized: list[MessagingFeature] = []
        for item in value:
            feature = _content_type(item)
            if feature not in normalized:
                normalized.append(feature)
        return normalized

    @model_validator(mode="after")
    def validate_permission_shape(self) -> "MessagingPermission":
        if self.user_id == self.target_user_id:
            raise ValueError("MessagingPermission users must be distinct.")

        expected = list(
            unlocked_features_for_status(
                self.friend_status,
                can_chat=self.can_chat,
            )
        )
        if "unlocked_features" not in self.model_fields_set:
            object.__setattr__(self, "unlocked_features", expected)
            return self
        if self.unlocked_features != expected:
            raise ValueError(
                "unlocked_features must match the C19F friend unlock rules."
            )
        return self


class FriendRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    from_user_id: str = Field(min_length=1, max_length=255)
    to_user_id: str = Field(min_length=1, max_length=255)
    status: FriendRequestStatus = FriendRequestStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("from_user_id", "to_user_id")
    @classmethod
    def normalize_user_id(cls, value: str, info) -> str:
        return _normalize_user_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_request_shape(self) -> "FriendRequest":
        if self.from_user_id == self.to_user_id:
            raise ValueError("FriendRequest users must be distinct.")
        return self


class FriendRequestCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_user_id: str = Field(min_length=1, max_length=255)

    @field_validator("to_user_id")
    @classmethod
    def normalize_to_user_id(cls, value: str) -> str:
        return _normalize_user_id(value, field_name="to_user_id")


class FriendActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_user_id: str = Field(min_length=1, max_length=255)

    @field_validator("from_user_id")
    @classmethod
    def normalize_from_user_id(cls, value: str) -> str:
        return _normalize_user_id(value, field_name="from_user_id")


class MessagingPermissionCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_user_id: str = Field(min_length=1, max_length=255)
    receiver_user_id: str = Field(min_length=1, max_length=255)
    content_type: MessagingFeature

    @field_validator("sender_user_id", "receiver_user_id")
    @classmethod
    def normalize_user_id(cls, value: str, info) -> str:
        return _normalize_user_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_distinct_users(self) -> "MessagingPermissionCheckRequest":
        if self.sender_user_id == self.receiver_user_id:
            raise ValueError("sender_user_id and receiver_user_id must be distinct.")
        return self


class MessagingPermissionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19F"] = "C19F"
    sender_user_id: str = Field(min_length=1, max_length=255)
    receiver_user_id: str = Field(min_length=1, max_length=255)
    content_type: MessagingFeature
    permission: MessagingPermission
    same_org: bool | None = None
    allowed: bool
    denied: bool
    denial_code: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=500)
    c19e_gate_checked: bool = False
    c19e_decision: CrossOrgDecision | None = None
    c19c_message_schema_integrated: Literal[True] = True
    c19d_conversation_system_integrated: Literal[True] = True
    c19e_cross_org_gate_integrated: Literal[True] = True
    c19a_identity_system_integrated: Literal[True] = True
    c18g_data_isolation_boundary_preserved: Literal[True] = True
    ui_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False
    media_payload_implemented: Literal[False] = False
    voice_video_implemented: Literal[False] = False
    group_chat_implemented: Literal[False] = False

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "MessagingPermissionDecision":
        if self.allowed == self.denied:
            raise ValueError("Messaging permission allowed/denied mismatch.")
        if self.allowed and self.denial_code is not None:
            raise ValueError(
                "Allowed messaging decisions must not include denial_code."
            )
        if self.denied and self.denial_code is None:
            raise ValueError("Denied messaging decisions must include denial_code.")
        if (
            self.allowed
            and self.content_type not in self.permission.unlocked_features
        ):
            raise ValueError("Allowed content_type must be an unlocked feature.")
        return self


class MessagingPermissionApiEndpointDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["GET", "POST"]
    path: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=500)
    authenticated_internal_user_required: Literal[True] = True
    user_to_user_scoped: Literal[True] = True


class MessagingPermissionApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c19f_messaging_permission_api_design_v1"] = (
        "c19f_messaging_permission_api_design_v1"
    )
    endpoints: tuple[
        MessagingPermissionApiEndpointDesign,
        MessagingPermissionApiEndpointDesign,
        MessagingPermissionApiEndpointDesign,
        MessagingPermissionApiEndpointDesign,
        MessagingPermissionApiEndpointDesign,
    ] = (
        MessagingPermissionApiEndpointDesign(
            method="POST",
            path="/friends/request",
            purpose="Create a pending user-to-user friend request.",
        ),
        MessagingPermissionApiEndpointDesign(
            method="POST",
            path="/friends/accept",
            purpose="Accept an incoming friend request and unlock full features.",
        ),
        MessagingPermissionApiEndpointDesign(
            method="POST",
            path="/friends/reject",
            purpose="Reject an incoming friend request and block communication.",
        ),
        MessagingPermissionApiEndpointDesign(
            method="GET",
            path="/friends/list",
            purpose="List friend requests involving the authenticated user.",
        ),
        MessagingPermissionApiEndpointDesign(
            method="POST",
            path="/messages/permission/check",
            purpose="Evaluate whether sender can use a content type with receiver.",
        ),
    )
    mounted_under_application_api_prefix: Literal[True] = True
    public_api_exposure_allowed: Literal[False] = False
    websocket_implemented: Literal[False] = False
    group_chat_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


class MessagingFeatureUnlockingRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c19f_feature_unlocking_rules_v1"] = (
        "c19f_feature_unlocking_rules_v1"
    )
    default_internal_can_chat: Literal[True] = True
    level_1_internal_features: tuple[Literal["text"], Literal["emoji"]] = (
        "text",
        "emoji",
    )
    level_2_friend_features: tuple[
        Literal["text"],
        Literal["emoji"],
        Literal["image"],
        Literal["file"],
        Literal["voice"],
        Literal["video"],
    ] = ("text", "emoji", "image", "file", "voice", "video")
    level_3_blocked_features: tuple[str, ...] = ()
    pending_request_features: tuple[Literal["text"], Literal["emoji"]] = (
        "text",
        "emoji",
    )
    image_requires_friend: Literal[True] = True
    file_requires_friend: Literal[True] = True
    voice_requires_friend: Literal[True] = True
    video_requires_friend: Literal[True] = True
    rejected_blocks_chat: Literal[True] = True
    owner_or_admin_bypass_allowed: Literal[False] = False


class MessagingPermissionDatabaseSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["c19f_messaging_permissions_tables_v1"] = (
        "c19f_messaging_permissions_tables_v1"
    )
    permission_table_name: Literal["messaging_permissions"] = (
        "messaging_permissions"
    )
    friend_request_table_name: Literal["friend_requests"] = "friend_requests"
    permission_columns: tuple[
        Literal["user_id"],
        Literal["target_user_id"],
        Literal["can_chat"],
        Literal["friend_status"],
        Literal["unlocked_features"],
    ] = (
        "user_id",
        "target_user_id",
        "can_chat",
        "friend_status",
        "unlocked_features",
    )
    friend_request_columns: tuple[
        Literal["from_user_id"],
        Literal["to_user_id"],
        Literal["status"],
        Literal["created_at"],
    ] = ("from_user_id", "to_user_id", "status", "created_at")
    user_to_user_scope_unique: Literal[True] = True
    current_runtime_storage: Literal["process registry; no migration executed"] = (
        "process registry; no migration executed"
    )
    migration_executed: Literal[False] = False


class MessagingPermissionIntegrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c19f_c19a_c19c_c19d_c19e_integration_v1"] = (
        "c19f_c19a_c19c_c19d_c19e_integration_v1"
    )
    c19a_identity_source: Literal["contact_identities"] = "contact_identities"
    c19c_message_schema_source: Literal["MessageSendRequest and content_type"] = (
        "MessageSendRequest and content_type"
    )
    c19d_conversation_source: Literal["conversation_service"] = (
        "conversation_service"
    )
    c19e_cross_org_gate_source: Literal["can_communicate"] = "can_communicate"
    c18g_data_isolation_source: Literal["org data isolation remains separate"] = (
        "org data isolation remains separate"
    )
    modifies_c19a_to_c19e: Literal[False] = False
    modifies_c18g: Literal[False] = False


class MessagingPermissionSecurityBoundary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    boundary_id: Literal["c19f_security_boundary_v1"] = (
        "c19f_security_boundary_v1"
    )
    permission_is_not_org_access: Literal[True] = True
    permission_is_not_data_isolation: Literal[True] = True
    c18g_still_applies: Literal[True] = True
    all_permissions_user_to_user_scoped: Literal[True] = True
    no_friend_requirement_bypass: Literal[True] = True
    sender_must_match_authenticated_actor: Literal[True] = True
    cross_org_must_pass_c19e: Literal[True] = True
    rejected_relationship_blocks_chat: Literal[True] = True
    group_chat_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False
    media_transport_implemented: Literal[False] = False


class MessagingPermissionCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19F"] = "C19F"
    component: Literal["Messaging Permission Control"] = (
        "Messaging Permission Control"
    )
    completion_status: Literal["complete"] = "complete"
    messaging_permission_schema_defined: Literal[True] = True
    friend_system_model_defined: Literal[True] = True
    permission_evaluation_function_defined: Literal[True] = True
    feature_unlocking_rules_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    c19a_integrated: Literal[True] = True
    c19c_integrated: Literal[True] = True
    c19d_integrated: Literal[True] = True
    c19e_integrated: Literal[True] = True
    security_boundaries_defined: Literal[True] = True
    ui_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False
    group_chat_implemented: Literal[False] = False
    voice_video_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


def build_messaging_permission(
    *,
    user_id: str | int,
    target_user_id: str | int,
    friend_status: FriendStatus | FriendRequestStatus | str,
    can_chat: bool = True,
) -> MessagingPermission:
    status = _friend_status(friend_status)
    effective_can_chat = can_chat and status != FriendStatus.REJECTED
    return MessagingPermission(
        user_id=str(user_id),
        target_user_id=str(target_user_id),
        can_chat=effective_can_chat,
        friend_status=status,
        unlocked_features=list(
            unlocked_features_for_status(status, can_chat=effective_can_chat)
        ),
    )


def evaluate_messaging_permission(
    *,
    sender_user_id: str | int,
    receiver_user_id: str | int,
    content_type: MessagingFeature | str,
    same_org: bool,
    friend_status: FriendStatus | FriendRequestStatus | str,
    c19e_decision: CrossOrgDecision | None = None,
) -> MessagingPermissionDecision:
    sender = _normalize_user_id(sender_user_id, field_name="sender_user_id")
    receiver = _normalize_user_id(receiver_user_id, field_name="receiver_user_id")
    feature = _content_type(content_type)
    status = _friend_status(friend_status)
    c19e_gate_checked = c19e_decision is not None

    def decision(
        *,
        allowed: bool,
        denial_code: str | None,
        reason: str,
        can_chat: bool = True,
    ) -> MessagingPermissionDecision:
        permission = build_messaging_permission(
            user_id=sender,
            target_user_id=receiver,
            friend_status=status,
            can_chat=can_chat,
        )
        return MessagingPermissionDecision(
            sender_user_id=sender,
            receiver_user_id=receiver,
            content_type=feature,
            permission=permission,
            same_org=same_org,
            allowed=allowed,
            denied=not allowed,
            denial_code=denial_code,
            reason=reason,
            c19e_gate_checked=c19e_gate_checked,
            c19e_decision=c19e_decision,
        )

    if sender == receiver:
        return decision(
            allowed=False,
            denial_code="c19f_self_message_denied",
            reason="Messaging permission requires distinct users.",
            can_chat=False,
        )

    if not same_org and (c19e_decision is None or c19e_decision.denied):
        return decision(
            allowed=False,
            denial_code="c19f_c19e_gate_denied",
            reason="Cross-org messages must pass the C19E communication gate.",
            can_chat=False,
        )

    if status == FriendStatus.REJECTED:
        return decision(
            allowed=False,
            denial_code="c19f_friend_rejected",
            reason="Rejected friend relationship blocks messaging.",
            can_chat=False,
        )

    if feature in ADVANCED_MESSAGING_FEATURES and status != FriendStatus.ACCEPTED:
        return decision(
            allowed=False,
            denial_code="c19f_friend_required",
            reason="Image, file, voice, and video require accepted friend status.",
        )

    return decision(
        allowed=True,
        denial_code=None,
        reason="Messaging permission allows this content type.",
    )


MESSAGING_PERMISSION_SQL_SCHEMA = """
CREATE TABLE messaging_permissions (
    user_id TEXT NOT NULL,
    target_user_id TEXT NOT NULL,
    can_chat BOOLEAN NOT NULL,
    friend_status TEXT CHECK (
        friend_status IN ('none', 'pending', 'accepted', 'rejected')
    ) NOT NULL,
    unlocked_features TEXT NOT NULL,
    PRIMARY KEY (user_id, target_user_id)
);

CREATE TABLE friend_requests (
    from_user_id TEXT NOT NULL,
    to_user_id TEXT NOT NULL,
    status TEXT CHECK (status IN ('pending', 'accepted', 'rejected')) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (from_user_id, to_user_id)
);
""".strip()


MESSAGING_PERMISSION_DATA_FLOW_DIAGRAM = """
POST /messages/permission/check or /messages/send
  -> authenticated internal user
  -> sender_user_id must match authenticated actor
  -> C19A identity and active C18C membership are verified through C19E/C19D
  -> same-org internal users default to can_chat=True with text + emoji only
  -> cross-org users must pass C19E before C19F evaluates friend status
  -> friend_status accepted unlocks image + file + voice + video
  -> friend_status pending or none keeps text + emoji only
  -> friend_status rejected blocks communication
  -> C19C still owns the message schema; C19F only authorizes content capability
  -> C19D still owns direct conversation binding
  -> C18G data isolation remains separate from messaging permission
""".strip()


def get_messaging_feature_unlocking_rules() -> MessagingFeatureUnlockingRules:
    return MessagingFeatureUnlockingRules()


def get_messaging_permission_api_design() -> MessagingPermissionApiDesign:
    return MessagingPermissionApiDesign()


def get_messaging_permission_database_schema() -> MessagingPermissionDatabaseSchema:
    return MessagingPermissionDatabaseSchema()


def get_messaging_permission_integration_model() -> (
    MessagingPermissionIntegrationModel
):
    return MessagingPermissionIntegrationModel()


def get_messaging_permission_security_boundary() -> (
    MessagingPermissionSecurityBoundary
):
    return MessagingPermissionSecurityBoundary()


def get_messaging_permission_completion_status() -> (
    MessagingPermissionCompletionStatus
):
    return MessagingPermissionCompletionStatus()
