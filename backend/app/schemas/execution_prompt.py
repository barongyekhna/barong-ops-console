from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .ai_execution_binding import AIExecutionBindingRecord, AIExecutionCapability
from .capability_binding import (
    CapabilityBindingRecord,
    CapabilityBindingRequestValidationResult,
)
from .model_lock import ModelLockRegistryRecord, ModelLockRequestValidationResult
from .module_allocation import (
    ModuleAllocationModuleId,
    ModuleAllocationRecord,
    ModuleAllocationRequestValidationResult,
)


ExecutionPromptValidationSeverity = Literal["info", "warning", "error"]


class ExecutionPromptTemplateEngineDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine_id: Literal["c14x_e_prompt_template_engine_v1"] = (
        "c14x_e_prompt_template_engine_v1"
    )
    required_inputs: tuple[
        Literal["module_id"],
        Literal["capability"],
        Literal["model"],
        Literal["key"],
        Literal["context"],
    ] = ("module_id", "capability", "model", "key", "context")
    template_sections: tuple[
        Literal["system_boundary"],
        Literal["binding_injection"],
        Literal["assembled_context"],
        Literal["task_context"],
        Literal["output_contract"],
        Literal["safety_rules"],
    ] = (
        "system_boundary",
        "binding_injection",
        "assembled_context",
        "task_context",
        "output_contract",
        "safety_rules",
    )
    render_policy: Literal["deterministic_static_template_only"] = (
        "deterministic_static_template_only"
    )
    missing_binding_behavior: Literal["reject_without_prompt"] = (
        "reject_without_prompt"
    )
    context_policy: Literal["safe_structured_context_only"] = (
        "safe_structured_context_only"
    )
    prompt_generation_executes_ai: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False
    staging_change_allowed: Literal[False] = False
    docker_allowed: Literal[False] = False
    pytest_allowed: Literal[False] = False
    git_commit_allowed: Literal[False] = False


class ExecutionPromptBindingInjectionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    injection_id: Literal["c14x_e_binding_injection_model_v1"] = (
        "c14x_e_binding_injection_model_v1"
    )
    injection_order: tuple[
        Literal["C14X-A key binding"],
        Literal["C14X-B model lock"],
        Literal["C14X-C capability routing"],
        Literal["C14X-D module allocation"],
    ] = (
        "C14X-A key binding",
        "C14X-B model lock",
        "C14X-C capability routing",
        "C14X-D module allocation",
    )
    key_binding_required: Literal[True] = True
    model_lock_required: Literal[True] = True
    capability_routing_required: Literal[True] = True
    module_allocation_required: Literal[True] = True
    exact_key_match_required: Literal[True] = True
    exact_model_match_required: Literal[True] = True
    exact_capability_match_required: Literal[True] = True
    active_binding_required: Literal[True] = True
    fallback_binding_allowed: Literal[False] = False
    auto_routing_allowed: Literal[False] = False
    implicit_capability_access_allowed: Literal[False] = False
    shared_capability_pool_allowed: Literal[False] = False
    unlimited_ai_access_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class ExecutionPromptSecurityConstraints(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    constraints_id: Literal["c14_security_constraints_for_c14x_e_v1"] = (
        "c14_security_constraints_for_c14x_e_v1"
    )
    source_components: tuple[
        Literal["C14A secret classification"],
        Literal["C14B secret storage policy"],
        Literal["C14C secret access control"],
        Literal["C14D external dependency governance"],
        Literal["C14E dependency binding rules"],
        Literal["C14F validation layer"],
        Literal["C14G final seal"],
    ] = (
        "C14A secret classification",
        "C14B secret storage policy",
        "C14C secret access control",
        "C14D external dependency governance",
        "C14E dependency binding rules",
        "C14F validation layer",
        "C14G final seal",
    )
    raw_secret_allowed: Literal[False] = False
    secret_in_prompt_allowed: Literal[False] = False
    secret_in_context_allowed: Literal[False] = False
    c09_direct_secret_access_allowed: Literal[False] = False
    c10_raw_secret_injection_allowed: Literal[False] = False
    external_dependency_default_decision: Literal["deny"] = "deny"
    unknown_service_decision: Literal["quarantine"] = "quarantine"
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_change_allowed: Literal[False] = False
    staging_change_allowed: Literal[False] = False
    docker_allowed: Literal[False] = False
    pytest_allowed: Literal[False] = False
    git_commit_allowed: Literal[False] = False


class ExecutionPromptContextAssemblyRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rules_id: Literal["c14x_e_context_assembly_rules_v1"] = (
        "c14x_e_context_assembly_rules_v1"
    )
    required_context_blocks: tuple[
        Literal["module_context"],
        Literal["capability_context"],
        Literal["model_context"],
        Literal["security_constraints"],
        Literal["input_context"],
    ] = (
        "module_context",
        "capability_context",
        "model_context",
        "security_constraints",
        "input_context",
    )
    module_context_source: Literal["C14X-D module allocation"] = (
        "C14X-D module allocation"
    )
    capability_context_source: Literal["C14X-C capability routing"] = (
        "C14X-C capability routing"
    )
    model_context_source: Literal["C14X-B model lock"] = (
        "C14X-B model lock"
    )
    key_context_source: Literal["C14X-A key binding"] = "C14X-A key binding"
    security_context_source: Literal["C14 final seal"] = "C14 final seal"
    context_must_be_sanitized: Literal[True] = True
    missing_context_behavior: Literal["reject_without_prompt"] = (
        "reject_without_prompt"
    )
    prompt_context_grants_execution: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class ExecutionPromptModuleContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_id: ModuleAllocationModuleId
    routed_module: str = Field(min_length=1, max_length=128)
    allowed_capabilities: tuple[AIExecutionCapability, ...]
    bound_key: str = Field(min_length=1, max_length=180)
    bound_model: str = Field(min_length=1, max_length=180)
    allocation_status: str = Field(min_length=1, max_length=40)
    requested_units: int = Field(ge=0)
    current_window_units: int = Field(ge=0)
    budget_remaining_units: int | None = Field(default=None, ge=0)
    budget_window_seconds: int | None = Field(default=None, ge=1)
    allocation_pass_grants_execution: Literal[False] = False


class ExecutionPromptCapabilityContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: AIExecutionCapability
    key: str = Field(min_length=1, max_length=180)
    model: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=40)
    routing_path: tuple[str, str, str, str]
    capability_routing_grants_execution: Literal[False] = False


class ExecutionPromptModelContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key_id: str = Field(min_length=1, max_length=180)
    requested_model_id: str = Field(min_length=1, max_length=180)
    locked_model_id: str = Field(min_length=1, max_length=180)
    lock_timestamp: str = Field(min_length=20, max_length=40)
    model_lock_validation_grants_execution: Literal[False] = False


class ExecutionPromptStructuredInputContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    context_id: str = Field(min_length=1, max_length=180)
    module_context: ExecutionPromptModuleContext
    capability_context: ExecutionPromptCapabilityContext
    model_context: ExecutionPromptModelContext
    security_constraints: ExecutionPromptSecurityConstraints
    input_context: dict[str, Any] = Field(default_factory=dict)
    no_secret_material: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True


class ExecutionPromptBindingInjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key_binding: AIExecutionBindingRecord | None = None
    model_lock: ModelLockRegistryRecord | None = None
    capability_route: CapabilityBindingRecord | None = None
    module_allocation: ModuleAllocationRecord | None = None
    model_lock_validation: ModelLockRequestValidationResult | None = None
    capability_routing_validation: (
        CapabilityBindingRequestValidationResult | None
    ) = None
    module_allocation_validation: (
        ModuleAllocationRequestValidationResult | None
    ) = None
    all_bindings_injected: bool
    exact_binding_match: bool
    active_binding_match: bool
    execution_rejected: bool
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class AIExecutionPrompt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_id: str = Field(min_length=1, max_length=180)
    template_id: Literal["c14x_e_ai_execution_prompt_template_v1"] = (
        "c14x_e_ai_execution_prompt_template_v1"
    )
    module_id: ModuleAllocationModuleId
    capability: AIExecutionCapability
    key: str = Field(min_length=1, max_length=180)
    model: str = Field(min_length=1, max_length=180)
    prompt_text: str = Field(min_length=1, max_length=50000)
    prompt_is_contract_only: Literal[True] = True
    prompt_executes_ai: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class C09CompatibleExecutionPromptPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    payload_id: str = Field(min_length=1, max_length=180)
    payload_version: Literal["c14x_e_c09_compatible_payload_v1"] = (
        "c14x_e_c09_compatible_payload_v1"
    )
    c09_contract_shape: Literal[
        "ExecutionRequestContractV1_compatible_draft"
    ] = "ExecutionRequestContractV1_compatible_draft"
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: Literal["c14x.e.prompt_generator.contract"] = (
        "c14x.e.prompt_generator.contract"
    )
    action_key: Literal["c14x.e.generate_prompt_contract"] = (
        "c14x.e.generate_prompt_contract"
    )
    provider_key: Literal["c14x.e.contract_only_prompt_provider"] = (
        "c14x.e.contract_only_prompt_provider"
    )
    provider_type: Literal["contract_only_provider"] = "contract_only_provider"
    status: Literal["draft"] = "draft"
    risk_level: Literal["low"] = "low"
    required_permission: Literal["modules.read"] = "modules.read"
    input_payload: dict[str, Any] = Field(default_factory=dict)
    sanitized_input_summary: dict[str, Any] = Field(default_factory=dict)
    execution_requested: Literal[False] = False
    can_submit_to_c09: Literal[False] = False
    creates_execution_request: Literal[False] = False
    writes_operation_log: Literal[False] = False
    writes_artifact: Literal[False] = False
    not_submittable_reason: str = Field(min_length=1, max_length=500)
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ExecutionPromptValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: ExecutionPromptValidationSeverity
    code: str = Field(min_length=1, max_length=180)
    message: str = Field(min_length=1, max_length=500)


class ExecutionPromptGenerationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    generation_status: Literal["generated", "rejected"]
    generation_allowed: bool
    rejection_code: str | None = Field(default=None, max_length=180)
    rejection_reason: str | None = Field(default=None, max_length=500)
    binding_injection: ExecutionPromptBindingInjection
    structured_input_context: ExecutionPromptStructuredInputContext | None = None
    ai_execution_prompt: AIExecutionPrompt | None = None
    c09_compatible_payload: C09CompatibleExecutionPromptPayload | None = None
    issues: list[ExecutionPromptValidationIssue] = Field(default_factory=list)
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True
    no_docker: Literal[True] = True
    no_pytest: Literal[True] = True
    no_git_commit: Literal[True] = True


class ExecutionPromptValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    issues: list[ExecutionPromptValidationIssue] = Field(default_factory=list)
    prompt_template_engine_defined: Literal[True] = True
    binding_injection_model_defined: Literal[True] = True
    execution_payload_builder_defined: Literal[True] = True
    context_assembly_rules_defined: Literal[True] = True
    c14_security_constraints_defined: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ExecutionPromptCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C14X-E"] = "C14X-E"
    component: Literal["Execution Prompt Generator"] = (
        "Execution Prompt Generator"
    )
    completion_status: Literal["complete"] = "complete"
    prompt_template_engine_defined: Literal[True] = True
    binding_injection_model_defined: Literal[True] = True
    execution_payload_builder_defined: Literal[True] = True
    context_assembly_rules_defined: Literal[True] = True
    c14_security_constraints_defined: Literal[True] = True
    c09_compatible_payload_defined: Literal[True] = True
    c14x_system_fully_complete: Literal[True] = True
    c14x_system_fully_complete_answer: Literal["YES"] = "YES"
    proceed_reason: str = Field(min_length=1, max_length=500)
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True
    no_docker: Literal[True] = True
    no_pytest: Literal[True] = True
    no_git_commit: Literal[True] = True
