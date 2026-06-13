from typing import Any, Literal

from pydantic import BaseModel, Field

from ..schemas.execution_provider import ExecutionRiskLevel
from .types import SandboxArchitectureStage, SandboxTrustZone


class SandboxTrustBoundary(BaseModel):
    boundary_key: str = Field(min_length=1, max_length=180)
    inbound_zone: Literal["c09_execution_provider"] = "c09_execution_provider"
    sandbox_zone: Literal["c10_sandbox"] = "c10_sandbox"
    outbound_zone: Literal["future_c15_external_provider"] = (
        "future_c15_external_provider"
    )
    trusted_contract_source: Literal["C09 Execution Provider"] = (
        "C09 Execution Provider"
    )
    untrusted_payload_policy: Literal["sanitize_before_runtime"] = (
        "sanitize_before_runtime"
    )
    external_system_trust: Literal["untrusted_not_connected"] = (
        "untrusted_not_connected"
    )
    production_trust: Literal["denied"] = "denied"
    staging_trust: Literal["denied"] = "denied"


class SandboxContext(BaseModel):
    context_id: str | None = Field(default=None, max_length=128)
    stage: SandboxArchitectureStage = "c10a_architecture_only"
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    provider_key: str = Field(min_length=1, max_length=180)
    action_key: str = Field(min_length=1, max_length=180)
    actor_user_id: int | None = None
    risk_level: ExecutionRiskLevel
    source_zone: Literal["c09_execution_provider"] = "c09_execution_provider"
    current_zone: Literal["c10_sandbox"] = "c10_sandbox"
    future_target_zone: Literal["future_c15_external_provider"] = (
        "future_c15_external_provider"
    )
    trust_boundary: SandboxTrustBoundary
    execution_context_ref: str | None = Field(default=None, max_length=180)
    sandbox_scope_ref: str | None = Field(default=None, max_length=180)
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    sanitized_input_summary: dict[str, Any] = Field(default_factory=dict)
    visible_trust_zones: list[SandboxTrustZone] = Field(default_factory=list)
    runtime_execution_policy: Literal[
        "not_available_in_c10a",
        "mock_simulation_only",
    ] = "not_available_in_c10a"
    external_provider_policy: Literal["denied"] = "denied"
    db_mutation_policy: Literal["denied"] = "denied"
    filesystem_write_policy: Literal["sandbox_scope_only"] = "sandbox_scope_only"
