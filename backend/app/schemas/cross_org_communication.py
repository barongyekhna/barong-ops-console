from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .message import MessageContentType, MessageStatus
from .permission import PermissionDecision


CROSS_ORG_COMMUNICATION_MODULE_ID = "C19E"
CROSS_ORG_COMMUNICATION_PERMISSION_ACTION = "read"


class CrossOrgPolicyMode(StrEnum):
    OPEN = "open"
    RESTRICTED = "restricted"
    CLOSED = "closed"


class CrossOrgPolicyRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allow_cross_org_chat: bool = True
    require_permission: bool = True
    require_mutual_approval: bool = False


class CrossOrgPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: CrossOrgPolicyMode = CrossOrgPolicyMode.OPEN
    rules: CrossOrgPolicyRules = Field(default_factory=CrossOrgPolicyRules)


class CrossOrgCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_user_id: str = Field(min_length=1, max_length=255)
    receiver_user_id: str = Field(min_length=1, max_length=255)

    @field_validator("sender_user_id", "receiver_user_id")
    @classmethod
    def normalize_user_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("user_id must not be empty.")
        return normalized

    @model_validator(mode="after")
    def validate_distinct_users(self) -> "CrossOrgCheckRequest":
        if self.sender_user_id == self.receiver_user_id:
            raise ValueError("sender_user_id and receiver_user_id must be distinct.")
        return self


class CrossOrgParticipantIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)
    org_id: str = Field(min_length=1, max_length=40)
    c19a_identity_verified: Literal[True] = True
    c18c_active_membership_verified: Literal[True] = True


class CrossOrgDataIsolationScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sender_org_id: str | None = Field(default=None, max_length=40)
    receiver_org_id: str | None = Field(default=None, max_length=40)
    c18g_data_isolation_required: Literal[True] = True
    sender_data_scope: Literal["sender_org_id"] = "sender_org_id"
    receiver_data_scope: Literal["receiver_org_id"] = "receiver_org_id"
    cross_org_data_access_allowed: Literal[False] = False
    message_flow_records_sender_org_id: Literal[True] = True
    message_flow_records_receiver_org_id: Literal[True] = True


class CrossOrgDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19E"] = "C19E"
    sender_user_id: str = Field(min_length=1, max_length=255)
    receiver_user_id: str = Field(min_length=1, max_length=255)
    sender: CrossOrgParticipantIdentity | None = None
    receiver: CrossOrgParticipantIdentity | None = None
    cross_org: bool
    allowed: bool
    denied: bool
    denial_code: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=500)
    policy: CrossOrgPolicy = Field(default_factory=CrossOrgPolicy)
    c18f_permission_checked: bool
    c18f_permission_decision: PermissionDecision | None = None
    c18g_scope: CrossOrgDataIsolationScope = Field(
        default_factory=CrossOrgDataIsolationScope
    )
    c19a_identity_checked: bool
    c18c_membership_checked: bool
    c17_trace_logged: Literal[True] = True
    c17_trace_id: str = Field(min_length=1, max_length=180)
    default_global_im_boundary: bool = True
    global_im_module_id: Literal["C19E"] = CROSS_ORG_COMMUNICATION_MODULE_ID
    global_im_permission_action: Literal["read"] = (
        CROSS_ORG_COMMUNICATION_PERMISSION_ACTION
    )

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "CrossOrgDecision":
        if self.allowed == self.denied:
            raise ValueError("CrossOrgDecision allowed/denied mismatch.")
        if self.allowed and self.denial_code is not None:
            raise ValueError("Allowed decisions must not include denial_code.")
        if self.denied and self.denial_code is None:
            raise ValueError("Denied decisions must include denial_code.")
        if self.allowed and self.cross_org and not self.c18f_permission_checked:
            raise ValueError("Allowed cross-org decisions must check C18F.")
        if self.allowed and self.cross_org and self.c18f_permission_decision is None:
            raise ValueError("Allowed cross-org decisions must include C18F decision.")
        return self


class CrossOrgConversationRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: str = Field(min_length=1, max_length=64)
    participants: tuple[str, str]
    sender_org_id: str = Field(min_length=1, max_length=40)
    receiver_org_id: str = Field(min_length=1, max_length=40)
    cross_org: bool
    conversation_cross_org_field: Literal["conversation.cross_org"] = (
        "conversation.cross_org"
    )
    conversation_cross_org_value: bool
    c19d_conversation_can_cross_org: Literal[True] = True
    c19d_schema_modified: Literal[False] = False

    @model_validator(mode="after")
    def validate_cross_org_marker(self) -> "CrossOrgConversationRule":
        if self.cross_org != self.conversation_cross_org_value:
            raise ValueError("conversation.cross_org marker must match cross_org.")
        return self


class CrossOrgMessageOrgEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str = Field(min_length=1, max_length=64)
    conversation_id: str = Field(min_length=1, max_length=64)
    from_user_id: str = Field(min_length=1, max_length=255)
    to_user_id: str = Field(min_length=1, max_length=255)
    sender_org_id: str = Field(min_length=1, max_length=40)
    receiver_org_id: str = Field(min_length=1, max_length=40)
    content_type: MessageContentType
    status: MessageStatus = MessageStatus.SENT
    cross_org: bool
    c18g_scoped: Literal[True] = True
    c17_trace_logged: Literal[True] = True
    persistence_implemented: Literal[False] = False


class CrossOrgMessageSendDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19E"] = "C19E"
    allowed: bool
    denied: bool
    denial_code: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=500)
    communication_decision: CrossOrgDecision
    conversation: CrossOrgConversationRule | None = None
    message: CrossOrgMessageOrgEnvelope | None = None
    persistence_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False
    group_chat_implemented: Literal[False] = False

    @model_validator(mode="after")
    def validate_send_decision(self) -> "CrossOrgMessageSendDecision":
        if self.allowed == self.denied:
            raise ValueError("Message send decision allowed/denied mismatch.")
        if self.allowed and self.denial_code is not None:
            raise ValueError("Allowed send decisions must not include denial_code.")
        if self.denied and self.denial_code is None:
            raise ValueError("Denied send decisions must include denial_code.")
        if self.allowed and (self.conversation is None or self.message is None):
            raise ValueError("Allowed send decisions must include envelope metadata.")
        return self


class CrossOrgCommunicationLogic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    logic_id: Literal["c19e_can_communicate_v1"] = "c19e_can_communicate_v1"
    same_org_rule: Literal["sender.org_id == receiver.org_id -> ALLOW"] = (
        "sender.org_id == receiver.org_id -> ALLOW"
    )
    cross_org_rule: Literal[
        "sender.org_id != receiver.org_id -> C18F permission + C19E policy"
    ] = "sender.org_id != receiver.org_id -> C18F permission + C19E policy"
    c18f_module_id: Literal["C19E"] = CROSS_ORG_COMMUNICATION_MODULE_ID
    c18f_action: Literal["read"] = CROSS_ORG_COMMUNICATION_PERMISSION_ACTION
    identity_source: Literal["C19A contact identity"] = "C19A contact identity"
    membership_source: Literal["C18C org membership"] = "C18C org membership"
    data_scope_source: Literal["C18G org data isolation"] = (
        "C18G org data isolation"
    )


class CrossOrgConversationRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c19e_cross_org_conversation_rules_v1"] = (
        "c19e_cross_org_conversation_rules_v1"
    )
    c19d_direct_conversation_can_cross_org: Literal[True] = True
    required_marker: Literal["conversation.cross_org = True when orgs differ"] = (
        "conversation.cross_org = True when orgs differ"
    )
    group_chat_logic_implemented: Literal[False] = False
    modifies_c19d_schema: Literal[False] = False


class CrossOrgMessageFlowRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c19e_message_flow_rules_v1"] = (
        "c19e_message_flow_rules_v1"
    )
    sender_org_id_recorded: Literal[True] = True
    receiver_org_id_recorded: Literal[True] = True
    c18g_data_isolation_enforced: Literal[True] = True
    c17_trace_records_cross_org_behavior: Literal[True] = True
    no_websocket: Literal[True] = True
    no_group_chat_logic: Literal[True] = True
    persistence_migration_executed: Literal[False] = False


class CrossOrgApiEndpointDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["POST"]
    path: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=500)
    authenticated_internal_user_required: Literal[True] = True
    c19e_policy_enforced: Literal[True] = True
    c17_trace_required: Literal[True] = True


class CrossOrgApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c19e_cross_org_api_design_v1"] = (
        "c19e_cross_org_api_design_v1"
    )
    endpoints: tuple[CrossOrgApiEndpointDesign, CrossOrgApiEndpointDesign] = (
        CrossOrgApiEndpointDesign(
            method="POST",
            path="/comm/cross-org/check",
            purpose="Return the C19E communication permission decision.",
        ),
        CrossOrgApiEndpointDesign(
            method="POST",
            path="/messages/send",
            purpose="Run C19E before accepting a message into the send boundary.",
        ),
    )
    mounted_under_application_api_prefix: Literal[True] = True
    public_api_exposure_allowed: Literal[False] = False
    websocket_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


class CrossOrgSecurityBoundary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    boundary_id: Literal["c19e_security_boundary_v1"] = (
        "c19e_security_boundary_v1"
    )
    no_org_bypass: Literal[True] = True
    cross_org_requires_c18f: Literal[True] = True
    data_scoped_by_c18g: Literal[True] = True
    identity_verified_by_c19a: Literal[True] = True
    cross_org_actions_logged_by_c17: Literal[True] = True
    sender_must_match_authenticated_actor: Literal[True] = True
    cross_org_data_access_allowed: Literal[False] = False
    modifies_c18_system: Literal[False] = False
    modifies_c19a_to_c19d: Literal[False] = False


class CrossOrgIntegrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c19e_c18_c19d_integration_v1"] = (
        "c19e_c18_c19d_integration_v1"
    )
    c18c_org_membership_source: Literal["org_memberships"] = "org_memberships"
    c18f_permission_source: Literal["permission_isolation.check_permission"] = (
        "permission_isolation.check_permission"
    )
    c18g_data_isolation_source: Literal["OrgDataIsolation middleware/session hooks"] = (
        "OrgDataIsolation middleware/session hooks"
    )
    c19a_identity_source: Literal["contact_identities"] = "contact_identities"
    c19d_conversation_source: Literal["conversation_service"] = (
        "conversation_service"
    )
    c17_trace_source: Literal["event_collector"] = "event_collector"
    modifies_c18_system: Literal[False] = False
    modifies_c19a_to_c19d: Literal[False] = False


class CrossOrgCommunicationCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19E"] = "C19E"
    component: Literal["Cross-Org Communication Layer"] = (
        "Cross-Org Communication Layer"
    )
    completion_status: Literal["complete"] = "complete"
    cross_org_policy_model_defined: Literal[True] = True
    communication_permission_logic_defined: Literal[True] = True
    cross_org_conversation_rules_defined: Literal[True] = True
    message_flow_rules_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    security_boundaries_defined: Literal[True] = True
    c18_c19d_integration_defined: Literal[True] = True
    ui_implemented: Literal[False] = False
    websocket_implemented: Literal[False] = False
    group_chat_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


CROSS_ORG_SYSTEM_BEHAVIOR_DIAGRAM = """
POST /messages/send or /comm/cross-org/check
  -> authenticated internal user
  -> sender_user_id must match authenticated actor
  -> C19A resolves sender and receiver contact identities
  -> C18C verifies both users have active org memberships
  -> if sender.org_id == receiver.org_id: allow same-org communication
  -> if orgs differ:
       -> apply CrossOrgPolicy(mode=open by default)
       -> require C18F check on module C19E/action read in sender org
       -> deny when C18F, policy, or identity checks fail
  -> C19D conversation remains direct and is marked conversation.cross_org=True
     in the C19E envelope when participant orgs differ
  -> message envelope records sender_org_id and receiver_org_id
  -> C18G keeps data scoped by org ids; cross-org data access is never granted
  -> C17 event trace records allow/deny and cross_org behavior
""".strip()


def get_default_cross_org_policy() -> CrossOrgPolicy:
    return CrossOrgPolicy()


def get_cross_org_communication_logic() -> CrossOrgCommunicationLogic:
    return CrossOrgCommunicationLogic()


def get_cross_org_conversation_rules() -> CrossOrgConversationRules:
    return CrossOrgConversationRules()


def get_cross_org_message_flow_rules() -> CrossOrgMessageFlowRules:
    return CrossOrgMessageFlowRules()


def get_cross_org_api_design() -> CrossOrgApiDesign:
    return CrossOrgApiDesign()


def get_cross_org_security_boundary() -> CrossOrgSecurityBoundary:
    return CrossOrgSecurityBoundary()


def get_cross_org_integration_model() -> CrossOrgIntegrationModel:
    return CrossOrgIntegrationModel()


def get_cross_org_communication_completion_status() -> (
    CrossOrgCommunicationCompletionStatus
):
    return CrossOrgCommunicationCompletionStatus()
