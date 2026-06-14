from typing import Any, Literal

from pydantic import BaseModel, Field

from ..schemas.execution_provider import (
    ExecutionLifecycleStatus,
    ExecutionProviderType,
    ExecutionRequestContractV1,
    ExecutionResultContractV1,
    ExecutionRiskLevel,
)
from .resource import ResourcePolicy, ResourceViolation
from .execution_context import (
    ExecutionContext,
    ExecutionContextLifecycleState,
    ExecutionIsolationLevel,
)


SandboxArchitectureStage = Literal[
    "c10a_architecture_only",
    "c10b_mock_runner",
    "c10c_execution_context",
    "c10d_resource_control",
    "c10e_execution_bridge",
    "c10f_runtime_finalization",
]
SandboxBoundaryState = Literal[
    "declared",
    "contract_received",
    "blocked_no_runtime",
    "blocked_policy",
    "mock_lifecycle_simulated",
    "mock_blocked_by_policy",
    "future_provider_pending",
]
SandboxContractMode = Literal["architecture_only", "contract_only", "mock_only"]
SandboxResultStatus = Literal[
    "not_executed",
    "contract_accepted",
    "contract_rejected",
    "blocked_by_policy",
    "mock_succeeded",
    "mock_blocked",
    "future_result_pending",
]
SandboxTrustZone = Literal[
    "user_action",
    "c08_module_adapter",
    "c09_execution_provider",
    "c10_sandbox",
    "future_c15_external_provider",
]
SandboxDeniedCapability = Literal[
    "runtime_execution",
    "external_provider_call",
    "production_access",
    "staging_access",
    "db_mutation",
    "filesystem_write_outside_sandbox",
]


class SandboxRequest(BaseModel):
    request_id: str | None = Field(default=None, max_length=128)
    sandbox_request_id: str | None = Field(default=None, max_length=128)
    context_id: str | None = Field(default=None, max_length=128)
    execution_context_ref: str | None = Field(default=None, max_length=180)
    scope_ref: str | None = Field(default=None, max_length=180)
    memory_scope_ref: str | None = Field(default=None, max_length=180)
    log_scope_ref: str | None = Field(default=None, max_length=180)
    state_scope_ref: str | None = Field(default=None, max_length=180)
    resource_policy_ref: str | None = Field(default=None, max_length=180)
    isolation_level: ExecutionIsolationLevel | None = None
    context_lifecycle_state: ExecutionContextLifecycleState | None = None
    stage: SandboxArchitectureStage = "c10a_architecture_only"
    contract_mode: SandboxContractMode = "architecture_only"
    source_trust_zone: Literal["c09_execution_provider"] = "c09_execution_provider"
    target_trust_zone: Literal["c10_sandbox"] = "c10_sandbox"
    c09_execution_request: ExecutionRequestContractV1
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    provider_key: str = Field(min_length=1, max_length=180)
    provider_type: ExecutionProviderType
    action_key: str = Field(min_length=1, max_length=180)
    actor_user_id: int | None = None
    risk_level: ExecutionRiskLevel
    requested_capabilities: list[str] = Field(default_factory=list)
    denied_capabilities: tuple[SandboxDeniedCapability, ...] = (
        "runtime_execution",
        "external_provider_call",
        "production_access",
        "staging_access",
        "db_mutation",
        "filesystem_write_outside_sandbox",
    )
    target_scope: dict[str, Any] = Field(default_factory=dict)
    sanitized_input_summary: dict[str, Any] = Field(default_factory=dict)
    sandbox_scope_ref: str | None = Field(default=None, max_length=180)
    production_access_policy: Literal["denied"] = "denied"
    external_provider_policy: Literal["denied"] = "denied"
    db_mutation_policy: Literal["denied"] = "denied"
    filesystem_write_policy: Literal["sandbox_scope_only"] = "sandbox_scope_only"


class SandboxResult(BaseModel):
    result_id: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    sandbox_request_id: str | None = Field(default=None, max_length=128)
    context_id: str | None = Field(default=None, max_length=128)
    execution_context_ref: str | None = Field(default=None, max_length=180)
    scope_ref: str | None = Field(default=None, max_length=180)
    memory_scope_ref: str | None = Field(default=None, max_length=180)
    log_scope_ref: str | None = Field(default=None, max_length=180)
    state_scope_ref: str | None = Field(default=None, max_length=180)
    resource_policy_ref: str | None = Field(default=None, max_length=180)
    isolation_level: ExecutionIsolationLevel | None = None
    context_lifecycle_state: ExecutionContextLifecycleState | None = None
    stage: SandboxArchitectureStage = "c10a_architecture_only"
    status: SandboxResultStatus = "not_executed"
    execution_status: ExecutionLifecycleStatus = "skipped"
    boundary_state: SandboxBoundaryState = "blocked_no_runtime"
    result_summary: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    resource_violations: list[ResourceViolation] = Field(default_factory=list)
    error_code: str | None = Field(default=None, max_length=120)
    error_message_safe: str | None = Field(default=None, max_length=500)
    safe_result_only: bool = True
    runtime_created: Literal[False] = False
    external_provider_called: Literal[False] = False
    db_mutated: Literal[False] = False
    production_touched: Literal[False] = False
    staging_touched: Literal[False] = False
    filesystem_write_scope: Literal["none", "sandbox_scope_only"] = "none"


class SandboxResponse(BaseModel):
    response_id: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    sandbox_request_id: str | None = Field(default=None, max_length=128)
    context_id: str | None = Field(default=None, max_length=128)
    execution_context_ref: str | None = Field(default=None, max_length=180)
    stage: SandboxArchitectureStage = "c10a_architecture_only"
    contract_mode: SandboxContractMode = "architecture_only"
    source_trust_zone: Literal["c10_sandbox"] = "c10_sandbox"
    target_trust_zone: Literal["c09_execution_provider"] = "c09_execution_provider"
    result: SandboxResult
    execution_context: ExecutionContext | None = None
    resource_policy: ResourcePolicy | None = None
    c09_result_contract: ExecutionResultContractV1 | None = None
    safety_notes: list[str] = Field(default_factory=list)
    next_stage_policy: Literal[
        "wait_for_c10b",
        "wait_for_c10c",
        "wait_for_c10d",
        "wait_for_c10e",
        "wait_for_c10f",
    ] = "wait_for_c10b"


class SandboxContractInterface(BaseModel):
    contract_key: str = Field(min_length=1, max_length=180)
    contract_version: str = Field(min_length=1, max_length=40)
    request_schema: Literal["SandboxRequest"] = "SandboxRequest"
    response_schema: Literal["SandboxResponse"] = "SandboxResponse"
    context_schema: Literal["SandboxContext"] = "SandboxContext"
    execution_context_schema: Literal["ExecutionContext"] = "ExecutionContext"
    result_schema: Literal["SandboxResult"] = "SandboxResult"
    upstream_contract_ref: Literal["C09 Execution Provider"] = (
        "C09 Execution Provider"
    )
    downstream_contract_ref: Literal["future C15 external provider"] = (
        "future C15 external provider"
    )
    runtime_execution_allowed: Literal[False] = False
