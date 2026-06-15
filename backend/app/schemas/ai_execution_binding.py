from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AIExecutionCapability = Literal["serp", "reasoning", "writing", "embedding"]
AIExecutionBindingStatus = Literal["draft", "active", "disabled", "deprecated"]
AIExecutionBindingValidationSeverity = Literal["info", "warning", "error"]


class AIExecutionBindingRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1, max_length=180)
    model: str = Field(min_length=1, max_length=180)
    capability: AIExecutionCapability
    module: str = Field(min_length=1, max_length=128)
    status: AIExecutionBindingStatus
    reason: str = Field(min_length=1, max_length=500)
    explicit_binding_required: Literal[True] = True
    one_to_one_binding_required: Literal[True] = True
    key_to_model_fixed: Literal[True] = True
    model_to_capability_fixed: Literal[True] = True
    capability_to_module_fixed: Literal[True] = True
    automatic_model_selection_allowed: Literal[False] = False
    fallback_routing_allowed: Literal[False] = False
    implicit_execution_routing_allowed: Literal[False] = False
    registry_executes_ai: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False


class AIExecutionBindingRegistryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[AIExecutionBindingRecord]
    count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    one_to_one_binding_enforced: Literal[True] = True
    explicit_binding_required: Literal[True] = True
    automatic_model_selection_allowed: Literal[False] = False
    fallback_routing_allowed: Literal[False] = False
    implicit_execution_routing_allowed: Literal[False] = False
    registry_executes_ai: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True


class AIExecutionBindingRuleModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c14x_a_ai_execution_binding_rules_v1"] = (
        "c14x_a_ai_execution_binding_rules_v1"
    )
    binding_shape: tuple[
        Literal["key"],
        Literal["model"],
        Literal["capability"],
        Literal["module"],
        Literal["status"],
    ] = ("key", "model", "capability", "module", "status")
    allowed_capabilities: tuple[AIExecutionCapability, ...] = (
        "serp",
        "reasoning",
        "writing",
        "embedding",
    )
    allowed_statuses: tuple[AIExecutionBindingStatus, ...] = (
        "draft",
        "active",
        "disabled",
        "deprecated",
    )
    key_to_model_fixed: Literal[True] = True
    model_to_capability_fixed: Literal[True] = True
    capability_to_module_fixed: Literal[True] = True
    one_to_one_binding_required: Literal[True] = True
    automatic_model_selection_allowed: Literal[False] = False
    fallback_routing_allowed: Literal[False] = False
    implicit_execution_routing_allowed: Literal[False] = False
    binding_creation_policy: Literal["explicit_only"] = "explicit_only"
    binding_update_policy: Literal["manual_override_only"] = (
        "manual_override_only"
    )
    binding_deletion_policy: Literal["controlled_operation_only"] = (
        "controlled_operation_only"
    )
    ui_write_surface_exposed: Literal[False] = False
    registry_executes_ai: Literal[False] = False
    registry_only_defines_routing_path: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True


class AIExecutionBindingValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: AIExecutionBindingValidationSeverity
    code: str = Field(min_length=1, max_length=180)
    message: str = Field(min_length=1, max_length=500)
    key: str | None = Field(default=None, max_length=180)
    model: str | None = Field(default=None, max_length=180)
    capability: AIExecutionCapability | None = None
    module: str | None = Field(default=None, max_length=128)


class AIExecutionBindingValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    issues: list[AIExecutionBindingValidationIssue] = Field(default_factory=list)
    binding_count: int = Field(ge=0)
    active_binding_count: int = Field(ge=0)
    route_count: int = Field(ge=0)
    one_to_one_binding_enforced: Literal[True] = True
    no_automatic_model_selection: Literal[True] = True
    no_fallback_routing: Literal[True] = True
    no_implicit_execution_routing: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True


class AIExecutionRoutePath(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1, max_length=180)
    model: str = Field(min_length=1, max_length=180)
    capability: AIExecutionCapability
    module: str = Field(min_length=1, max_length=128)
    status: AIExecutionBindingStatus
    routing_path: tuple[str, str, str, str]
    registry_only_defines_routing_path: Literal[True] = True
    registry_executes_ai: Literal[False] = False
    execution_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    fallback_route_available: Literal[False] = False


class AIExecutionFlowMapping(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: Literal["c14x_a_ai_execution_binding_flow_v1"] = (
        "c14x_a_ai_execution_binding_flow_v1"
    )
    flow: tuple[str, ...] = (
        "UI exact binding key inspection",
        "C14X-A registry exact key lookup",
        "Fixed key -> model -> capability -> module path",
        "Stop before any runtime execution boundary",
    )
    routes: list[AIExecutionRoutePath]
    count: int = Field(ge=0)
    registry_executes_ai: Literal[False] = False
    registry_only_defines_routing_path: Literal[True] = True
    automatic_model_selection_allowed: Literal[False] = False
    fallback_routing_allowed: Literal[False] = False
    implicit_execution_routing_allowed: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True


class AIExecutionBindingUIInteractionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    interaction_id: Literal["c14x_a_ui_registry_interaction_v1"] = (
        "c14x_a_ui_registry_interaction_v1"
    )
    allowed_methods: tuple[Literal["GET"], ...] = ("GET",)
    allowed_paths: tuple[str, ...] = (
        "/api/control-plane/ai-execution-bindings/registry",
        "/api/control-plane/ai-execution-bindings/rules",
        "/api/control-plane/ai-execution-bindings/execution-flow",
        "/api/control-plane/ai-execution-bindings/validation",
        "/api/control-plane/ai-execution-bindings/ui-interaction",
        "/api/control-plane/ai-execution-bindings/completion-status",
    )
    lookup_mode: Literal["exact_binding_key_only"] = "exact_binding_key_only"
    create_update_delete_surface: Literal["not_exposed_in_ui"] = (
        "not_exposed_in_ui"
    )
    binding_creation_policy: Literal["explicit_only"] = "explicit_only"
    binding_update_policy: Literal["manual_override_only"] = (
        "manual_override_only"
    )
    binding_deletion_policy: Literal["controlled_operation_only"] = (
        "controlled_operation_only"
    )
    automatic_model_selection_allowed: Literal[False] = False
    fallback_routing_allowed: Literal[False] = False
    implicit_execution_routing_allowed: Literal[False] = False
    registry_executes_ai: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True


class AIExecutionBindingCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C14X-A"] = "C14X-A"
    component: Literal["AI Execution Binding Registry"] = (
        "AI Execution Binding Registry"
    )
    completion_status: Literal["complete"] = "complete"
    registry_structure_defined: Literal[True] = True
    binding_rule_model_defined: Literal[True] = True
    execution_flow_mapping_defined: Literal[True] = True
    ui_registry_interaction_defined: Literal[True] = True
    one_to_one_binding_enforced: Literal[True] = True
    can_proceed_to_c14x_b: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=500)
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
