from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .workflow_registry import WorkflowRegistryStatus


ModuleWorkflowBindingStatus = Literal["active", "read_only", "blocked"]
ModuleWorkflowValidationSeverity = Literal["info", "warning", "error"]


class ModuleWorkflowBindingRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_id: str = Field(min_length=1, max_length=128)
    allowed_workflows: tuple[str, ...]
    binding_status: ModuleWorkflowBindingStatus
    registered_workflows: tuple[str, ...] = ()
    read_only_workflows: tuple[str, ...] = ()
    blocked_workflows: tuple[str, ...] = ()
    source_registry: Literal["C15A Workflow Registry"] = (
        "C15A Workflow Registry"
    )
    explicit_binding_required: Literal[True] = True
    workflow_whitelist_required: Literal[True] = True
    workflow_must_exist_in_c15a_registry: Literal[True] = True
    module_can_call_unlisted_workflow: Literal[False] = False
    cross_module_workflow_call_allowed: Literal[False] = False
    hidden_webhook_reference_exposed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False
    staging_change_allowed: Literal[False] = False


class ModuleWorkflowBindingModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c15f_module_workflow_binding_model_v1"] = (
        "c15f_module_workflow_binding_model_v1"
    )
    binding_shape: tuple[
        Literal["module_id"],
        Literal["allowed_workflows"],
        Literal["binding_status"],
    ] = ("module_id", "allowed_workflows", "binding_status")
    items: list[ModuleWorkflowBindingRecord]
    count: int = Field(ge=0)
    active_binding_count: int = Field(ge=0)
    read_only_binding_count: int = Field(ge=0)
    blocked_binding_count: int = Field(ge=0)
    allowed_workflow_count: int = Field(ge=0)
    c15a_registry_required: Literal[True] = True
    explicit_binding_required: Literal[True] = True
    whitelist_only_access: Literal[True] = True
    unbound_workflow_rejected: Literal[True] = True
    cross_module_workflow_call_allowed: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModuleWorkflowEnforcementRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enforcement_id: Literal["c15f_module_workflow_enforcement_v1"] = (
        "c15f_module_workflow_enforcement_v1"
    )
    flow: tuple[str, ...] = (
        "Read requested module_id and workflow_id",
        "Validate module_id against the registered module registry",
        "Validate workflow_id against the C15A Workflow Registry",
        "Lookup the C15F module workflow whitelist",
        "Require workflow_id to be listed in module_id.allowed_workflows",
        "Reject unregistered, unbound, non-active, or cross-module workflows",
        "Stop before any runtime execution boundary",
    )
    unregistered_workflow_behavior: Literal["reject"] = "reject"
    unbound_workflow_behavior: Literal["reject"] = "reject"
    non_active_workflow_behavior: Literal["reject"] = "reject"
    cross_module_workflow_behavior: Literal["reject"] = "reject"
    arbitrary_workflow_call_behavior: Literal["reject"] = "reject"
    matching_binding_behavior: Literal[
        "binding_validation_pass_only_no_execution"
    ] = "binding_validation_pass_only_no_execution"
    c15a_registry_required: Literal[True] = True
    whitelist_only_access: Literal[True] = True
    module_workflow_isolation_enforced: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False
    staging_change_allowed: Literal[False] = False


class ModuleWorkflowAccessControlSystem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    access_control_id: Literal[
        "c15f_module_workflow_access_control_v1"
    ] = "c15f_module_workflow_access_control_v1"
    registry_source: Literal["C15A Workflow Registry"] = (
        "C15A Workflow Registry"
    )
    whitelist_field: Literal["allowed_workflows"] = "allowed_workflows"
    module_identifier_field: Literal["module_id"] = "module_id"
    workflow_identifier_field: Literal["workflow_id"] = "workflow_id"
    module_can_access_only_allowed_workflows: Literal[True] = True
    workflow_must_be_registered_in_c15a: Literal[True] = True
    module_binding_must_be_active: Literal[True] = True
    implicit_workflow_access_allowed: Literal[False] = False
    fallback_workflow_allowed: Literal[False] = False
    arbitrary_workflow_selection_allowed: Literal[False] = False
    hidden_webhook_reference_exposed: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModuleWorkflowIsolationRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    isolation_id: Literal["c15f_module_workflow_isolation_v1"] = (
        "c15f_module_workflow_isolation_v1"
    )
    rules: tuple[str, ...] = (
        "A workflow belongs to exactly one C15A module.",
        "A C15F allowed_workflows list may contain only workflows owned by the same module_id.",
        "A module must not call a workflow registered for another module.",
        "Cross-module workflow calls are rejected before gateway dispatch.",
    )
    module_a_workflow_equals_module_b_workflow: Literal[False] = False
    cross_module_workflow_call_allowed: Literal[False] = False
    workflow_reassignment_at_runtime_allowed: Literal[False] = False
    isolation_violation_behavior: Literal["reject"] = "reject"
    c15a_registry_required: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModuleWorkflowBindingDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    module_registered: bool
    registered_in_c15a: bool
    module_binding_found: bool
    workflow_owned_by_module: bool
    workflow_in_module_whitelist: bool
    binding_status: ModuleWorkflowBindingStatus | Literal["missing"]
    workflow_registry_status: WorkflowRegistryStatus | Literal["unregistered"]
    workflow_access_allowed: bool
    binding_validation_passed: bool
    isolation_violation: bool
    execution_rejected: bool
    rejection_code: str | None = Field(default=None, max_length=180)
    reason: str = Field(min_length=1, max_length=500)
    c15a_registry_required: Literal[True] = True
    explicit_binding_required: Literal[True] = True
    whitelist_only_access: Literal[True] = True
    hidden_webhook_reference_exposed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False
    staging_change_allowed: Literal[False] = False


class ModuleWorkflowBindingValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: ModuleWorkflowValidationSeverity
    code: str = Field(min_length=1, max_length=180)
    message: str = Field(min_length=1, max_length=500)
    module_id: str | None = Field(default=None, max_length=128)
    workflow_id: str | None = Field(default=None, max_length=180)


class ModuleWorkflowBindingValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    issues: list[ModuleWorkflowBindingValidationIssue] = Field(
        default_factory=list
    )
    module_binding_count: int = Field(ge=0)
    active_module_binding_count: int = Field(ge=0)
    read_only_module_binding_count: int = Field(ge=0)
    blocked_module_binding_count: int = Field(ge=0)
    allowed_workflow_count: int = Field(ge=0)
    c15a_registry_workflow_count: int = Field(ge=0)
    explicit_binding_required: Literal[True] = True
    whitelist_only_access: Literal[True] = True
    c15a_registry_required: Literal[True] = True
    module_workflow_isolation_enforced: Literal[True] = True
    unbound_workflow_rejected: Literal[True] = True
    arbitrary_workflow_call_blocked: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModuleWorkflowBindingCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15F"] = "C15F"
    component: Literal["Module Workflow Binding Engine"] = (
        "Module Workflow Binding Engine"
    )
    completion_status: Literal["complete"] = "complete"
    module_workflow_binding_model_defined: Literal[True] = True
    enforcement_rules_defined: Literal[True] = True
    access_control_system_defined: Literal[True] = True
    isolation_rules_defined: Literal[True] = True
    c15a_registry_integration_defined: Literal[True] = True
    unbound_workflow_rejected: Literal[True] = True
    arbitrary_workflow_call_blocked: Literal[True] = True
    cross_module_workflow_call_blocked: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True
    can_proceed_to_c15g: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=500)
