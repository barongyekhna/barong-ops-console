from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .ai_execution_binding import AIExecutionBindingStatus, AIExecutionCapability


ModuleAllocationModuleId = Literal["K-series", "P-series", "SEO", "BS"]
ModuleAllocationValidationSeverity = Literal["info", "warning", "error"]


class ModuleCapabilityBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: AIExecutionCapability
    max_units_per_request: int = Field(ge=1)
    max_units_per_window: int = Field(ge=1)
    window_seconds: int = Field(ge=1)
    budget_enforced: Literal[True] = True
    usage_constraint_required: Literal[True] = True
    unlimited_access_allowed: Literal[False] = False
    runtime_metering_performed: Literal[False] = False


class ModuleAllocationRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_id: ModuleAllocationModuleId
    allowed_capabilities: tuple[AIExecutionCapability, ...] = Field(
        min_length=1
    )
    bound_key: str = Field(min_length=1, max_length=180)
    bound_model: str = Field(min_length=1, max_length=180)
    status: AIExecutionBindingStatus
    capability_budgets: tuple[ModuleCapabilityBudget, ...] = Field(
        min_length=1
    )
    reason: str = Field(min_length=1, max_length=500)
    explicit_assignment_required: Literal[True] = True
    binding_must_be_explicit: Literal[True] = True
    bound_key_required: Literal[True] = True
    bound_model_required: Literal[True] = True
    capability_budget_required: Literal[True] = True
    module_to_capability_fixed: Literal[True] = True
    module_to_key_fixed: Literal[True] = True
    module_to_model_fixed: Literal[True] = True
    implicit_capability_access_allowed: Literal[False] = False
    shared_capability_pool_allowed: Literal[False] = False
    cross_module_capability_access_allowed: Literal[False] = False
    fallback_capability_allowed: Literal[False] = False
    fallback_model_selection_allowed: Literal[False] = False
    auto_routing_allowed: Literal[False] = False
    unlimited_ai_access_allowed: Literal[False] = False
    registry_executes_ai: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False
    staging_change_allowed: Literal[False] = False


class ModuleAllocationRegistryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[ModuleAllocationRecord]
    count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    explicit_assignment_required: Literal[True] = True
    no_implicit_capability_access: Literal[True] = True
    no_shared_capability_pool: Literal[True] = True
    capability_budget_required: Literal[True] = True
    no_unlimited_ai_access: Literal[True] = True
    registry_executes_ai: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModuleAllocationCategoryRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_id: ModuleAllocationModuleId
    allowed_capabilities: tuple[AIExecutionCapability, ...]
    category_assignment_source: Literal["c14x_d_static_category_rule"] = (
        "c14x_d_static_category_rule"
    )
    category_rule_grants_runtime_access: Literal[False] = False
    explicit_registry_allocation_required: Literal[True] = True
    budget_required_before_use: Literal[True] = True


class ModuleAllocationCategoryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category_model_id: Literal["c14x_d_module_categories_v1"] = (
        "c14x_d_module_categories_v1"
    )
    items: list[ModuleAllocationCategoryRule]
    count: int = Field(ge=0)
    module_ids: tuple[ModuleAllocationModuleId, ...] = (
        "K-series",
        "P-series",
        "SEO",
        "BS",
    )
    category_templates_only: Literal[True] = True
    category_rule_grants_runtime_access: Literal[False] = False
    explicit_registry_allocation_required: Literal[True] = True
    no_implicit_capability_access: Literal[True] = True
    no_shared_capability_pool: Literal[True] = True
    no_runtime_execution: Literal[True] = True


class ModuleAllocationAssignmentModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    assignment_model_id: Literal["c14x_d_capability_assignment_model_v1"] = (
        "c14x_d_capability_assignment_model_v1"
    )
    allocation_shape: tuple[
        Literal["module_id"],
        Literal["allowed_capabilities"],
        Literal["bound_key"],
        Literal["bound_model"],
        Literal["status"],
        Literal["capability_budgets"],
    ] = (
        "module_id",
        "allowed_capabilities",
        "bound_key",
        "bound_model",
        "status",
        "capability_budgets",
    )
    assignment_policy: Literal["explicit_module_allocation_only"] = (
        "explicit_module_allocation_only"
    )
    unassigned_capability_behavior: Literal["reject_without_fallback"] = (
        "reject_without_fallback"
    )
    missing_budget_behavior: Literal["reject_without_execution"] = (
        "reject_without_execution"
    )
    binding_creation_policy: Literal["manual_registry_only"] = (
        "manual_registry_only"
    )
    implicit_capability_access_allowed: Literal[False] = False
    shared_capability_pool_allowed: Literal[False] = False
    cross_module_capability_access_allowed: Literal[False] = False
    unlimited_ai_access_allowed: Literal[False] = False
    auto_routing_allowed: Literal[False] = False
    fallback_capability_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class ModuleAllocationBudgetItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_id: ModuleAllocationModuleId
    capability: AIExecutionCapability
    bound_key: str = Field(min_length=1, max_length=180)
    bound_model: str = Field(min_length=1, max_length=180)
    status: AIExecutionBindingStatus
    max_units_per_request: int = Field(ge=1)
    max_units_per_window: int = Field(ge=1)
    window_seconds: int = Field(ge=1)
    budget_enforced: Literal[True] = True
    unlimited_access_allowed: Literal[False] = False


class ModuleAllocationBudgetSystem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    budget_system_id: Literal["c14x_d_capability_budget_system_v1"] = (
        "c14x_d_capability_budget_system_v1"
    )
    items: list[ModuleAllocationBudgetItem]
    count: int = Field(ge=0)
    per_module_capability_limits_required: Literal[True] = True
    usage_constraints_required: Literal[True] = True
    missing_budget_behavior: Literal["reject_without_execution"] = (
        "reject_without_execution"
    )
    budget_exhausted_behavior: Literal["reject_without_fallback"] = (
        "reject_without_fallback"
    )
    no_unlimited_ai_access: Literal[True] = True
    registry_executes_ai: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True


class ModuleAllocationEnforcementRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enforcement_id: Literal["c14x_d_module_allocation_enforcement_v1"] = (
        "c14x_d_module_allocation_enforcement_v1"
    )
    flow: tuple[str, ...] = (
        "Read declared module_id, capability, key, model, and usage units",
        "Lookup exact C14X-D module allocation by module_id",
        "Require capability to be explicitly assigned to that module",
        "Require key/model to equal the module allocation binding",
        "Require finite per-capability budget to allow requested usage",
        "Reject missing or mismatched allocation without fallback",
        "Pass validation context to C14X-C routing only after allocation check",
        "Stop before any runtime execution boundary",
    )
    missing_allocation_behavior: Literal["reject_without_fallback"] = (
        "reject_without_fallback"
    )
    capability_not_assigned_behavior: Literal["reject_without_implicit_access"] = (
        "reject_without_implicit_access"
    )
    budget_exceeded_behavior: Literal["reject_without_unlimited_access"] = (
        "reject_without_unlimited_access"
    )
    matching_allocation_behavior: Literal[
        "validation_pass_only_no_execution_grant"
    ] = "validation_pass_only_no_execution_grant"
    implicit_capability_access_blocked: Literal[True] = True
    shared_capability_pool_blocked: Literal[True] = True
    cross_module_capability_access_blocked: Literal[True] = True
    unlimited_ai_access_blocked: Literal[True] = True
    fallback_capability_blocked: Literal[True] = True
    fallback_model_selection_blocked: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModuleAllocationIntegrationFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c14x_d_to_c14x_c_b_c09_c10_flow_v1"] = (
        "c14x_d_to_c14x_c_b_c09_c10_flow_v1"
    )
    flow: tuple[
        Literal["Module"],
        Literal["C14X-D allocation check"],
        Literal["C14X-C routing"],
        Literal["C14X-B model lock"],
        Literal["C09 execution"],
        Literal["C10 sandbox"],
    ] = (
        "Module",
        "C14X-D allocation check",
        "C14X-C routing",
        "C14X-B model lock",
        "C09 execution",
        "C10 sandbox",
    )
    c14x_d_precedes_c14x_c: Literal[True] = True
    c14x_c_precedes_c14x_b: Literal[True] = True
    c14x_b_precedes_c09: Literal[True] = True
    c09_precedes_c10: Literal[True] = True
    allocation_pass_grants_execution: Literal[False] = False
    c14x_d_executes_ai: Literal[False] = False
    c14x_d_invokes_model: Literal[False] = False
    c14x_d_calls_external_api: Literal[False] = False
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModuleAllocationValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: ModuleAllocationValidationSeverity
    code: str = Field(min_length=1, max_length=180)
    message: str = Field(min_length=1, max_length=500)
    module_id: ModuleAllocationModuleId | None = None
    capability: AIExecutionCapability | None = None
    bound_key: str | None = Field(default=None, max_length=180)
    bound_model: str | None = Field(default=None, max_length=180)


class ModuleAllocationValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    issues: list[ModuleAllocationValidationIssue] = Field(default_factory=list)
    allocation_count: int = Field(ge=0)
    active_allocation_count: int = Field(ge=0)
    budget_count: int = Field(ge=0)
    explicit_assignment_required: Literal[True] = True
    category_limits_enforced: Literal[True] = True
    no_implicit_capability_access: Literal[True] = True
    no_shared_capability_pool: Literal[True] = True
    cross_module_capability_access_blocked: Literal[True] = True
    capability_budget_required: Literal[True] = True
    no_unlimited_ai_access: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModuleAllocationRequestValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_id: str = Field(min_length=1, max_length=180)
    capability: str = Field(min_length=1, max_length=180)
    key: str = Field(min_length=1, max_length=180)
    requested_model_id: str = Field(min_length=1, max_length=180)
    requested_units: int = Field(ge=0)
    current_window_units: int = Field(ge=0)
    bound_key: str | None = Field(default=None, max_length=180)
    bound_model: str | None = Field(default=None, max_length=180)
    budget_remaining_units: int | None = Field(default=None, ge=0)
    budget_window_seconds: int | None = Field(default=None, ge=1)
    valid: bool
    allocation_validation_passed: bool
    capability_assignment_passed: bool
    budget_validation_passed: bool
    execution_rejected: bool
    rejection_code: str | None = Field(default=None, max_length=180)
    rejection_reason: str = Field(min_length=1, max_length=500)
    c14x_c_routing_required_next: Literal[True] = True
    c14x_b_model_lock_required_downstream: Literal[True] = True
    implicit_capability_access_blocked: Literal[True] = True
    shared_capability_pool_blocked: Literal[True] = True
    cross_module_capability_access_blocked: Literal[True] = True
    unlimited_ai_access_blocked: Literal[True] = True
    fallback_capability_blocked: Literal[True] = True
    fallback_model_selection_blocked: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModuleAllocationCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C14X-D"] = "C14X-D"
    component: Literal["Module Allocation System"] = (
        "Module Allocation System"
    )
    completion_status: Literal["complete"] = "complete"
    module_allocation_registry_defined: Literal[True] = True
    capability_assignment_model_defined: Literal[True] = True
    module_categories_defined: Literal[True] = True
    capability_budget_system_defined: Literal[True] = True
    enforcement_rules_defined: Literal[True] = True
    integration_flow_defined: Literal[True] = True
    explicit_assignment_required: Literal[True] = True
    no_implicit_capability_access: Literal[True] = True
    no_shared_capability_pool: Literal[True] = True
    no_unlimited_ai_access: Literal[True] = True
    can_proceed_to_c14x_e: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=500)
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True
