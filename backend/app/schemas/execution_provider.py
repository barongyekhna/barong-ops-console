from typing import Any, Literal

from pydantic import BaseModel, Field


ExecutionProviderType = Literal[
    "no_op_provider",
    "mock_provider",
    "contract_only_provider",
    "local_backend_provider",
    "queue_provider",
    "webhook_provider",
    "scheduled_provider",
    "future_live_provider",
]
ExecutionProviderStatus = Literal[
    "draft",
    "contract_ready",
    "test_ready",
    "provider_pending",
    "provider_unavailable",
    "disabled",
    "deprecated",
    "sealed",
]
ExecutionProviderLifecycle = ExecutionProviderStatus
ExecutionMode = Literal[
    "contract_only",
    "no_op",
    "mock",
    "local_backend",
    "queue",
    "webhook",
    "scheduled",
    "future_live",
]
ExecutionActionType = Literal[
    "read",
    "manage",
    "run",
    "sync",
    "generate",
    "review",
    "export",
    "publish",
    "prepare",
    "declare",
    "test_run",
]
ExecutionRiskLevel = Literal["low", "medium", "high", "critical"]
ExecutionLifecycleStatus = Literal[
    "draft",
    "requested",
    "blocked_permission",
    "blocked_approval_required",
    "blocked_provider_unavailable",
    "accepted",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "retry_scheduled",
    "skipped",
    "rejected",
    "archived",
]
ApprovalStatus = Literal[
    "not_required",
    "blocked_approval_required",
    "waiting_c12",
]
SecretBindingStatus = Literal[
    "not_required",
    "declared_only",
    "secret_rules_required",
    "waiting_c14",
]
ScopeStatus = Literal[
    "not_required",
    "adapter_pending",
    "scope_adapter_pending",
    "waiting_c18",
]
ProviderAccessState = Literal[
    "visible",
    "hidden",
    "locked",
    "unavailable",
    "blocked",
    "provider_pending",
    "disabled",
    "deprecated",
]


class ExecutionSchemaDeclaration(BaseModel):
    schema_key: str = Field(min_length=1, max_length=180)
    schema_version: str = Field(min_length=1, max_length=40)
    model_name: str = Field(min_length=1, max_length=120)
    fields: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    status_values: list[ExecutionLifecycleStatus] = Field(default_factory=list)
    serialization_policy: str = Field(min_length=1, max_length=160)
    persistence_policy: Literal["contract_only_no_persistence"] = (
        "contract_only_no_persistence"
    )
    redaction_policy: str = Field(min_length=1, max_length=160)


class ExecutionRequestContractV1(BaseModel):
    execution_id: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=180)
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    action_key: str = Field(min_length=1, max_length=180)
    actor_user_id: int | None = None
    target_scope: dict[str, Any] = Field(default_factory=dict)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    sanitized_input_summary: dict[str, Any] = Field(default_factory=dict)
    provider_key: str = Field(min_length=1, max_length=180)
    provider_type: ExecutionProviderType
    status: ExecutionLifecycleStatus = "draft"
    risk_level: ExecutionRiskLevel
    required_permission: str = Field(min_length=1, max_length=255)
    approval_status: ApprovalStatus = "not_required"
    secret_binding_status: SecretBindingStatus = "not_required"
    created_at: str | None = None
    accepted_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    cancelled_at: str | None = None
    timeout_at: str | None = None
    result_summary: dict[str, Any] | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    error_code: str | None = Field(default=None, max_length=120)
    error_message_safe: str | None = Field(default=None, max_length=500)
    operation_log_id: str | None = Field(default=None, max_length=128)


class ExecutionResultContractV1(BaseModel):
    execution_id: str | None = Field(default=None, max_length=128)
    provider_key: str = Field(min_length=1, max_length=180)
    status: ExecutionLifecycleStatus
    result_summary: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    error_code: str | None = Field(default=None, max_length=120)
    error_message_safe: str | None = Field(default=None, max_length=500)
    operation_log_id: str | None = Field(default=None, max_length=128)
    safe_result_only: bool = True


class ExecutionStateContractV1(BaseModel):
    current_status: ExecutionLifecycleStatus = "draft"
    allowed_statuses: list[ExecutionLifecycleStatus]
    blocked_statuses: list[ExecutionLifecycleStatus]
    terminal_statuses: list[ExecutionLifecycleStatus]
    transition_policy: str = Field(min_length=1, max_length=160)
    executable_in_c09b: bool = False


class ExecutionApprovalRequirement(BaseModel):
    requires_approval: bool = False
    approval_status: ApprovalStatus = "not_required"
    approval_provider_state: Literal["not_required", "waiting_c12"] = (
        "not_required"
    )
    blocks_execution_in_c09b: bool = False
    reason: str = Field(min_length=1, max_length=255)


class ExecutionSecretRequirement(BaseModel):
    requires_secret: bool = False
    secret_binding_status: SecretBindingStatus = "not_required"
    secret_value_declared: bool = False
    provider_credential_declared: bool = False
    secret_read_allowed: bool = False
    rules_provider_state: Literal["not_required", "waiting_c14"] = "not_required"
    blocks_execution_in_c09b: bool = False
    reason: str = Field(min_length=1, max_length=255)


class ExecutionScopeRequirement(BaseModel):
    requires_scope: bool = False
    scope_status: ScopeStatus = "not_required"
    allowed_scope_types: list[str] = Field(default_factory=list)
    requires_c18_scope_adapter: bool = False
    blocks_execution_in_c09b: bool = False
    reason: str = Field(min_length=1, max_length=255)


class ExecutionPolicyDeclaration(BaseModel):
    policy_key: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1, max_length=500)
    c09b_behavior: str = Field(min_length=1, max_length=255)
    enabled_in_c09b: bool = False


class ExecutionOperationLogPolicy(BaseModel):
    operation_log_action: str = Field(min_length=1, max_length=180)
    write_policy: Literal["declared_only"] = "declared_only"
    writes_operation_logs_in_c09b: bool = False
    details_projection: list[str] = Field(default_factory=list)
    redaction_policy: str = Field(min_length=1, max_length=160)


class ExecutionAuditEventPolicy(BaseModel):
    event_refs: list[str] = Field(default_factory=list)
    write_policy: Literal["declared_only"] = "declared_only"
    writes_audit_events_in_c09b: bool = False


class ExecutionArtifactPolicy(BaseModel):
    artifact_refs_allowed: bool = True
    writes_artifacts_in_c09b: bool = False
    local_path_allowed: bool = False
    external_reference_allowed: bool = False
    safe_reference_only: bool = True


class ExecutionCallbackPolicy(BaseModel):
    callback_supported: bool = False
    callback_connected_in_c09b: bool = False
    correlation_id_policy: str = Field(min_length=1, max_length=160)
    external_endpoint_declared: bool = False


class ExecutionFailurePolicy(BaseModel):
    safe_error_code_required: bool = True
    safe_error_message_required: bool = True
    raw_provider_error_exposed: bool = False
    retry_requires_policy_match: bool = True


class ExecutionFallbackBehavior(BaseModel):
    permission_missing: str = Field(min_length=1, max_length=160)
    approval_missing: str = Field(min_length=1, max_length=160)
    secret_missing: str = Field(min_length=1, max_length=160)
    scope_missing: str = Field(min_length=1, max_length=160)
    provider_missing: str = Field(min_length=1, max_length=160)


class ExecutionUnavailableBehavior(BaseModel):
    block_reason: str = Field(min_length=1, max_length=160)
    safe_status_message: str = Field(min_length=1, max_length=255)
    show_to_user: bool = True


class ExecutionProviderTestContract(BaseModel):
    test_key: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1, max_length=500)
    required: bool = True


class ExecutionProviderContractV1(BaseModel):
    provider_key: str = Field(min_length=1, max_length=180)
    provider_version: str = Field(min_length=1, max_length=40)
    provider_type: ExecutionProviderType
    provider_status: ExecutionProviderStatus
    lifecycle: ExecutionProviderLifecycle
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    supported_execution_modes: list[ExecutionMode] = Field(default_factory=list)
    supported_action_types: list[ExecutionActionType] = Field(default_factory=list)
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    action_key: str = Field(min_length=1, max_length=180)
    execution_request_schema: ExecutionSchemaDeclaration
    execution_result_schema: ExecutionSchemaDeclaration
    execution_state_schema: ExecutionSchemaDeclaration
    required_permissions: list[str] = Field(default_factory=list)
    risk_level: ExecutionRiskLevel
    approval_requirement: ExecutionApprovalRequirement
    secret_requirement: ExecutionSecretRequirement
    scope_requirement: ExecutionScopeRequirement
    idempotency_policy: ExecutionPolicyDeclaration
    retry_policy: ExecutionPolicyDeclaration
    timeout_policy: ExecutionPolicyDeclaration
    cancellation_policy: ExecutionPolicyDeclaration
    concurrency_policy: ExecutionPolicyDeclaration
    rate_limit_policy: ExecutionPolicyDeclaration
    operation_log_policy: ExecutionOperationLogPolicy
    audit_event_policy: ExecutionAuditEventPolicy
    artifact_policy: ExecutionArtifactPolicy
    callback_policy: ExecutionCallbackPolicy
    failure_policy: ExecutionFailurePolicy
    fallback_behavior: ExecutionFallbackBehavior
    unavailable_behavior: ExecutionUnavailableBehavior
    test_contracts: list[ExecutionProviderTestContract] = Field(
        default_factory=list
    )
    docs_path: str = Field(min_length=1, max_length=255)
    operation_log_action: str = Field(min_length=1, max_length=180)
    requires_execution_provider: bool = False
    requires_approval: bool = False
    executable: bool = False
    can_request_execution: bool = False
    live_provider_connected: bool = False
    external_endpoint_declared: bool = False
    credential_declared: bool = False


class ExecutionProviderRead(ExecutionProviderContractV1):
    pass


class ExecutionProviderRegistryResponse(BaseModel):
    items: list[ExecutionProviderRead]
    count: int = Field(ge=0)


class ExecutionProviderAccessRead(BaseModel):
    provider_key: str
    provider_type: ExecutionProviderType
    provider_status: ExecutionProviderStatus
    provider_access_state: ProviderAccessState
    module_key: str
    adapter_key: str
    action_key: str
    visible: bool
    hidden: bool
    locked: bool
    unavailable: bool
    blocked: bool
    block_reason: str
    required_permission: str
    missing_permissions: list[str]
    risk_level: ExecutionRiskLevel
    requires_approval: bool
    approval_status: ApprovalStatus
    requires_secret: bool
    secret_binding_status: SecretBindingStatus
    requires_scope: bool
    scope_status: ScopeStatus
    execution_mode: ExecutionMode
    can_request_execution: bool
    executable: bool
    no_execute_reason: str
    operation_log_action: str
    safe_status_message: str


class ExecutionProviderAccessListResponse(BaseModel):
    user_id: int
    role: str
    is_owner_full_access: bool
    items: list[ExecutionProviderAccessRead]
    count: int = Field(ge=0)
