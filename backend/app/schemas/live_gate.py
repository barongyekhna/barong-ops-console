from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


LiveExecutionMode = Literal["mock", "staging", "live"]
LiveGateDecisionState = Literal["ALLOW", "DENY", "STAGING_ONLY"]
LivePolicyScope = Literal["global", "org", "module"]
LivePolicyStatus = Literal["active", "disabled"]
UnlockDecisionState = Literal[
    "not_required",
    "unlocked",
    "denied",
    "blocked",
    "missing",
    "invalid",
]
CanaryStage = Literal["mock", "staging", "live"]
ReadinessCheckStatus = Literal["pass", "fail", "warn"]
RollbackGuardAction = Literal["none", "watch", "trigger_rollback", "restore_previous"]


class LiveGatePolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_scope: LivePolicyScope
    scope_key: str = Field(min_length=1, max_length=180)
    enabled: bool = False
    staging_only: bool = True
    rollout_percentage: int = Field(default=0, ge=0, le=100)
    allowed_orgs: tuple[str, ...] = Field(default_factory=tuple)
    allowed_modules: tuple[str, ...] = Field(default_factory=tuple)
    status: LivePolicyStatus = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class LiveGatePolicyRead(LiveGatePolicyInput):
    policy_id: str = Field(min_length=1, max_length=128)
    org_id: str = Field(min_length=1, max_length=40)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LiveGateDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate: Literal["LiveGatingController"] = "LiveGatingController"
    decision: LiveGateDecisionState
    reason: str = Field(min_length=1, max_length=700)
    execution_mode_requested: LiveExecutionMode
    execution_mode_effective: LiveExecutionMode
    execution_mode_valid: bool
    global_live_switch: bool
    org_policy_checked: bool
    org_policy: str = Field(min_length=1, max_length=180)
    module_policy_checked: bool
    module_policy: str = Field(min_length=1, max_length=180)
    c12_unlock_required: bool
    c12_unlocked: bool
    pre_live_validation_passed: bool
    canary_stage: CanaryStage
    evaluated_at: datetime

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"


class ApprovalUnlockDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    controller: Literal["C12ApprovalUnlockTokenController"] = (
        "C12ApprovalUnlockTokenController"
    )
    decision: UnlockDecisionState
    approval_id: str | None = Field(default=None, max_length=128)
    execution_id: str | None = Field(default=None, max_length=128)
    unlock_id: str | None = Field(default=None, max_length=128)
    unlock_token: str | None = Field(default=None, max_length=255)
    status: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=700)
    issued_at: datetime | None = None
    expires_at: datetime | None = None

    @property
    def unlocked(self) -> bool:
        return self.decision == "unlocked"


class CanaryRouteDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    router: Literal["CanaryRolloutSystem"] = "CanaryRolloutSystem"
    requested_mode: LiveExecutionMode
    routed_mode: LiveExecutionMode
    stage: CanaryStage
    percentage_rollout: int = Field(ge=0, le=100)
    org_allowed: bool
    module_allowed: bool
    org_rule_matched: bool = False
    module_rule_matched: bool = False
    deterministic_bucket: int = Field(ge=0, le=99)
    reason: str = Field(min_length=1, max_length=700)

    @property
    def staging_only(self) -> bool:
        return self.requested_mode == "live" and self.routed_mode != "live"


class LiveAuditEnforcementResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enforced: bool
    trace_id: str | None = Field(default=None, max_length=180)
    execution_id: str | None = Field(default=None, max_length=128)
    event_stream_record_id: str | None = Field(default=None, max_length=128)
    audit_id: str | None = Field(default=None, max_length=128)
    status: Literal["emitted", "skipped", "failed"]
    reason: str = Field(min_length=1, max_length=700)


class ExecutionUnlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=180)
    payload: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = Field(default=None, max_length=128)
    unlock_token: str | None = Field(default=None, max_length=255)
    execution_id: str | None = Field(default=None, max_length=128)
    trace_id: str | None = Field(default=None, max_length=180)


class ExecutionUnlockResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    flow: tuple[str, ...] = (
        "request",
        "policy check",
        "approval check",
        "live gate check",
        "provider router",
    )
    status: Literal["accepted", "denied", "staging_only"]
    reason: str = Field(min_length=1, max_length=700)
    policy_allowed: bool
    approval: ApprovalUnlockDecision
    canary: CanaryRouteDecision
    live_gate: LiveGateDecision
    audit: LiveAuditEnforcementResult
    router_response: Any | None = None
    direct_execution_allowed: Literal[False] = False
    provider_router_called: bool = False
    live_provider_dispatched: Literal[False] = False


class ReadinessCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    check: str = Field(min_length=1, max_length=160)
    status: ReadinessCheckStatus
    reason: str = Field(min_length=1, max_length=700)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PreLiveValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: Literal["PreLiveValidationEngine"] = "PreLiveValidationEngine"
    passed: bool
    generated_at: datetime
    checks: tuple[ReadinessCheckResult, ...]


class ProductionReadinessReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: Literal["ProductionReadinessEngine"] = "ProductionReadinessEngine"
    ready: bool
    generated_at: datetime
    checks: tuple[ReadinessCheckResult, ...]


class RollbackGuardDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    guard: Literal["LiveRollbackGuard"] = "LiveRollbackGuard"
    action: RollbackGuardAction
    reason: str = Field(min_length=1, max_length=700)
    failure_count: int = Field(ge=0)
    previous_version: str | None = Field(default=None, max_length=180)
    restored_version: str | None = Field(default=None, max_length=180)
    db_consistent: bool
    image_consistent: bool
    rollback_triggered: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
