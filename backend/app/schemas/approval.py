from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    action_key: str = Field(min_length=1, max_length=180)
    requester_id: int = Field(gt=0)
    request_time: datetime
    risk_level: ApprovalRiskLevel
    execution_type: ApprovalExecutionType
    status: ApprovalRequestStatus = APPROVAL_REQUEST_INITIAL_STATUS
    reason: str = Field(min_length=1, max_length=1000)
    reviewer_id: int | None = Field(default=None, gt=0)
    context_snapshot: ApprovalContextSnapshot
    status_trace: tuple[ApprovalStatusTraceEntry, ...] = Field(
        default_factory=tuple
    )


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
