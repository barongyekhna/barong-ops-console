from typing import Literal

from pydantic import BaseModel, Field

from .context import SandboxContext, SandboxTrustBoundary
from .isolation import ModuleExecutionContainerSpec, SandboxIsolationProfile
from .types import SandboxContractInterface


class SandboxRuntimeBoundary(BaseModel):
    boundary_key: str = Field(min_length=1, max_length=180)
    stage: Literal["c10a_architecture_only"] = "c10a_architecture_only"
    inbound_stage: Literal["C09 Execution Provider"] = "C09 Execution Provider"
    boundary_stage: Literal["C10 Sandbox"] = "C10 Sandbox"
    future_outbound_stage: Literal["future C15 external provider"] = (
        "future C15 external provider"
    )
    accepted_input: Literal["C09 execution request contract"] = (
        "C09 execution request contract"
    )
    emitted_output: Literal["sandbox response contract"] = (
        "sandbox response contract"
    )
    runtime_execution_allowed: Literal[False] = False
    external_provider_call_allowed: Literal[False] = False


class ExecutionIsolationLayer(BaseModel):
    layer_key: str = Field(min_length=1, max_length=180)
    stage: Literal["c10a_architecture_only"] = "c10a_architecture_only"
    isolation_profile: SandboxIsolationProfile
    trust_boundary: SandboxTrustBoundary
    process_isolation_status: Literal["concept_only"] = "concept_only"
    memory_isolation_status: Literal["declared_only"] = "declared_only"
    execution_context_status: Literal["declared_only"] = "declared_only"
    side_effect_policy_status: Literal["deny_by_contract"] = "deny_by_contract"
    runtime_binding_status: Literal["not_created_in_c10a"] = "not_created_in_c10a"


class ModuleExecutionContainer(BaseModel):
    container: ModuleExecutionContainerSpec
    context: SandboxContext
    isolation_layer_ref: str = Field(min_length=1, max_length=180)
    container_status: Literal["architecture_only"] = "architecture_only"
    runtime_created: Literal[False] = False
    executable: Literal[False] = False


class SandboxArchitectureV1(BaseModel):
    architecture_key: str = Field(min_length=1, max_length=180)
    architecture_version: str = Field(min_length=1, max_length=40)
    stage: Literal["c10a_architecture_only"] = "c10a_architecture_only"
    runtime_boundary: SandboxRuntimeBoundary
    isolation_layer: ExecutionIsolationLayer
    module_execution_container: ModuleExecutionContainer
    contract_interface: SandboxContractInterface
    upstream_relationship: Literal[
        "C09 Execution Provider supplies execution contracts but does not execute."
    ] = "C09 Execution Provider supplies execution contracts but does not execute."
    downstream_relationship: Literal[
        "future C15 external provider remains disconnected in C10A."
    ] = "future C15 external provider remains disconnected in C10A."
    wait_policy: Literal["wait_before_c10b"] = "wait_before_c10b"

