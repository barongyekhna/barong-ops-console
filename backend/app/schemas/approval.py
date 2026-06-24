from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from .live_gate import ApprovalUnlockDecision


ApprovalRiskLevel = Literal["low", "medium", "high"]
ApprovalExecutionType = Literal["mock", "no_op", "async", "real"]
ApprovalRequestStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "auto_approved",
]
ApprovalDecisionStatus = Literal[
    "approved",
    "rejected",
    "auto_approved",
    "pending",
]
ApprovalDecisionSource = Literal[
    "risk",
    "execution",
    "module",
    "user",
    "global",
]
ApprovalCategory = Literal["control_plane", "feature"]
ApprovalActorRole = Literal["owner", "admin", "user", "system"]
ApprovalActorType = Literal["user", "system"]
ApprovalContextSource = Literal[
    "c09_execution_request",
    "c10_sandbox_contract",
    "c11_execution_type",
    "c11b_risk_policy",
    "c11d_risk_policy",
    "c12_approval_request",
]
ApprovalStatusTransitionEvent = Literal[
    "request_created",
    "manual_approved",
    "manual_rejected",
    "auto_approved",
]
ApprovalWorkflowState = ApprovalRequestStatus
ApprovalWorkflowEvent = Literal[
    "execution_request_triggered",
    "c12b_decision_recorded",
    "workflow_state_updated",
]

APPROVAL_REQUEST_SCHEMA_VERSION = "c12.approval_request.v1"
APPROVAL_CONTEXT_SNAPSHOT_SCHEMA_VERSION = (
    "c12.approval_context_snapshot.v1"
)
APPROVAL_WORKFLOW_SCHEMA_VERSION = "c12.approval_workflow.v1"
APPROVAL_REQUEST_INITIAL_STATUS: ApprovalRequestStatus = "pending"
APPROVAL_REQUEST_TERMINAL_STATUSES: tuple[ApprovalRequestStatus, ...] = (
    "approved",
    "rejected",
    "auto_approved",
)
APPROVAL_REQUEST_ALLOWED_TRANSITIONS: tuple[
    tuple[ApprovalRequestStatus, ApprovalRequestStatus],
    ...,
] = (
    ("pending", "approved"),
    ("pending", "rejected"),
    ("pending", "auto_approved"),
)
APPROVAL_WORKFLOW_INITIAL_STATE: ApprovalWorkflowState = (
    APPROVAL_REQUEST_INITIAL_STATUS
)
APPROVAL_WORKFLOW_TERMINAL_STATES: tuple[ApprovalWorkflowState, ...] = (
    APPROVAL_REQUEST_TERMINAL_STATUSES
)
APPROVAL_WORKFLOW_ALLOWED_TRANSITIONS: tuple[
    tuple[ApprovalWorkflowState, ApprovalWorkflowState],
    ...,
] = APPROVAL_REQUEST_ALLOWED_TRANSITIONS
C12D_APPROVAL_SAFETY_GUARANTEES = (
    "C12D persists approval records and decisions only.",
    "C12D does not call C09 execution provider APIs.",
    "C12D does not call C10 sandbox runtime or bridge.",
    "C12D does not call external providers or provider endpoints.",
    "C12D does not execute approved actions.",
)


class ApprovalContextFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=1000)
    source: ApprovalContextSource
    redacted: bool = True


class ApprovalContextSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["c12.approval_context_snapshot.v1"] = (
        APPROVAL_CONTEXT_SNAPSHOT_SCHEMA_VERSION
    )
    snapshot_id: str = Field(min_length=1, max_length=180)
    captured_at: datetime
    execution_id: str = Field(min_length=1, max_length=128)
    organization_id: str | None = Field(default=None, max_length=40)
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    action_key: str = Field(min_length=1, max_length=180)
    requester_id: int = Field(gt=0)
    risk_level: ApprovalRiskLevel
    execution_type: ApprovalExecutionType
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    facts: tuple[ApprovalContextFact, ...] = Field(default_factory=tuple)
    audit_purpose: Literal["c12_approval_audit"] = "c12_approval_audit"
    immutable: Literal[True] = True

    @model_validator(mode="after")
    def enforce_module_switch(self) -> "ApprovalContextSnapshot":
        _enforce_module_switch_before_c12(self.module_key)
        return self


class ApprovalStatusTraceEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event: ApprovalStatusTransitionEvent
    from_status: ApprovalRequestStatus | None = None
    to_status: ApprovalRequestStatus
    actor_id: int | None = Field(default=None, gt=0)
    transition_time: datetime
    reason: str = Field(min_length=1, max_length=1000)
    decision_source: ApprovalDecisionSource | None = None


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["c12.approval_request.v1"] = (
        APPROVAL_REQUEST_SCHEMA_VERSION
    )
    approval_id: str = Field(min_length=1, max_length=128)
    execution_id: str = Field(min_length=1, max_length=128)
    organization_id: str | None = Field(default=None, max_length=40)
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    action_key: str = Field(min_length=1, max_length=180)
    requester_id: int = Field(gt=0)
    request_time: datetime
    risk_level: ApprovalRiskLevel
    execution_type: ApprovalExecutionType
    category: ApprovalCategory = "feature"
    status: ApprovalRequestStatus = APPROVAL_REQUEST_INITIAL_STATUS
    reason: str = Field(min_length=1, max_length=1000)
    reviewer_id: int | None = Field(default=None, gt=0)
    context_snapshot: ApprovalContextSnapshot
    status_trace: tuple[ApprovalStatusTraceEntry, ...] = Field(
        default_factory=tuple
    )

    @computed_field
    @property
    def timestamp(self) -> datetime:
        return self.request_time

    @model_validator(mode="after")
    def enforce_module_switch(self) -> "ApprovalRequest":
        _enforce_module_switch_before_c12(self.module_key)
        return self


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ApprovalDecisionStatus
    reason: str = Field(min_length=1, max_length=1000)
    decision_source: ApprovalDecisionSource


class ApprovalWorkflowHistoryEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event: ApprovalWorkflowEvent
    from_state: ApprovalWorkflowState | None = None
    to_state: ApprovalWorkflowState
    state_changed: bool = True
    event_time: datetime
    decision_status: ApprovalDecisionStatus | None = None
    decision_source: ApprovalDecisionSource | None = None
    actor_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=1000)


class ApprovalWorkflow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["c12.approval_workflow.v1"] = (
        APPROVAL_WORKFLOW_SCHEMA_VERSION
    )
    workflow_id: str = Field(min_length=1, max_length=180)
    approval_id: str = Field(min_length=1, max_length=128)
    execution_id: str = Field(min_length=1, max_length=128)
    state: ApprovalWorkflowState = APPROVAL_WORKFLOW_INITIAL_STATE
    approval_request: ApprovalRequest
    created_at: datetime
    updated_at: datetime
    history: tuple[ApprovalWorkflowHistoryEntry, ...] = Field(
        default_factory=tuple
    )


class ApprovalRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    execution_id: str = Field(
        default_factory=lambda: f"execution-{uuid4()}",
        min_length=1,
        max_length=128,
    )
    category: ApprovalCategory | None = None
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str | None = Field(default=None, min_length=1, max_length=180)
    action_key: str | None = Field(default=None, min_length=1, max_length=180)
    risk_level: ApprovalRiskLevel = "medium"
    execution_type: ApprovalExecutionType = "no_op"
    reason: str = Field(
        default="Approval requested.",
        min_length=1,
        max_length=1000,
    )
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    context_facts: tuple[ApprovalContextFact, ...] = Field(
        default_factory=tuple
    )

    @model_validator(mode="after")
    def enforce_module_switch(self) -> "ApprovalRequestCreate":
        if self.adapter_key is None:
            self.adapter_key = f"{self.module_key}.adapter"[:180]
        if self.action_key is None:
            self.action_key = f"{self.module_key}.request"[:180]
        _enforce_module_switch_before_c12(self.module_key)
        return self


class ApprovalDecisionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=1000)


class ApprovalDecisionRecordResponse(BaseModel):
    decision_id: str
    approval_id: str
    workflow_id: str
    status: ApprovalDecisionStatus
    reason: str
    decision_source: ApprovalDecisionSource
    actor_type: ApprovalActorType
    actor_role: ApprovalActorRole
    actor_id: int | None
    decision_time: datetime


class ApprovalPermissionBoundaryResponse(BaseModel):
    actor_role: ApprovalActorRole
    allowed_actions: tuple[str, ...]
    full_access: bool = False


class ApprovalSafetyBoundaryResponse(BaseModel):
    stage: Literal["c12d_approval_persistence_api"] = (
        "c12d_approval_persistence_api"
    )
    no_execution: Literal[True] = True
    no_sandbox_call: Literal[True] = True
    no_external_provider: Literal[True] = True
    no_permission_bypass: Literal[True] = True


class ApprovalDisplayInfo(BaseModel):
    title: str
    category_label: str
    module_label: str
    action_label: str
    status_label: str
    risk_label: str
    summary: str


class ApprovalDetailResponse(BaseModel):
    approval: ApprovalRequest
    workflow: ApprovalWorkflow
    decisions: list[ApprovalDecisionRecordResponse]
    display: ApprovalDisplayInfo
    permission_boundary: ApprovalPermissionBoundaryResponse
    execution_unlock: ApprovalUnlockDecision | None = None
    safety: ApprovalSafetyBoundaryResponse = Field(
        default_factory=ApprovalSafetyBoundaryResponse
    )


class ApprovalListItem(BaseModel):
    approval_id: str
    execution_id: str
    organization_id: str | None = None
    module_key: str
    adapter_key: str
    action_key: str
    requester_id: int
    request_time: datetime
    timestamp: datetime
    risk_level: ApprovalRiskLevel
    execution_type: ApprovalExecutionType
    category: ApprovalCategory = "feature"
    status: ApprovalRequestStatus
    reason: str
    reviewer_id: int | None
    workflow_id: str | None = None
    workflow_state: ApprovalWorkflowState | None = None
    display: ApprovalDisplayInfo


def _enforce_module_switch_before_c12(module_key: str) -> None:
    from ..services.module_switch_runtime_gate import (
        ModuleSwitchRuntimeBlockedError,
        enforce_module_switch_before_c12_approval_request,
    )

    try:
        enforce_module_switch_before_c12_approval_request(module_key)
    except ModuleSwitchRuntimeBlockedError as exc:
        raise ValueError(str(exc)) from None
