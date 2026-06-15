from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


WorkflowRegistryTrigger = Literal["webhook"]
WorkflowRegistryStatus = Literal[
    "active",
    "inactive",
    "deprecated",
    "error",
]
WorkflowRegistryDecisionMode = Literal["executable", "blocked", "read_only"]
WorkflowRegistryValidationSeverity = Literal["info", "warning", "error"]


class WorkflowRegistryRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    trigger: WorkflowRegistryTrigger
    status: WorkflowRegistryStatus
    n8n_webhook: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=64)
    created_at: str = Field(min_length=1, max_length=40)
    updated_at: str = Field(min_length=1, max_length=40)

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class WorkflowRegistryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[WorkflowRegistryRecord]
    count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    explicit_module_binding_required: Literal[True] = True
    one_module_can_bind_multiple_workflows: Literal[True] = True
    real_n8n_webhook_address_exposed: Literal[False] = False
    registry_is_single_source_of_truth: Literal[True] = True
    registry_executes_workflow: Literal[False] = False


class ModuleWorkflowBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: str = Field(min_length=1, max_length=128)
    workflow_ids: tuple[str, ...]
    active_workflow_ids: tuple[str, ...] = ()
    inactive_workflow_ids: tuple[str, ...] = ()
    deprecated_workflow_ids: tuple[str, ...] = ()
    error_workflow_ids: tuple[str, ...] = ()
    workflow_count: int = Field(ge=0)
    explicit_binding_required: Literal[True] = True


class ModuleWorkflowBindingResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[ModuleWorkflowBinding]
    count: int = Field(ge=0)
    one_module_can_bind_multiple_workflows: Literal[True] = True
    explicit_binding_required: Literal[True] = True


class WorkflowStatusRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: WorkflowRegistryStatus
    execution_allowed: bool
    read_only: bool
    decision_mode: WorkflowRegistryDecisionMode
    reason: str = Field(min_length=1, max_length=500)


class WorkflowStatusManagementModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c15a_workflow_status_management_v1"] = (
        "c15a_workflow_status_management_v1"
    )
    allowed_statuses: tuple[WorkflowRegistryStatus, ...] = (
        "active",
        "inactive",
        "deprecated",
        "error",
    )
    rules: tuple[WorkflowStatusRule, ...]
    active_is_executable: Literal[True] = True
    inactive_blocks_execution: Literal[True] = True
    deprecated_is_read_only: Literal[True] = True
    error_blocks_execution: Literal[True] = True
    registry_executes_workflow: Literal[False] = False


class WorkflowRegistryRulesModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c15a_workflow_registry_rules_v1"] = (
        "c15a_workflow_registry_rules_v1"
    )
    record_shape: tuple[
        Literal["workflow_id"],
        Literal["module"],
        Literal["trigger"],
        Literal["status"],
        Literal["n8n_webhook"],
        Literal["version"],
        Literal["created_at"],
        Literal["updated_at"],
    ] = (
        "workflow_id",
        "module",
        "trigger",
        "status",
        "n8n_webhook",
        "version",
        "created_at",
        "updated_at",
    )
    allowed_trigger: Literal["webhook"] = "webhook"
    allowed_statuses: tuple[WorkflowRegistryStatus, ...] = (
        "active",
        "inactive",
        "deprecated",
        "error",
    )
    unregistered_workflow_callable: Literal[False] = False
    explicit_module_binding_required: Literal[True] = True
    real_n8n_webhook_address_exposure_allowed: Literal[False] = False
    registry_is_single_source_of_truth: Literal[True] = True
    auto_create_unregistered_workflow_allowed: Literal[False] = False
    registry_executes_workflow: Literal[False] = False
    no_n8n_execution: Literal[True] = True
    no_ai_model_trigger: Literal[True] = True
    no_production_or_staging_change: Literal[True] = True


class WorkflowInvocationDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    registered: bool
    bound_to_module: bool
    status: WorkflowRegistryStatus | Literal["unregistered"]
    execution_allowed: bool
    read_only: bool
    decision_mode: WorkflowRegistryDecisionMode
    hidden_webhook_ref: str | None = Field(default=None, max_length=255)
    reason: str = Field(min_length=1, max_length=500)
    registry_executes_workflow: Literal[False] = False
    no_n8n_execution: Literal[True] = True
    no_ai_model_trigger: Literal[True] = True


class WorkflowRegistryValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: WorkflowRegistryValidationSeverity
    code: str = Field(min_length=1, max_length=180)
    message: str = Field(min_length=1, max_length=500)
    workflow_id: str | None = Field(default=None, max_length=180)
    module: str | None = Field(default=None, max_length=128)


class WorkflowRegistryValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    issues: list[WorkflowRegistryValidationIssue] = Field(default_factory=list)
    workflow_count: int = Field(ge=0)
    module_binding_count: int = Field(ge=0)
    active_workflow_count: int = Field(ge=0)
    explicit_module_binding_required: Literal[True] = True
    hidden_webhook_policy_enforced: Literal[True] = True
    registry_is_single_source_of_truth: Literal[True] = True
    no_n8n_execution: Literal[True] = True
    no_ai_model_trigger: Literal[True] = True


class WorkflowSystemFlowDiagram(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: Literal["c15a_workflow_registry_flow_v1"] = (
        "c15a_workflow_registry_flow_v1"
    )
    diagram: Literal[
        "Module -> C15A Registry -> C15B -> n8n webhook -> C15D callback"
    ] = "Module -> C15A Registry -> C15B -> n8n webhook -> C15D callback"
    nodes: tuple[
        Literal["Module"],
        Literal["C15A Registry"],
        Literal["C15B"],
        Literal["n8n webhook"],
        Literal["C15D callback"],
    ] = (
        "Module",
        "C15A Registry",
        "C15B",
        "n8n webhook",
        "C15D callback",
    )
    edges: tuple[str, ...] = (
        "Module requests workflow by explicit module/workflow_id binding",
        "C15A validates registration, binding, hidden webhook ref, and status",
        "C15B may dispatch only an active decision from C15A",
        "n8n webhook returns through the governed callback boundary",
        "C15D callback records results without mutating C15A registration",
    )
    registry_is_single_source_of_truth: Literal[True] = True
    registry_executes_workflow: Literal[False] = False
    no_n8n_execution: Literal[True] = True
    no_ai_model_trigger: Literal[True] = True


class WorkflowRegistryCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15A"] = "C15A"
    component: Literal["Workflow Registry System"] = (
        "Workflow Registry System"
    )
    completion_status: Literal["complete"] = "complete"
    registry_model_defined: Literal[True] = True
    module_binding_mapping_defined: Literal[True] = True
    status_management_logic_defined: Literal[True] = True
    system_flow_diagram_defined: Literal[True] = True
    hidden_webhook_policy_enforced: Literal[True] = True
    registry_is_single_source_of_truth: Literal[True] = True
    can_proceed_to_c15b: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=500)
    no_n8n_execution: Literal[True] = True
    no_ai_model_trigger: Literal[True] = True
    no_production_or_staging_change: Literal[True] = True
