from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .external_dependency import ExternalServiceStatus, ExternalTrustLevel


DependencyCapability = Literal["serp", "reasoning", "writing", "embedding"]
DependencyBindingStatus = Literal["active", "restricted", "disabled"]
DependencyBindingValidationSeverity = Literal["info", "warning", "error"]
DependencyGraphEdgeStatus = Literal["valid", "restricted", "blocked"]
DependencyBindingAuditDecision = Literal["allow", "restrict", "block"]


class ModuleServiceBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_key: str = Field(min_length=1, max_length=128)
    service_id: str = Field(min_length=1, max_length=180)
    binding_status: DependencyBindingStatus
    allowed_capabilities: list[DependencyCapability] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=255)
    explicit_binding_required: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True


class ModuleCapabilityBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_key: str = Field(min_length=1, max_length=128)
    allowed_capabilities: list[DependencyCapability] = Field(default_factory=list)
    binding_status: DependencyBindingStatus
    reason: str = Field(min_length=1, max_length=255)
    explicit_binding_required: Literal[True] = True
    no_cross_module_leakage: Literal[True] = True


class ServiceCapabilityMapping(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_id: str = Field(min_length=1, max_length=180)
    capabilities: list[DependencyCapability] = Field(default_factory=list)
    binding_status: DependencyBindingStatus
    reason: str = Field(min_length=1, max_length=255)
    no_endpoint_declared: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True


class DependencyBindingRuleSetResponse(BaseModel):
    module_service_bindings: list[ModuleServiceBinding]
    module_capability_bindings: list[ModuleCapabilityBinding]
    service_capability_mappings: list[ServiceCapabilityMapping]
    count: int = Field(ge=0)
    no_implicit_provider_usage: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True


class DependencyBindingValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: DependencyBindingValidationSeverity
    code: str = Field(min_length=1, max_length=180)
    message: str = Field(min_length=1, max_length=500)
    module_key: str | None = Field(default=None, max_length=128)
    service_id: str | None = Field(default=None, max_length=180)
    capability: DependencyCapability | None = None


class DependencyBindingValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    issues: list[DependencyBindingValidationIssue] = Field(default_factory=list)
    module_service_binding_count: int = Field(ge=0)
    module_capability_binding_count: int = Field(ge=0)
    service_capability_mapping_count: int = Field(ge=0)
    graph_edge_count: int = Field(ge=0)
    no_implicit_provider_usage: Literal[True] = True
    no_cross_module_binding_leakage: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True


class DependencyGraphModuleNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_key: str = Field(min_length=1, max_length=128)
    declared_service_ids: list[str] = Field(default_factory=list)
    allowed_capabilities: list[DependencyCapability] = Field(default_factory=list)
    binding_status: DependencyBindingStatus
    explicit_binding_present: bool


class DependencyGraphCapabilityNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: DependencyCapability
    module_count: int = Field(ge=0)
    service_count: int = Field(ge=0)


class DependencyGraphServiceNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_id: str = Field(min_length=1, max_length=180)
    service_registered: bool
    service_status: ExternalServiceStatus | Literal["missing"]
    trust_level: ExternalTrustLevel
    capabilities: list[DependencyCapability] = Field(default_factory=list)
    binding_status: DependencyBindingStatus


class DependencyGraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    edge_id: str = Field(min_length=1, max_length=180)
    module_key: str = Field(min_length=1, max_length=128)
    capability: DependencyCapability
    service_id: str = Field(min_length=1, max_length=180)
    binding_status: DependencyBindingStatus
    validation_status: DependencyGraphEdgeStatus
    reasons: list[str] = Field(default_factory=list)
    audit_ref: str = Field(min_length=1, max_length=180)
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True


class DependencyGraphSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    graph_id: Literal["c14e_dependency_binding_graph_v1"] = (
        "c14e_dependency_binding_graph_v1"
    )
    modules: list[DependencyGraphModuleNode]
    capabilities: list[DependencyGraphCapabilityNode]
    services: list[DependencyGraphServiceNode]
    edges: list[DependencyGraphEdge]
    validation: DependencyBindingValidationResult
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True


class DependencyGraphResponse(BaseModel):
    graph: DependencyGraphSnapshot


class DependencyBindingAuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(min_length=1, max_length=180)
    module_key: str = Field(min_length=1, max_length=128)
    service_id: str = Field(min_length=1, max_length=180)
    capability: DependencyCapability | None = None
    binding_status: DependencyBindingStatus
    decision: DependencyBindingAuditDecision
    reason: str = Field(min_length=1, max_length=500)
    no_implicit_provider_usage: Literal[True] = True
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True


class DependencyBindingAuditResponse(BaseModel):
    items: list[DependencyBindingAuditEntry]
    count: int = Field(ge=0)
