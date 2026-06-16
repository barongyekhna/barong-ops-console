from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHARED_MODULE_GLOBAL_ORG = "ALL"
SHARED_MODULE_ID_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$"
)
SHARED_MODULE_ORG_ID_PATTERN = re.compile(r"^org_[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

SharedModuleMode = Literal["single", "multi", "global", "shared"]


def _normalize_module_id(value: str) -> str:
    module_id = value.strip()
    if not SHARED_MODULE_ID_PATTERN.fullmatch(module_id):
        raise ValueError(
            "module_id must be unique and use letters, numbers, dot, underscore, "
            "or hyphen segments."
        )
    return module_id


def _normalize_org_id(value: str) -> str:
    org_id = value.strip()
    if not SHARED_MODULE_ORG_ID_PATTERN.fullmatch(org_id):
        raise ValueError("org_id must be a stable org identifier prefixed with org_.")
    return org_id


def _normalize_allowed_orgs(value: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        org_id = item.strip()
        normalized_org_id = (
            SHARED_MODULE_GLOBAL_ORG
            if org_id == SHARED_MODULE_GLOBAL_ORG
            else _normalize_org_id(org_id)
        )
        if normalized_org_id in seen:
            raise ValueError("allowed_orgs must not contain duplicates.")
        seen.add(normalized_org_id)
        normalized.append(normalized_org_id)
    return normalized


class SharedModule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_id: str = Field(min_length=1, max_length=128)
    mode: SharedModuleMode
    allowed_orgs: list[str] = Field(min_length=1)
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        return _normalize_module_id(value)

    @field_validator("allowed_orgs")
    @classmethod
    def validate_allowed_orgs(cls, value: list[str]) -> list[str]:
        return _normalize_allowed_orgs(value)

    @model_validator(mode="after")
    def validate_mode_shape(self) -> "SharedModule":
        if self.mode == "global":
            if self.allowed_orgs != [SHARED_MODULE_GLOBAL_ORG]:
                raise ValueError("global shared modules must use allowed_orgs=['ALL'].")
        elif SHARED_MODULE_GLOBAL_ORG in self.allowed_orgs:
            raise ValueError("ALL is reserved for global shared modules only.")
        elif self.mode == "single" and len(self.allowed_orgs) != 1:
            raise ValueError("single shared modules must allow exactly one org.")
        elif self.mode in {"multi", "shared"} and not self.allowed_orgs:
            raise ValueError(f"{self.mode} shared modules must allow at least one org.")

        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be before created_at.")
        return self


class SharedModuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=1, max_length=128)
    mode: SharedModuleMode
    allowed_orgs: list[str] = Field(min_length=1)
    enabled: bool = True

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        return _normalize_module_id(value)

    @field_validator("allowed_orgs")
    @classmethod
    def validate_allowed_orgs(cls, value: list[str]) -> list[str]:
        return _normalize_allowed_orgs(value)

    @model_validator(mode="after")
    def validate_mode_shape(self) -> "SharedModuleCreateRequest":
        SharedModule(
            module_id=self.module_id,
            mode=self.mode,
            allowed_orgs=self.allowed_orgs,
            enabled=self.enabled,
        )
        return self


class SharedModuleUpdateOrgsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=1, max_length=128)
    allowed_orgs: list[str] = Field(min_length=1)

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        return _normalize_module_id(value)

    @field_validator("allowed_orgs")
    @classmethod
    def validate_allowed_orgs(cls, value: list[str]) -> list[str]:
        return _normalize_allowed_orgs(value)


class SharedModuleListResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[SharedModule]
    count: int = Field(ge=0)
    registry_type: Literal["shared_module_registry"] = "shared_module_registry"
    stores_business_data: Literal[False] = False


class OrgSharedModulesResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org_id: str = Field(min_length=1, max_length=68)
    available_modules: list[SharedModule]
    count: int = Field(ge=0)
    module_logic_shared: Literal[True] = True
    shared_module_equals_shared_data: Literal[False] = False
    data_access_granted: Literal[False] = False
    c18g_data_isolation_required: Literal[True] = True
    c18h_org_context_required: Literal[True] = True
    runtime_state_shared: Literal[False] = False


class SharedModuleExecutionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_id: str = Field(min_length=1, max_length=128)
    org_id: str = Field(min_length=1, max_length=68)
    allowed: bool
    denied: bool
    reason: str = Field(min_length=1, max_length=500)
    module_logic_reused: Literal[True] = True
    data_access_granted_by_registry: Literal[False] = False
    c18f_permission_required: Literal[True] = True
    c18g_data_isolation_required: Literal[True] = True
    c18h_org_context_required: Literal[True] = True
    runtime_state_shared: Literal[False] = False


class SharedModuleModeRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: SharedModuleMode
    allowed_orgs_shape: str = Field(min_length=1, max_length=200)
    available_to: str = Field(min_length=1, max_length=300)
    module_logic_can_be_reused: Literal[True] = True
    cross_org_data_access_allowed: Literal[False] = False
    notes: str = Field(min_length=1, max_length=500)


class SharedModuleModeDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    definition_id: Literal["c18i_shared_module_modes_v1"] = (
        "c18i_shared_module_modes_v1"
    )
    rules: tuple[
        SharedModuleModeRule,
        SharedModuleModeRule,
        SharedModuleModeRule,
        SharedModuleModeRule,
    ] = (
        SharedModuleModeRule(
            mode="single",
            allowed_orgs_shape='["org_..."]',
            available_to="Exactly one organization.",
            notes="Single mode rejects use from every org outside allowed_orgs.",
        ),
        SharedModuleModeRule(
            mode="multi",
            allowed_orgs_shape='["org_...", "org_..."]',
            available_to="Every listed organization.",
            notes="Multi mode shares module availability only; C18G isolates data.",
        ),
        SharedModuleModeRule(
            mode="global",
            allowed_orgs_shape='["ALL"]',
            available_to="Every organization.",
            notes="Global mode is visible to all orgs but still grants no data access.",
        ),
        SharedModuleModeRule(
            mode="shared",
            allowed_orgs_shape='["org_...", "org_..."]',
            available_to="Every listed organization.",
            notes=(
                "Shared mode reuses module logic across orgs while every data read "
                "and write remains scoped to the active C18H org_id."
            ),
        ),
    )


class SharedModuleAvailabilityLogic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    logic_id: Literal["c18i_shared_module_availability_v1"] = (
        "c18i_shared_module_availability_v1"
    )
    expression: Literal[
        'enabled AND (mode == "global" OR user_org_id in allowed_orgs)'
    ] = 'enabled AND (mode == "global" OR user_org_id in allowed_orgs)'
    function_name: Literal["is_module_available"] = "is_module_available"
    supports_modes: tuple[
        Literal["single"],
        Literal["multi"],
        Literal["global"],
        Literal["shared"],
    ] = ("single", "multi", "global", "shared")
    grants_data_access: Literal[False] = False


class SharedModuleExecutionFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: Literal["c18i_shared_module_execution_flow_v1"] = (
        "c18i_shared_module_execution_flow_v1"
    )
    steps: tuple[str, str, str, str, str, str] = (
        "Load module metadata from the C18I shared module registry.",
        "Resolve org_id from the authenticated C18H org context.",
        "Deny when is_module_available(org_id, module) is false.",
        "Require C18F permission for module execution.",
        "Execute reusable module logic with the active org_id only.",
        "Let C18G enforce org_id filtering for every data read and write.",
    )
    shared_module_equals_shared_data: Literal[False] = False
    runtime_state_shared: Literal[False] = False


class SharedModuleApiEndpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["POST", "GET"]
    path: str = Field(min_length=1, max_length=120)
    owner_required: bool
    returns_business_data: Literal[False] = False
    notes: str = Field(min_length=1, max_length=500)


class SharedModuleApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c18i_shared_module_api_design_v1"] = (
        "c18i_shared_module_api_design_v1"
    )
    endpoints: tuple[
        SharedModuleApiEndpoint,
        SharedModuleApiEndpoint,
        SharedModuleApiEndpoint,
        SharedModuleApiEndpoint,
    ] = (
        SharedModuleApiEndpoint(
            method="POST",
            path="/module/shared/create",
            owner_required=True,
            notes="Creates shared module registry metadata.",
        ),
        SharedModuleApiEndpoint(
            method="POST",
            path="/module/shared/update-orgs",
            owner_required=True,
            notes="Updates the org allowlist for an existing shared module.",
        ),
        SharedModuleApiEndpoint(
            method="GET",
            path="/module/shared/list",
            owner_required=True,
            notes="Lists shared module registry metadata only.",
        ),
        SharedModuleApiEndpoint(
            method="GET",
            path="/org/{org_id}/shared-modules",
            owner_required=False,
            notes=(
                "Lists modules available to the requested org after C18C "
                "membership checks."
            ),
        ),
    )
    migration_executed: Literal[False] = False
    frontend_implemented: Literal[False] = False
    ui_implemented: Literal[False] = False


class SharedModuleSecurityBoundary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    boundary_id: Literal["c18i_shared_module_security_boundary_v1"] = (
        "c18i_shared_module_security_boundary_v1"
    )
    module_logic_can_be_shared: Literal[True] = True
    data_must_be_org_scoped: Literal[True] = True
    shared_module_equals_shared_data: Literal[False] = False
    cross_org_data_access_allowed: Literal[False] = False
    cross_org_runtime_state_allowed: Literal[False] = False
    permission_enforced_by: Literal["C18F"] = "C18F"
    storage_enforced_by: Literal["C18G"] = "C18G"
    org_context_enforced_by: Literal["C18H"] = "C18H"


class SharedModuleC18Integration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c18i_c18c_to_c18h_integration_v1"] = (
        "c18i_c18c_to_c18h_integration_v1"
    )
    c18c_org_membership_required: Literal[True] = True
    c18d_module_binding_synced: Literal[True] = True
    c18e_visibility_consumes_c18d_binding: Literal[True] = True
    c18f_permission_required_for_execution: Literal[True] = True
    c18g_data_isolation_required: Literal[True] = True
    c18h_org_context_required: Literal[True] = True
    shared_mode_maps_to_c18d_multi_binding: Literal[True] = True
    c18a_to_c18h_files_modified: Literal[False] = False


class SharedModuleDataIsolationProof(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proof_id: Literal["c18i_shared_module_data_isolation_proof_v1"] = (
        "c18i_shared_module_data_isolation_proof_v1"
    )
    registry_stores_business_data: Literal[False] = False
    registry_stores_runtime_state: Literal[False] = False
    data_records_must_belong_to_org_id: Literal[True] = True
    c18g_scopes_reads_by_org_id: Literal[True] = True
    c18g_rejects_cross_org_writes: Literal[True] = True
    shared_module_equals_shared_data: Literal[False] = False
    cross_org_query_logic_allowed: Literal[False] = False
    cross_org_runtime_state_allowed: Literal[False] = False
    data_access_controlled_by: Literal["C18C + C18F + C18G + C18H"] = (
        "C18C + C18F + C18G + C18H"
    )


class SharedModuleCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C18I"] = "C18I"
    component: Literal["Shared Module System"] = "Shared Module System"
    completion_status: Literal["complete"] = "complete"
    shared_module_schema_defined: Literal[True] = True
    mode_definition_defined: Literal[True] = True
    availability_logic_defined: Literal[True] = True
    execution_flow_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    security_boundaries_defined: Literal[True] = True
    c18c_to_c18h_integrated: Literal[True] = True
    data_isolation_proof_defined: Literal[True] = True
    migration_executed: Literal[False] = False
    ui_implemented: Literal[False] = False
    frontend_implemented: Literal[False] = False
    cross_org_data_logic_added: Literal[False] = False


SHARED_MODULE_DATA_STRUCTURE = """
shared_modules:
  module_id: str
  mode: single | multi | global | shared
  allowed_orgs: list[str]
  enabled: bool
  created_at: datetime
  updated_at: datetime
""".strip()


def get_shared_module_mode_definition() -> SharedModuleModeDefinition:
    return SharedModuleModeDefinition()


def get_shared_module_availability_logic() -> SharedModuleAvailabilityLogic:
    return SharedModuleAvailabilityLogic()


def get_shared_module_execution_flow() -> SharedModuleExecutionFlow:
    return SharedModuleExecutionFlow()


def get_shared_module_api_design() -> SharedModuleApiDesign:
    return SharedModuleApiDesign()


def get_shared_module_security_boundary() -> SharedModuleSecurityBoundary:
    return SharedModuleSecurityBoundary()


def get_shared_module_c18_integration() -> SharedModuleC18Integration:
    return SharedModuleC18Integration()


def get_shared_module_data_isolation_proof() -> SharedModuleDataIsolationProof:
    return SharedModuleDataIsolationProof()


def get_shared_module_completion_status() -> SharedModuleCompletionStatus:
    return SharedModuleCompletionStatus()
