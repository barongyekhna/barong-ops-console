from typing import Literal

from pydantic import BaseModel, Field


AdapterStatus = Literal[
    "draft",
    "adapter_pending",
    "contract_ready",
    "test_ready",
    "staging_ready",
    "production_ready",
    "disabled",
    "deprecated",
    "sealed",
]
AdapterLifecycle = AdapterStatus
AdapterSurface = Literal[
    "navigation",
    "dashboard_card",
    "module_page",
    "detail_page",
    "action_panel",
    "settings_panel",
    "audit_log_view",
    "status_widget",
    "future_approval_panel",
]
AdapterRiskLevel = Literal["low", "medium", "high", "critical"]
AdapterBindingStatus = Literal[
    "draft",
    "adapter_pending",
    "contract_ready",
    "test_ready",
    "staging_ready",
    "production_ready",
    "disabled",
    "deprecated",
    "sealed",
]
AdapterDeniedBehavior = Literal["show_locked", "hide_when_denied"]
AdapterUnavailableBehavior = Literal[
    "hide",
    "show_unavailable",
    "planned",
    "adapter_pending",
    "execution_not_connected",
    "provider_not_connected",
    "disabled",
]
AdapterAccessState = Literal[
    "available",
    "locked",
    "hidden",
    "unavailable",
    "adapter_pending",
    "disabled",
]
AdapterDependencyName = Literal[
    "n8n",
    "woocommerce",
    "minio",
    "filebrowser",
    "ai_provider",
    "serp",
    "wecom",
    "google_sheets",
]
ExecutionProviderState = Literal[
    "not_required",
    "required_not_implemented_c08b",
    "adapter_pending",
    "disabled",
]


class ModuleAdapterPage(BaseModel):
    page_key: str = Field(min_length=1, max_length=160)
    module_key: str = Field(min_length=1, max_length=128)
    surface: AdapterSurface
    route: str = Field(min_length=1, max_length=255)
    route_namespace: str = Field(min_length=1, max_length=255)
    required_permission: str | None = Field(default=None, max_length=255)
    status: AdapterBindingStatus
    unavailable_behavior: AdapterUnavailableBehavior
    component_ref: str | None = Field(default=None, max_length=160)
    data_contract_refs: list[str] = Field(default_factory=list)
    action_refs: list[str] = Field(default_factory=list)


class ModuleAdapterNavBinding(BaseModel):
    nav_key: str = Field(min_length=1, max_length=160)
    module_key: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=120)
    group: str = Field(min_length=1, max_length=80)
    icon: str = Field(min_length=1, max_length=80)
    order: int = Field(ge=0)
    route: str = Field(min_length=1, max_length=255)
    required_permission: str | None = Field(default=None, max_length=255)
    denied_behavior: AdapterDeniedBehavior
    unavailable_behavior: AdapterUnavailableBehavior
    default_visible: bool = True
    owner_only: bool = False


class ModuleAdapterRouteBinding(BaseModel):
    route_key: str = Field(min_length=1, max_length=160)
    module_key: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=255)
    route_namespace: str = Field(min_length=1, max_length=255)
    surface: AdapterSurface
    required_permission: str | None = Field(default=None, max_length=255)
    guard_policy: str = Field(min_length=1, max_length=120)
    status: AdapterBindingStatus


class ModuleAdapterApiBinding(BaseModel):
    api_key: str = Field(min_length=1, max_length=160)
    module_key: str = Field(min_length=1, max_length=128)
    api_namespace: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=255)
    method: Literal["GET", "POST", "PATCH", "DELETE", "NO_API"]
    required_permission: str | None = Field(default=None, max_length=255)
    status: AdapterBindingStatus
    no_api: bool = False


class ModuleAdapterCapability(BaseModel):
    capability_key: str = Field(min_length=1, max_length=160)
    module_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    required_permission: str | None = Field(default=None, max_length=255)
    surfaces: list[AdapterSurface] = Field(default_factory=list)


class ModuleAdapterAction(BaseModel):
    action_key: str = Field(min_length=1, max_length=180)
    module_key: str = Field(min_length=1, max_length=128)
    capability_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    required_permission: str = Field(min_length=1, max_length=255)
    risk_level: AdapterRiskLevel
    requires_approval: bool = False
    requires_execution_provider: bool = False
    operation_log_action: str = Field(min_length=1, max_length=180)
    executable_before_c09: bool = False
    status: AdapterBindingStatus


class ModuleAdapterActionContract(BaseModel):
    action_key: str = Field(min_length=1, max_length=180)
    input_contract: str = Field(min_length=1, max_length=180)
    output_contract: str = Field(min_length=1, max_length=180)
    required_permission: str = Field(min_length=1, max_length=255)
    risk_level: AdapterRiskLevel
    requires_approval: bool = False
    requires_execution_provider: bool = False
    execution_requirement_ref: str | None = Field(default=None, max_length=180)
    operation_log_action: str = Field(min_length=1, max_length=180)
    audit_event_refs: list[str] = Field(default_factory=list)
    idempotency_policy: str = Field(min_length=1, max_length=160)
    timeout_policy: str = Field(min_length=1, max_length=160)
    fallback_behavior: str = Field(min_length=1, max_length=160)
    executable_before_c09: bool = False


class ModuleAdapterStatusProvider(BaseModel):
    provider_key: str = Field(min_length=1, max_length=160)
    module_key: str = Field(min_length=1, max_length=128)
    status_contract: str = Field(min_length=1, max_length=160)
    allowed_statuses: list[str] = Field(default_factory=list)
    source: str = Field(min_length=1, max_length=120)
    live_provider_connected: bool = False
    last_checked_at_policy: str = Field(min_length=1, max_length=160)
    safe_message_policy: str = Field(min_length=1, max_length=160)
    secret_read_allowed: bool = False


class ModuleAdapterHealthProvider(BaseModel):
    provider_key: str = Field(min_length=1, max_length=160)
    module_key: str = Field(min_length=1, max_length=128)
    health_contract: str = Field(min_length=1, max_length=160)
    checks: list[str] = Field(default_factory=list)
    mock_only: bool = True
    live_check_allowed: bool = False
    secret_read_allowed: bool = False
    safe_failure_behavior: str = Field(min_length=1, max_length=160)


class ModuleAdapterDataContract(BaseModel):
    contract_key: str = Field(min_length=1, max_length=180)
    contract_version: str = Field(min_length=1, max_length=40)
    module_key: str = Field(min_length=1, max_length=128)
    object_type: str = Field(min_length=1, max_length=120)
    schema_ref: str = Field(min_length=1, max_length=180)
    read_boundary: list[str] = Field(default_factory=list)
    write_boundary: list[str] = Field(default_factory=list)
    owner_module: str = Field(min_length=1, max_length=128)
    version_policy: str = Field(min_length=1, max_length=160)
    test_fixture_path: str | None = Field(default=None, max_length=255)
    breaking_change_policy: str = Field(min_length=1, max_length=160)


class ModuleAdapterInputContract(BaseModel):
    contract_key: str = Field(min_length=1, max_length=180)
    action_key: str | None = Field(default=None, max_length=180)
    schema_ref: str = Field(min_length=1, max_length=180)
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    validation_rules: list[str] = Field(default_factory=list)
    sensitive_fields: list[str] = Field(default_factory=list)
    redaction_policy: str = Field(min_length=1, max_length=160)


class ModuleAdapterOutputContract(BaseModel):
    contract_key: str = Field(min_length=1, max_length=180)
    action_key: str | None = Field(default=None, max_length=180)
    schema_ref: str = Field(min_length=1, max_length=180)
    safe_summary_fields: list[str] = Field(default_factory=list)
    sensitive_fields: list[str] = Field(default_factory=list)
    redaction_policy: str = Field(min_length=1, max_length=160)
    operation_log_projection: list[str] = Field(default_factory=list)


class ModuleAdapterPermissionBinding(BaseModel):
    permission_key: str = Field(min_length=1, max_length=255)
    module_key: str = Field(min_length=1, max_length=128)
    used_by: str = Field(min_length=1, max_length=160)
    surface: AdapterSurface | None = None
    action_key: str | None = Field(default=None, max_length=180)
    risk_level: AdapterRiskLevel = "low"
    required: bool = True
    registry_status: Literal["declared", "registered"] = "registered"
    pending_registration_reason: str | None = Field(default=None, max_length=255)


class ModuleAdapterScopeBinding(BaseModel):
    status: Literal["adapter_pending"] = "adapter_pending"
    declared_scope_types: list[str] = Field(default_factory=list)
    requires_c18_scope_adapter: bool = True
    default_scope_policy: str = Field(min_length=1, max_length=160)
    scope_validation_ref: str = Field(min_length=1, max_length=180)
    fallback_before_c18: str = Field(min_length=1, max_length=160)


class ModuleAdapterOperationLogBinding(BaseModel):
    action_key: str = Field(min_length=1, max_length=180)
    operation_log_action: str = Field(min_length=1, max_length=180)
    target_type: str = Field(min_length=1, max_length=120)
    target_id_policy: str = Field(min_length=1, max_length=160)
    details_projection: list[str] = Field(default_factory=list)
    redaction_policy: str = Field(min_length=1, max_length=160)
    result_values: list[str] = Field(default_factory=list)
    failure_values: list[str] = Field(default_factory=list)
    rollback_action: str | None = Field(default=None, max_length=180)


class ModuleAdapterAuditEvent(BaseModel):
    event_key: str = Field(min_length=1, max_length=180)
    module_key: str = Field(min_length=1, max_length=128)
    source_action: str | None = Field(default=None, max_length=180)
    severity: Literal["low", "medium", "high", "critical"]
    operation_log_action: str | None = Field(default=None, max_length=180)
    retention_policy: str = Field(min_length=1, max_length=160)
    view_surface: AdapterSurface | None = None


class ModuleAdapterFeatureFlagBinding(BaseModel):
    feature_flag_key: str = Field(min_length=1, max_length=160)
    module_key: str = Field(min_length=1, max_length=128)
    status: Literal["declared_only"] = "declared_only"
    switch_provider_state: Literal["not_implemented_c08b"] = (
        "not_implemented_c08b"
    )


class ModuleAdapterDependencyDeclaration(BaseModel):
    dependency_key: AdapterDependencyName
    dependency_type: str = Field(min_length=1, max_length=80)
    required: bool = False
    provider_status: Literal["declared_only", "not_connected"] = (
        "declared_only"
    )
    provider_contract_ref: str | None = Field(default=None, max_length=180)
    secret_requirement_ref: str | None = Field(default=None, max_length=180)
    live_connection_allowed: bool = False
    safe_unavailable_message: str = Field(min_length=1, max_length=255)


class ModuleAdapterExecutionRequirements(BaseModel):
    requires_execution_provider: bool = False
    executable_before_c09: bool = False
    execution_provider_state: ExecutionProviderState = "not_required"
    provider_contract_ref: str | None = Field(default=None, max_length=180)
    queue_required: bool = False
    result_contract_ref: str | None = Field(default=None, max_length=180)


class ModuleAdapterSandboxRequirements(BaseModel):
    sandbox_required: bool = False
    status: Literal["declared_only", "not_required"] = "not_required"
    data_boundary_ref: str | None = Field(default=None, max_length=180)
    network_access_allowed: bool = False
    file_system_access_allowed: bool = False


class ModuleAdapterApprovalRequirements(BaseModel):
    requires_approval: bool = False
    high_risk_action_policy: str = Field(min_length=1, max_length=160)
    approval_provider_state: Literal["not_implemented_c08b"] = (
        "not_implemented_c08b"
    )
    approval_reason_required: bool = False


class ModuleAdapterSecretRequirement(BaseModel):
    requirement_key: str = Field(min_length=1, max_length=160)
    requirement_type: str = Field(min_length=1, max_length=120)
    secret_value_declared: bool = False
    provider_credential_declared: bool = False
    status: Literal["declared_only", "not_required"] = "declared_only"


class ModuleAdapterFallbackBehavior(BaseModel):
    adapter_missing: str = Field(min_length=1, max_length=160)
    provider_missing: str = Field(min_length=1, max_length=160)
    execution_missing: str = Field(min_length=1, max_length=160)
    permission_missing: str = Field(min_length=1, max_length=160)


class ModuleAdapterTestContract(BaseModel):
    test_key: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1, max_length=500)
    required: bool = True


class ModuleAdapterContractV1(BaseModel):
    adapter_key: str = Field(min_length=1, max_length=180)
    adapter_version: str = Field(min_length=1, max_length=40)
    module_key: str = Field(min_length=1, max_length=128)
    manifest_version: str = Field(min_length=1, max_length=40)
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    adapter_status: AdapterStatus
    lifecycle: AdapterLifecycle
    supported_surfaces: list[AdapterSurface] = Field(default_factory=list)
    pages: list[ModuleAdapterPage] = Field(default_factory=list)
    nav_bindings: list[ModuleAdapterNavBinding] = Field(default_factory=list)
    route_bindings: list[ModuleAdapterRouteBinding] = Field(default_factory=list)
    api_bindings: list[ModuleAdapterApiBinding] = Field(default_factory=list)
    capabilities: list[ModuleAdapterCapability] = Field(default_factory=list)
    actions: list[ModuleAdapterAction] = Field(default_factory=list)
    action_contracts: list[ModuleAdapterActionContract] = Field(
        default_factory=list
    )
    status_provider: ModuleAdapterStatusProvider
    health_provider: ModuleAdapterHealthProvider
    data_contracts: list[ModuleAdapterDataContract] = Field(default_factory=list)
    input_contracts: list[ModuleAdapterInputContract] = Field(default_factory=list)
    output_contracts: list[ModuleAdapterOutputContract] = Field(
        default_factory=list
    )
    permission_bindings: list[ModuleAdapterPermissionBinding] = Field(
        default_factory=list
    )
    scope_bindings: list[ModuleAdapterScopeBinding] = Field(default_factory=list)
    operation_log_bindings: list[ModuleAdapterOperationLogBinding] = Field(
        default_factory=list
    )
    audit_events: list[ModuleAdapterAuditEvent] = Field(default_factory=list)
    feature_flag_bindings: list[ModuleAdapterFeatureFlagBinding] = Field(
        default_factory=list
    )
    dependency_declarations: list[ModuleAdapterDependencyDeclaration] = Field(
        default_factory=list
    )
    execution_requirements: ModuleAdapterExecutionRequirements
    sandbox_requirements: ModuleAdapterSandboxRequirements
    approval_requirements: ModuleAdapterApprovalRequirements
    secret_requirements: list[ModuleAdapterSecretRequirement] = Field(
        default_factory=list
    )
    fallback_behavior: ModuleAdapterFallbackBehavior
    unavailable_behavior: AdapterUnavailableBehavior
    test_contracts: list[ModuleAdapterTestContract] = Field(default_factory=list)
    docs_path: str = Field(min_length=1, max_length=255)


class ModuleAdapterRead(ModuleAdapterContractV1):
    pass


class ModuleAdapterRegistryResponse(BaseModel):
    items: list[ModuleAdapterRead]
    count: int = Field(ge=0)


class ModuleAdapterAccessRead(BaseModel):
    adapter_key: str
    module_key: str
    visible: bool
    hidden: bool
    locked: bool
    unavailable: bool
    adapter_status: AdapterStatus
    adapter_access_state: AdapterAccessState
    supported_surfaces: list[AdapterSurface]
    available_surfaces: list[AdapterSurface]
    disabled_surfaces: list[AdapterSurface]
    action_contracts: list[ModuleAdapterActionContract]
    available_actions: list[str]
    locked_actions: list[str]
    unavailable_actions: list[str]
    required_permissions: list[str]
    missing_permissions: list[str]
    requires_execution_provider: bool
    execution_provider_state: ExecutionProviderState
    requires_approval: bool
    reason: str


class ModuleAdapterAccessListResponse(BaseModel):
    user_id: int
    role: str
    is_owner_full_access: bool
    items: list[ModuleAdapterAccessRead]
    count: int = Field(ge=0)
