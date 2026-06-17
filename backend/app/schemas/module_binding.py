from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GLOBAL_MODULE_BOUND_ORG = "ALL"
MODULE_BINDING_ID_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$"
)
MODULE_BINDING_ORG_ID_PATTERN = re.compile(r"^org_[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

ModuleBindingMode = Literal["single", "multi", "global"]
ModuleBindingPermissionRole = Literal["owner", "org_admin", "member"]


def _normalize_module_id(value: str) -> str:
    module_id = value.strip()
    if not MODULE_BINDING_ID_PATTERN.fullmatch(module_id):
        raise ValueError(
            "module_id must be unique and use letters, numbers, dot, underscore, "
            "or hyphen segments."
        )
    return module_id


def _normalize_org_id(value: str) -> str:
    org_id = value.strip()
    if not MODULE_BINDING_ORG_ID_PATTERN.fullmatch(org_id):
        raise ValueError("org_id must be a stable org identifier prefixed with org_.")
    return org_id


class ModuleBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_id: str = Field(min_length=1, max_length=128)
    bound_orgs: list[str] = Field(min_length=1)
    mode: ModuleBindingMode
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        return _normalize_module_id(value)

    @field_validator("bound_orgs")
    @classmethod
    def validate_bound_orgs(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            org_id = item.strip()
            if org_id == GLOBAL_MODULE_BOUND_ORG:
                normalized_org_id = GLOBAL_MODULE_BOUND_ORG
            else:
                normalized_org_id = _normalize_org_id(org_id)
            if normalized_org_id in seen:
                raise ValueError("bound_orgs must not contain duplicates.")
            seen.add(normalized_org_id)
            normalized.append(normalized_org_id)
        return normalized

    @model_validator(mode="after")
    def validate_mode_shape(self) -> "ModuleBinding":
        if self.mode == "global":
            if self.bound_orgs != [GLOBAL_MODULE_BOUND_ORG]:
                raise ValueError("global module bindings must use bound_orgs=['ALL'].")
        elif GLOBAL_MODULE_BOUND_ORG in self.bound_orgs:
            raise ValueError("ALL is reserved for global module bindings only.")
        elif self.mode == "single" and len(self.bound_orgs) != 1:
            raise ValueError("single module bindings must bind exactly one org.")
        elif self.mode == "multi" and not self.bound_orgs:
            raise ValueError("multi module bindings must bind at least one org.")

        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be before created_at.")
        return self


class ModuleBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=1, max_length=128)
    org_id: str = Field(min_length=1, max_length=68)
    mode: ModuleBindingMode

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        return _normalize_module_id(value)

    @field_validator("org_id")
    @classmethod
    def validate_org_id(cls, value: str) -> str:
        return _normalize_org_id(value)


class OrgVisibleModulesResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org_id: str = Field(min_length=1, max_length=68)
    visible_modules: list[str]
    bindings: list[ModuleBinding]
    count: int = Field(ge=0)
    module_visibility_only: Literal[True] = True
    data_access_granted: Literal[False] = False
    c18c_org_id_isolation_required: Literal[True] = True


class ModuleBindingDataStructureDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c18d_module_binding_data_structure_v1"] = (
        "c18d_module_binding_data_structure_v1"
    )
    logical_store: Literal["module_bindings"] = "module_bindings"
    primary_key: Literal["id"] = "id"
    fields: tuple[
        Literal["id"],
        Literal["org_id"],
        Literal["module_id"],
        Literal["status"],
        Literal["created_at"],
        Literal["updated_at"],
    ] = (
        "id",
        "org_id",
        "module_id",
        "status",
        "created_at",
        "updated_at",
    )
    module_id_unique: Literal[False] = False
    org_id_module_id_pair_is_unique: Literal[True] = True
    bound_orgs_type: Literal["derived_from_rows"] = "derived_from_rows"
    allowed_modes: tuple[
        Literal["single"],
        Literal["multi"],
        Literal["global"],
    ] = ("single", "multi", "global")
    global_bound_org_sentinel: Literal["ALL"] = GLOBAL_MODULE_BOUND_ORG
    runtime_storage: Literal["db_backed_repository"] = "db_backed_repository"
    migration_executed: Literal[True] = True
    stores_business_data: Literal[False] = False
    grants_data_access: Literal[False] = False


class ModuleBindingModeRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: ModuleBindingMode
    bound_orgs_shape: str = Field(min_length=1, max_length=200)
    visible_to: str = Field(min_length=1, max_length=300)
    cross_org_data_access_allowed: Literal[False] = False
    notes: str = Field(min_length=1, max_length=500)


class ModuleBindingModeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c18d_single_multi_global_modes_v1"] = (
        "c18d_single_multi_global_modes_v1"
    )
    rules: tuple[
        ModuleBindingModeRule,
        ModuleBindingModeRule,
        ModuleBindingModeRule,
    ] = (
        ModuleBindingModeRule(
            mode="single",
            bound_orgs_shape='["org_..."]',
            visible_to="Exactly one organization.",
            notes="Single mode does not allow another org to see the module.",
        ),
        ModuleBindingModeRule(
            mode="multi",
            bound_orgs_shape='["org_...", "org_..."]',
            visible_to="Every listed organization.",
            notes="Multi mode shares visibility only; C18C keeps data isolated.",
        ),
        ModuleBindingModeRule(
            mode="global",
            bound_orgs_shape='["ALL"]',
            visible_to="Every organization.",
            notes="Global mode makes the module visible to all orgs.",
        ),
    )


class ModuleVisibilityAlgorithm(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm_id: Literal["c18d_module_visibility_algorithm_v1"] = (
        "c18d_module_visibility_algorithm_v1"
    )
    expression: Literal[
        'enabled AND (mode == "global" OR user_org_id in bound_orgs)'
    ] = 'enabled AND (mode == "global" OR user_org_id in bound_orgs)'
    flow: tuple[str, str, str, str] = (
        "Read user_org_id from the active C18C organization context.",
        "Read enabled module bindings.",
        'Include bindings where mode == "global" or user_org_id is in bound_orgs.',
        "Return visible module_id values for frontend module display only.",
    )
    module_visibility_only: Literal[True] = True
    grants_data_access: Literal[False] = False
    cross_org_query_logic_allowed: Literal[False] = False


class ModuleBindingApiEndpointDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["POST", "GET"]
    path: str = Field(min_length=1, max_length=120)
    allowed_roles: tuple[ModuleBindingPermissionRole, ...]
    modifies_binding: bool
    org_membership_required_for_non_owner: bool
    returns_data_records: Literal[False] = False
    notes: str = Field(min_length=1, max_length=500)


class ModuleBindingApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c18d_module_binding_api_design_v1"] = (
        "c18d_module_binding_api_design_v1"
    )
    endpoints: tuple[
        ModuleBindingApiEndpointDesign,
        ModuleBindingApiEndpointDesign,
        ModuleBindingApiEndpointDesign,
    ] = (
        ModuleBindingApiEndpointDesign(
            method="POST",
            path="/module/bind",
            allowed_roles=("owner",),
            modifies_binding=True,
            org_membership_required_for_non_owner=False,
            notes="Owner binds or rebinds module visibility for an org or globally.",
        ),
        ModuleBindingApiEndpointDesign(
            method="GET",
            path="/module/{module_id}/bindings",
            allowed_roles=("owner", "org_admin", "member"),
            modifies_binding=False,
            org_membership_required_for_non_owner=True,
            notes=(
                "Non-owner callers only see bindings for modules visible to one "
                "of their active org memberships."
            ),
        ),
        ModuleBindingApiEndpointDesign(
            method="GET",
            path="/org/{org_id}/modules",
            allowed_roles=("owner", "org_admin", "member"),
            modifies_binding=False,
            org_membership_required_for_non_owner=True,
            notes="Lists visible module_id values for the requested org_id.",
        ),
    )
    ui_implemented: Literal[False] = False
    frontend_implemented: Literal[False] = False
    migration_executed: Literal[True] = True


class ModuleBindingPermissionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c18d_module_binding_permission_model_v1"] = (
        "c18d_module_binding_permission_model_v1"
    )
    owner_can_bind_any_module: Literal[True] = True
    owner_can_unbind_any_module: Literal[True] = True
    org_admin_can_view_modules: Literal[True] = True
    org_admin_can_modify_bindings: Literal[False] = False
    member_can_view_visible_modules: Literal[True] = True
    member_can_modify_bindings: Literal[False] = False
    non_owner_view_requires_active_c18c_membership: Literal[True] = True


class ModuleBindingC18Integration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c18d_c18c_c18e_relationship_v1"] = (
        "c18d_c18c_c18e_relationship_v1"
    )
    c18c_role: str = Field(
        default=(
            "C18C remains authoritative for active organization membership and "
            "org_id data isolation."
        ),
        min_length=1,
        max_length=500,
    )
    c18d_role: str = Field(
        default="C18D controls only which module capabilities are visible to each org.",
        min_length=1,
        max_length=500,
    )
    c18e_role: str = Field(
        default=(
            "C18E may consume the visible_module_list for scoped permission UX or "
            "execution gating, but must not treat visibility as data access."
        ),
        min_length=1,
        max_length=500,
    )
    module_binding_equals_data_sharing: Literal[False] = False
    module_visibility_equals_data_access: Literal[False] = False
    all_data_access_requires_c18c_org_id_filter: Literal[True] = True
    cross_org_data_logic_added: Literal[False] = False


class ModuleBindingCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C18D"] = "C18D"
    component: Literal["Module Organization Binding System"] = (
        "Module Organization Binding System"
    )
    completion_status: Literal["complete"] = "complete"
    module_binding_schema_defined: Literal[True] = True
    data_structure_design_defined: Literal[True] = True
    single_multi_global_model_defined: Literal[True] = True
    visibility_algorithm_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    permission_model_defined: Literal[True] = True
    c18c_c18e_relationship_defined: Literal[True] = True
    migration_executed: Literal[True] = True
    ui_implemented: Literal[False] = False
    frontend_implemented: Literal[False] = False
    cross_org_data_logic_added: Literal[False] = False


MODULE_BINDING_DATA_STRUCTURE = """
module_bindings:
  id: int
  org_id: str
  module_id: str
  status: enabled | disabled
  created_at: datetime
  updated_at: datetime
""".strip()


def get_module_binding_data_structure_design() -> ModuleBindingDataStructureDesign:
    return ModuleBindingDataStructureDesign()


def get_module_binding_mode_model() -> ModuleBindingModeModel:
    return ModuleBindingModeModel()


def get_module_visibility_algorithm() -> ModuleVisibilityAlgorithm:
    return ModuleVisibilityAlgorithm()


def get_module_binding_api_design() -> ModuleBindingApiDesign:
    return ModuleBindingApiDesign()


def get_module_binding_permission_model() -> ModuleBindingPermissionModel:
    return ModuleBindingPermissionModel()


def get_module_binding_c18_integration() -> ModuleBindingC18Integration:
    return ModuleBindingC18Integration()


def get_module_binding_completion_status() -> ModuleBindingCompletionStatus:
    return ModuleBindingCompletionStatus()
