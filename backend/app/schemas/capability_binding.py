from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .ai_execution_binding import AIExecutionBindingStatus, AIExecutionCapability


CapabilityBindingValidationSeverity = Literal["info", "warning", "error"]
ModuleCapabilityBindingStatus = Literal["active", "disabled"]


class CapabilityBindingRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: AIExecutionCapability
    key: str = Field(min_length=1, max_length=180)
    model: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    status: AIExecutionBindingStatus
    reason: str = Field(min_length=1, max_length=500)
    explicit_binding_required: Literal[True] = True
    c14x_a_binding_required: Literal[True] = True
    c14x_b_model_lock_required: Literal[True] = True
    module_capability_binding_required: Literal[True] = True
    capability_to_key_fixed: Literal[True] = True
    capability_to_model_fixed: Literal[True] = True
    capability_to_module_fixed: Literal[True] = True
    key_to_model_fixed: Literal[True] = True
    model_lock_respected: Literal[True] = True
    capability_auto_switch_allowed: Literal[False] = False
    auto_routing_allowed: Literal[False] = False
    fallback_capability_allowed: Literal[False] = False
    fallback_model_selection_allowed: Literal[False] = False
    fallback_routing_allowed: Literal[False] = False
    implicit_capability_access_allowed: Literal[False] = False
    implicit_module_access_allowed: Literal[False] = False
    no_capability_drift: Literal[True] = True
    registry_executes_ai: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False
    staging_change_allowed: Literal[False] = False


class ModuleCapabilityBindingRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: str = Field(min_length=1, max_length=128)
    allowed_capabilities: tuple[AIExecutionCapability, ...] = Field(
        min_length=1
    )
    status: ModuleCapabilityBindingStatus
    reason: str = Field(min_length=1, max_length=500)
    explicit_binding_required: Literal[True] = True
    strict_enforcement_required: Literal[True] = True
    module_to_capability_fixed: Literal[True] = True
    implicit_capability_access_allowed: Literal[False] = False
    cross_module_capability_access_allowed: Literal[False] = False
    fallback_capability_allowed: Literal[False] = False
    auto_routing_allowed: Literal[False] = False
    registry_executes_ai: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False
    staging_change_allowed: Literal[False] = False


class CapabilityRoutePath(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: AIExecutionCapability
    key: str = Field(min_length=1, max_length=180)
    model: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    status: AIExecutionBindingStatus
    c14x_b_locked_model_id: str = Field(min_length=1, max_length=180)
    routing_path: tuple[str, str, str, str]
    explicit_binding_only: Literal[True] = True
    model_lock_respected: Literal[True] = True
    capability_auto_switch_allowed: Literal[False] = False
    auto_routing_allowed: Literal[False] = False
    fallback_capability_allowed: Literal[False] = False
    fallback_model_selection_allowed: Literal[False] = False
    implicit_capability_access_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class CapabilityRoutingModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    routing_model_id: Literal["c14x_c_capability_routing_model_v1"] = (
        "c14x_c_capability_routing_model_v1"
    )
    supported_capabilities: tuple[AIExecutionCapability, ...] = (
        "serp",
        "reasoning",
        "writing",
        "embedding",
    )
    route_shape: tuple[
        Literal["capability"],
        Literal["key"],
        Literal["model"],
        Literal["module"],
        Literal["status"],
    ] = ("capability", "key", "model", "module", "status")
    routes: list[CapabilityRoutePath]
    count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    unbound_capability_behavior: Literal["reject_without_fallback"] = (
        "reject_without_fallback"
    )
    explicit_binding_only: Literal[True] = True
    no_capability_drift: Literal[True] = True
    auto_routing_allowed: Literal[False] = False
    fallback_capability_allowed: Literal[False] = False
    fallback_model_selection_allowed: Literal[False] = False
    implicit_capability_access_allowed: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class CapabilityModelMapping(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: AIExecutionCapability
    model: str = Field(min_length=1, max_length=180)
    key: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    locked_model_id: str = Field(min_length=1, max_length=180)
    mapping_path: tuple[str, str, str, str]
    c14x_b_model_lock_required: Literal[True] = True
    model_lock_respected: Literal[True] = True
    capability_auto_switch_allowed: Literal[False] = False
    fallback_model_selection_allowed: Literal[False] = False
    auto_routing_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class CapabilityModelMappingResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[CapabilityModelMapping]
    count: int = Field(ge=0)
    supported_capabilities: tuple[AIExecutionCapability, ...] = (
        "serp",
        "reasoning",
        "writing",
        "embedding",
    )
    unbound_capability_behavior: Literal["reject_without_fallback"] = (
        "reject_without_fallback"
    )
    explicit_binding_only: Literal[True] = True
    model_lock_respected: Literal[True] = True
    capability_auto_switch_allowed: Literal[False] = False
    fallback_model_selection_allowed: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True


class ModuleCapabilityBindingRulesResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[ModuleCapabilityBindingRecord]
    count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    explicit_binding_required: Literal[True] = True
    strict_enforcement_required: Literal[True] = True
    implicit_capability_access_allowed: Literal[False] = False
    cross_module_capability_access_allowed: Literal[False] = False
    fallback_capability_allowed: Literal[False] = False
    auto_routing_allowed: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True


class CapabilityBindingEnforcementStrategy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enforcement_id: Literal["c14x_c_capability_binding_enforcement_v1"] = (
        "c14x_c_capability_binding_enforcement_v1"
    )
    flow: tuple[str, ...] = (
        "Read declared capability, key, requested model, and module",
        "Lookup exact C14X-C capability binding by capability",
        "Require C14X-C key/model/module to match C14X-A binding",
        "Require C14X-C model to match C14X-B locked model",
        "Require module to explicitly allow the capability",
        "Reject missing or mismatched bindings without fallback",
        "Stop before any runtime execution boundary",
    )
    missing_capability_behavior: Literal["reject_without_fallback"] = (
        "reject_without_fallback"
    )
    model_mismatch_behavior: Literal["reject_without_model_switch"] = (
        "reject_without_model_switch"
    )
    module_binding_missing_behavior: Literal["reject_without_implicit_access"] = (
        "reject_without_implicit_access"
    )
    matching_binding_behavior: Literal["validation_pass_only_no_execution_grant"] = (
        "validation_pass_only_no_execution_grant"
    )
    capability_drift_blocked: Literal[True] = True
    auto_routing_blocked: Literal[True] = True
    fallback_capability_blocked: Literal[True] = True
    fallback_model_selection_blocked: Literal[True] = True
    implicit_capability_access_blocked: Literal[True] = True
    runtime_model_switching_blocked: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class CapabilityBindingValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: CapabilityBindingValidationSeverity
    code: str = Field(min_length=1, max_length=180)
    message: str = Field(min_length=1, max_length=500)
    capability: AIExecutionCapability | None = None
    key: str | None = Field(default=None, max_length=180)
    model: str | None = Field(default=None, max_length=180)
    module: str | None = Field(default=None, max_length=128)


class CapabilityBindingValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    issues: list[CapabilityBindingValidationIssue] = Field(default_factory=list)
    capability_binding_count: int = Field(ge=0)
    active_capability_binding_count: int = Field(ge=0)
    module_binding_count: int = Field(ge=0)
    active_module_binding_count: int = Field(ge=0)
    c14x_a_binding_count: int = Field(ge=0)
    c14x_b_lock_count: int = Field(ge=0)
    route_count: int = Field(ge=0)
    explicit_binding_only: Literal[True] = True
    c14x_a_registry_required: Literal[True] = True
    c14x_b_model_lock_required: Literal[True] = True
    module_capability_binding_required: Literal[True] = True
    no_capability_drift: Literal[True] = True
    auto_routing_blocked: Literal[True] = True
    fallback_capability_blocked: Literal[True] = True
    fallback_model_selection_blocked: Literal[True] = True
    implicit_capability_access_blocked: Literal[True] = True
    runtime_model_switching_blocked: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class CapabilityBindingRequestValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str = Field(min_length=1, max_length=180)
    key: str = Field(min_length=1, max_length=180)
    requested_model_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    bound_model_id: str | None = Field(default=None, max_length=180)
    locked_model_id: str | None = Field(default=None, max_length=180)
    valid: bool
    capability_binding_validation_passed: bool
    module_capability_binding_passed: bool
    model_lock_validation_passed: bool
    execution_rejected: bool
    rejection_code: str | None = Field(default=None, max_length=180)
    rejection_reason: str = Field(min_length=1, max_length=500)
    capability_drift_blocked: Literal[True] = True
    auto_routing_blocked: Literal[True] = True
    fallback_capability_blocked: Literal[True] = True
    fallback_model_selection_blocked: Literal[True] = True
    implicit_capability_access_blocked: Literal[True] = True
    runtime_model_switching_blocked: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class CapabilityBindingIntegrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c14x_c_to_c14x_a_b_capability_binding_v1"] = (
        "c14x_c_to_c14x_a_b_capability_binding_v1"
    )
    upstream_components: tuple[
        Literal["C14X-A AI Execution Binding Registry"],
        Literal["C14X-B Model Lock System"],
    ] = (
        "C14X-A AI Execution Binding Registry",
        "C14X-B Model Lock System",
    )
    downstream_component: Literal["C14X-C Capability Binding Engine"] = (
        "C14X-C Capability Binding Engine"
    )
    join_rules: tuple[str, ...] = (
        "CapabilityBindingRecord.key == AIExecutionBindingRecord.key",
        "CapabilityBindingRecord.model == AIExecutionBindingRecord.model",
        "CapabilityBindingRecord.capability == AIExecutionBindingRecord.capability",
        "CapabilityBindingRecord.module == AIExecutionBindingRecord.module",
        "CapabilityBindingRecord.key == ModelLockRegistryRecord.key_id",
        "CapabilityBindingRecord.model == ModelLockRegistryRecord.model_id",
        "CapabilityBindingRecord.module has explicit ModuleCapabilityBindingRecord",
    )
    every_c14x_a_binding_requires_capability_binding: Literal[True] = True
    every_capability_binding_requires_c14x_b_model_lock: Literal[True] = True
    module_capability_binding_required: Literal[True] = True
    capability_binding_creates_ai_binding: Literal[False] = False
    capability_binding_creates_model_lock: Literal[False] = False
    capability_drift_allowed: Literal[False] = False
    auto_routing_allowed: Literal[False] = False
    fallback_capability_allowed: Literal[False] = False
    fallback_model_selection_allowed: Literal[False] = False
    implicit_capability_access_allowed: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class CapabilityBindingCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C14X-C"] = "C14X-C"
    component: Literal["Capability Binding Engine"] = (
        "Capability Binding Engine"
    )
    completion_status: Literal["complete"] = "complete"
    capability_routing_model_defined: Literal[True] = True
    capability_model_mapping_defined: Literal[True] = True
    module_capability_binding_rules_defined: Literal[True] = True
    enforcement_strategy_defined: Literal[True] = True
    c14x_a_integration_defined: Literal[True] = True
    c14x_b_model_lock_integration_defined: Literal[True] = True
    explicit_binding_only: Literal[True] = True
    no_capability_drift: Literal[True] = True
    auto_routing_blocked: Literal[True] = True
    fallback_capability_blocked: Literal[True] = True
    fallback_model_selection_blocked: Literal[True] = True
    implicit_capability_access_blocked: Literal[True] = True
    can_proceed_to_c14x_d: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=500)
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True
