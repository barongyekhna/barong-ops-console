from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ModelLockValidationSeverity = Literal["info", "warning", "error"]


class ModelLockRegistryRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key_id: str = Field(min_length=1, max_length=180)
    model_id: str = Field(min_length=1, max_length=180)
    locked: Literal[True] = True
    lock_timestamp: str = Field(min_length=20, max_length=40)
    lock_reason: str = Field(min_length=1, max_length=500)
    one_key_one_model_required: Literal[True] = True
    model_change_allowed: Literal[False] = False
    runtime_model_switching_allowed: Literal[False] = False
    fallback_model_selection_allowed: Literal[False] = False
    implicit_routing_override_allowed: Literal[False] = False
    registry_executes_ai: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True
    production_change_allowed: Literal[False] = False
    staging_change_allowed: Literal[False] = False


class ModelLockRegistryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[ModelLockRegistryRecord]
    count: int = Field(ge=0)
    locked_count: int = Field(ge=0)
    one_key_one_model_enforced: Literal[True] = True
    model_change_allowed: Literal[False] = False
    runtime_model_switching_allowed: Literal[False] = False
    fallback_model_selection_allowed: Literal[False] = False
    implicit_routing_override_allowed: Literal[False] = False
    registry_executes_ai: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModelLockRuleModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c14x_b_model_lock_rules_v1"] = (
        "c14x_b_model_lock_rules_v1"
    )
    registry_shape: tuple[
        Literal["key_id"],
        Literal["model_id"],
        Literal["locked"],
        Literal["lock_timestamp"],
        Literal["lock_reason"],
    ] = ("key_id", "model_id", "locked", "lock_timestamp", "lock_reason")
    upstream_registry: Literal["C14X-A AI Execution Binding Registry"] = (
        "C14X-A AI Execution Binding Registry"
    )
    key_to_model_source: Literal["C14X-A key -> model binding"] = (
        "C14X-A key -> model binding"
    )
    one_key_one_model_required: Literal[True] = True
    model_reuse_allowed: Literal[False] = False
    model_change_allowed: Literal[False] = False
    lock_update_policy: Literal["immutable_after_binding"] = (
        "immutable_after_binding"
    )
    request_validation_policy: Literal["exact_key_and_model_match_required"] = (
        "exact_key_and_model_match_required"
    )
    runtime_model_switching_allowed: Literal[False] = False
    fallback_model_selection_allowed: Literal[False] = False
    implicit_routing_override_allowed: Literal[False] = False
    binding_creation_policy: Literal["explicit_c14x_a_binding_required"] = (
        "explicit_c14x_a_binding_required"
    )
    registry_executes_ai: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModelLockEnforcementLogic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enforcement_id: Literal["c14x_b_model_lock_enforcement_v1"] = (
        "c14x_b_model_lock_enforcement_v1"
    )
    flow: tuple[str, ...] = (
        "Read declared key_id and requested model_id",
        "Lookup exact C14X-B model lock by key_id",
        "Require requested model_id to equal locked model_id",
        "Reject execution on missing lock or mismatch",
        "Stop before any runtime execution boundary",
    )
    missing_lock_behavior: Literal["reject_without_fallback"] = (
        "reject_without_fallback"
    )
    mismatch_behavior: Literal["reject_execution"] = "reject_execution"
    matching_lock_behavior: Literal["validation_pass_only_no_execution_grant"] = (
        "validation_pass_only_no_execution_grant"
    )
    runtime_model_switching_blocked: Literal[True] = True
    fallback_model_selection_blocked: Literal[True] = True
    implicit_routing_override_blocked: Literal[True] = True
    registry_executes_ai: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModelLockValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: ModelLockValidationSeverity
    code: str = Field(min_length=1, max_length=180)
    message: str = Field(min_length=1, max_length=500)
    key_id: str | None = Field(default=None, max_length=180)
    model_id: str | None = Field(default=None, max_length=180)


class ModelLockRegistryValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    issues: list[ModelLockValidationIssue] = Field(default_factory=list)
    lock_count: int = Field(ge=0)
    locked_count: int = Field(ge=0)
    c14x_a_binding_count: int = Field(ge=0)
    one_key_one_model_enforced: Literal[True] = True
    model_change_blocked: Literal[True] = True
    runtime_model_switching_blocked: Literal[True] = True
    fallback_model_selection_blocked: Literal[True] = True
    implicit_routing_override_blocked: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModelLockRequestValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key_id: str = Field(min_length=1, max_length=180)
    requested_model_id: str = Field(min_length=1, max_length=180)
    locked_model_id: str | None = Field(default=None, max_length=180)
    valid: bool
    lock_validation_passed: bool
    execution_rejected: bool
    rejection_code: str | None = Field(default=None, max_length=180)
    rejection_reason: str = Field(min_length=1, max_length=500)
    runtime_model_switching_blocked: Literal[True] = True
    fallback_model_selection_blocked: Literal[True] = True
    implicit_routing_override_blocked: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModelLockC14XAIntegration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c14x_b_to_c14x_a_model_lock_v1"] = (
        "c14x_b_to_c14x_a_model_lock_v1"
    )
    upstream_component: Literal["C14X-A AI Execution Binding Registry"] = (
        "C14X-A AI Execution Binding Registry"
    )
    downstream_component: Literal["C14X-B Model Lock System"] = (
        "C14X-B Model Lock System"
    )
    join_rules: tuple[str, ...] = (
        "ModelLockRegistryRecord.key_id == AIExecutionBindingRecord.key",
        "ModelLockRegistryRecord.model_id == AIExecutionBindingRecord.model",
    )
    every_c14x_a_binding_requires_model_lock: Literal[True] = True
    orphan_model_lock_allowed: Literal[False] = False
    lock_mismatch_blocks_execution: Literal[True] = True
    lock_registry_creates_ai_binding: Literal[False] = False
    runtime_model_switching_allowed: Literal[False] = False
    fallback_model_selection_allowed: Literal[False] = False
    implicit_routing_override_allowed: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True


class ModelLockCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C14X-B"] = "C14X-B"
    component: Literal["Model Lock System"] = "Model Lock System"
    completion_status: Literal["complete"] = "complete"
    model_lock_registry_defined: Literal[True] = True
    lock_mechanism_defined: Literal[True] = True
    enforcement_logic_defined: Literal[True] = True
    validation_rules_defined: Literal[True] = True
    c14x_a_integration_defined: Literal[True] = True
    one_key_one_model_enforced: Literal[True] = True
    runtime_model_switching_blocked: Literal[True] = True
    fallback_model_selection_blocked: Literal[True] = True
    implicit_routing_override_blocked: Literal[True] = True
    can_proceed_to_c14x_c: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=500)
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True
