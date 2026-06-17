from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .execution_provider import (
    ExecutionProviderType,
    ExecutionRiskLevel,
    ProviderRuntimeReadiness,
)


ExecutionRuntimeMode = Literal["mock", "staging", "live"]
ExecutionGateDecisionState = Literal["allow", "deny", "partial"]
ExecutionRouterValidationStatus = Literal["valid", "invalid"]


class ExecutionPermissionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1, max_length=120)
    decision: Literal["allow", "deny", "partial"]
    reason: str = Field(min_length=1, max_length=500)
    denial_code: str | None = Field(default=None, max_length=180)
    permission_key: str | None = Field(default=None, max_length=255)


class ExecutionOrgContextSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org_id: str = Field(min_length=1, max_length=68)
    user_id: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, max_length=40)
    request_id: str | None = Field(default=None, max_length=128)
    c18h_context_applied: bool = True


class ExecutionProviderSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_key: str = Field(min_length=1, max_length=180)
    provider_type: ExecutionProviderType
    provider_readiness: ProviderRuntimeReadiness
    selected_mode: ExecutionRuntimeMode
    selection_reason: str = Field(min_length=1, max_length=500)
    registry_metadata_only: Literal[True] = True
    resolver_selected: Literal[True] = True
    live_provider_connected: Literal[False] = False
    production_external_call_allowed: Literal[False] = False


class ExecutionModeAwareGateDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate: Literal["ExecutionModeAwareGate"] = "ExecutionModeAwareGate"
    decision: ExecutionGateDecisionState
    reason: str = Field(min_length=1, max_length=500)
    execution_mode_requested: ExecutionRuntimeMode
    execution_mode_allowed: bool
    execution_mode_selected: ExecutionRuntimeMode | None = None
    c18f_decision: Literal["allow", "deny", "partial"]
    c05_decision: Literal["allow", "deny", "partial"]
    c18_org_context_checked: Literal[True] = True
    provider_readiness: ProviderRuntimeReadiness
    module_policy: str = Field(min_length=1, max_length=180)
    production_external_call_allowed: Literal[False] = False
    live_execution_allowed: Literal[False] = False


class ExecutionRouterValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ExecutionRouterValidationStatus
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    c08_adapter_validated: bool = False
    c18_tenant_isolation_preserved: bool = True
    c05_permission_engine_checked: bool = False
    c18f_permission_isolation_checked: bool = False
    no_production_external_call: Literal[True] = True


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str = Field(min_length=1, max_length=180)
    org_id: str = Field(min_length=1, max_length=68)
    module_id: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    action: str = Field(min_length=1, max_length=180)
    execution_mode: ExecutionRuntimeMode
    risk_level: ExecutionRiskLevel
    required_permission: str = Field(min_length=1, max_length=255)
    pipeline: tuple[str, ...] = (
        "C08 Adapter Action",
        "ExecutionRouter.receive_request",
        "ProviderResolver.select_provider",
        "ExecutionModeAwareGate",
        "MockSandbox/StagingSandbox",
        "C17 audit event ready",
    )
    provider_execution_deferred: Literal[True] = True
    adapter_executes_logic: Literal[False] = False
    webhook_triggers_execution: Literal[False] = False
    production_external_call_allowed: Literal[False] = False
    created_at: datetime


class ExecutionRouterRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org_id: str = Field(min_length=1, max_length=68)
    module_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=180)
    payload: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class ExecutionRouterResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    router: Literal["ExecutionRouter"] = "ExecutionRouter"
    accepted: bool
    execution_plan: ExecutionPlan
    selected_provider: ExecutionProviderSelection | None
    gate_decision: ExecutionModeAwareGateDecision
    validation_result: ExecutionRouterValidationResult
    context: ExecutionOrgContextSnapshot | None = None
    permission_decisions: tuple[ExecutionPermissionSnapshot, ...] = ()
    dispatch_ready: bool = False
    live_provider_dispatched: Literal[False] = False
    production_external_call_performed: Literal[False] = False
