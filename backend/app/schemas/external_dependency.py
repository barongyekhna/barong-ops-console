from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ExternalServiceType = Literal[
    "ai_api",
    "automation",
    "payment",
    "storage",
    "custom",
    "unknown",
]
ExternalServiceStatus = Literal[
    "active",
    "suspended",
    "quarantined",
    "pending",
]
ExternalTrustLevel = Literal["high", "medium", "low", "untrusted"]
ExternalAccessRecommendation = Literal["allow", "restrict", "quarantine"]
ExternalPolicyDecisionValue = Literal[
    "allow",
    "deny",
    "quarantine",
    "require_approval",
]
ExternalDependencyBindingStatus = Literal[
    "allowed",
    "blocked",
    "quarantined",
    "pending_approval",
    "no_external_dependency",
]


class ExternalService(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_id: str = Field(min_length=1, max_length=180)
    service_type: ExternalServiceType = "unknown"
    status: ExternalServiceStatus = "pending"
    trust_level: ExternalTrustLevel = "untrusted"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalTrustEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_id: str = Field(min_length=1, max_length=180)
    service_type: ExternalServiceType
    status: ExternalServiceStatus
    configured_trust_level: ExternalTrustLevel
    dynamic_trust_level: ExternalTrustLevel
    dynamic_trust_score: int = Field(ge=0, le=100)
    access_recommendation: ExternalAccessRecommendation
    factors: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=255)


class ExternalDependencyPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1, max_length=500)
    module: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=180)
    service_id: str | None = Field(default=None, max_length=180)
    service_type: ExternalServiceType | None = None
    min_trust_level: ExternalTrustLevel = "medium"
    decision: Literal["allow", "deny", "require_approval"] = "deny"
    requires_c12_approval: bool = False
    enabled: bool = True

    @model_validator(mode="after")
    def validate_selector(self) -> "ExternalDependencyPolicy":
        if self.service_id is None and self.service_type is None:
            raise ValueError(
                "External dependency policy must select service_id or service_type."
            )
        return self


class PolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=180)
    context: dict[str, Any] = Field(default_factory=dict)
    decision: ExternalPolicyDecisionValue
    reason: str = Field(min_length=1, max_length=255)
    dynamic_trust_score: int = Field(ge=0, le=100)
    dynamic_trust_level: ExternalTrustLevel
    access_recommendation: ExternalAccessRecommendation
    default_deny_applied: bool = True
    explicit_policy_required: Literal[True] = True
    explicit_policy_matched: bool = False
    c12_approval_required: bool = False
    registration_required: bool = False
    quarantine_required: bool = False
    no_runtime_execution: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_secret_material_exposed: Literal[True] = True


class ExternalServiceRegistrationProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=180)
    service_id: str = Field(min_length=1, max_length=180)
    service_type: ExternalServiceType = "unknown"
    status: Literal["quarantined", "pending"] = "quarantined"
    source_module: str = Field(min_length=1, max_length=128)
    source_adapter: str = Field(min_length=1, max_length=180)
    source_action: str | None = Field(default=None, max_length=180)
    detection_context: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=255)
    ui_surface: Literal["c14_external_provider_control_panel"] = (
        "c14_external_provider_control_panel"
    )
    approval_status: Literal["waiting_review", "waiting_c12"] = "waiting_review"
    no_direct_execution_allowed: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_secret_material_exposed: Literal[True] = True


class ExternalDependencyBindingRead(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    adapter: str = Field(min_length=1, max_length=180)
    action: str | None = Field(default=None, max_length=180)
    service_id: str = Field(min_length=1, max_length=180)
    dependency_intent_declared: bool
    service_registered: bool
    service_status: ExternalServiceStatus | Literal["missing"]
    trust_level: ExternalTrustLevel
    binding_status: ExternalDependencyBindingStatus
    policy_decision: PolicyDecision
    requires_c12_approval: bool = False
    execution_gate_enforced: Literal[True] = True
    no_runtime_execution: Literal[True] = True


class ExternalDependencyGateSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["c14d_external_dependency_gate"] = (
        "c14d_external_dependency_gate"
    )
    evaluated_at: datetime
    service_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=180)
    decision: PolicyDecision
    registration_proposal: ExternalServiceRegistrationProposal | None = None
    execution_chain_allowed: bool
    c09_execution_allowed: bool
    c10_sandbox_allowed: bool


class ExternalServiceRegistryResponse(BaseModel):
    items: list[ExternalService]
    count: int = Field(ge=0)


class ExternalServiceProposalListResponse(BaseModel):
    items: list[ExternalServiceRegistrationProposal]
    count: int = Field(ge=0)


class ExternalDependencyBindingListResponse(BaseModel):
    items: list[ExternalDependencyBindingRead]
    count: int = Field(ge=0)
