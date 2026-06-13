from typing import Literal

from pydantic import BaseModel, Field


class ProcessIsolationPolicy(BaseModel):
    policy_key: str = Field(min_length=1, max_length=180)
    model: Literal["process_isolation_concept_only"] = (
        "process_isolation_concept_only"
    )
    process_spawn_allowed_in_c10a: Literal[False] = False
    shared_process_allowed: Literal[False] = False
    host_runtime_access: Literal["denied"] = "denied"
    future_runtime_ref: Literal["c10b_or_later"] = "c10b_or_later"


class MemoryIsolationPolicy(BaseModel):
    policy_key: str = Field(min_length=1, max_length=180)
    model: Literal["request_scoped_memory_concept"] = "request_scoped_memory_concept"
    cross_request_memory_allowed: Literal[False] = False
    secret_material_allowed: Literal[False] = False
    raw_provider_response_allowed: Literal[False] = False
    retained_memory_policy: Literal["none_in_c10a"] = "none_in_c10a"


class ExecutionContextSeparationPolicy(BaseModel):
    policy_key: str = Field(min_length=1, max_length=180)
    model: Literal["context_per_request"] = "context_per_request"
    module_context_ref: str | None = Field(default=None, max_length=180)
    adapter_context_ref: str | None = Field(default=None, max_length=180)
    provider_context_ref: str | None = Field(default=None, max_length=180)
    context_reuse_allowed: Literal[False] = False
    privilege_escalation_allowed: Literal[False] = False


class SideEffectPreventionRules(BaseModel):
    rules_key: str = Field(min_length=1, max_length=180)
    production_access: Literal["denied"] = "denied"
    staging_access: Literal["denied"] = "denied"
    external_provider_call: Literal["denied"] = "denied"
    db_write: Literal["denied"] = "denied"
    operation_log_write: Literal["denied_in_c10a"] = "denied_in_c10a"
    audit_event_write: Literal["denied_in_c10a"] = "denied_in_c10a"
    filesystem_write: Literal["sandbox_scope_only"] = "sandbox_scope_only"
    network_access: Literal["denied"] = "denied"
    secret_read: Literal["denied"] = "denied"


class SandboxIsolationProfile(BaseModel):
    profile_key: str = Field(min_length=1, max_length=180)
    process: ProcessIsolationPolicy
    memory: MemoryIsolationPolicy
    execution_context: ExecutionContextSeparationPolicy
    side_effects: SideEffectPreventionRules
    runtime_created: Literal[False] = False
    executable_in_c10a: Literal[False] = False


class ModuleExecutionContainerSpec(BaseModel):
    container_key: str = Field(min_length=1, max_length=180)
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    provider_key: str = Field(min_length=1, max_length=180)
    action_key: str = Field(min_length=1, max_length=180)
    isolation_profile_ref: str = Field(min_length=1, max_length=180)
    request_context_ref: str | None = Field(default=None, max_length=180)
    input_mount_policy: Literal["sanitized_contract_only"] = (
        "sanitized_contract_only"
    )
    output_mount_policy: Literal["safe_result_contract_only"] = (
        "safe_result_contract_only"
    )
    filesystem_scope_policy: Literal["sandbox_scope_only"] = "sandbox_scope_only"
    runtime_binding_status: Literal["not_created_in_c10a"] = "not_created_in_c10a"

