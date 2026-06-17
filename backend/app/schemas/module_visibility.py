from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .module_binding import ModuleBindingMode


class VisibleModule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_id: str = Field(min_length=1, max_length=128)
    module_name: str = Field(min_length=1, max_length=120)
    mode: ModuleBindingMode


class ModuleVisibilityResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)
    org_id: str = Field(min_length=1, max_length=68)
    visible_modules: list[VisibleModule]


class ModuleVisibilityAlgorithm(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm_id: Literal["c18e_module_visibility_algorithm_v1"] = (
        "c18e_module_visibility_algorithm_v1"
    )
    expression: Literal[
        'module.enabled == true AND (module.mode == "global" OR user.org_id in module.bound_orgs)'
    ] = (
        'module.enabled == true AND (module.mode == "global" OR user.org_id in module.bound_orgs)'
    )
    steps: tuple[str, str, str, str, str] = (
        "Read user active org memberships from C18C.",
        "Resolve the active org context for the current request.",
        "Read enabled module bindings from C18D.",
        'Include global modules and modules bound to the active org_id.',
        "Return visible_modules for UI rendering only.",
    )
    supports_single_mode: Literal[True] = True
    supports_multi_mode: Literal[True] = True
    supports_global_mode: Literal[True] = True
    uses_c18c_org_membership: Literal[True] = True
    uses_c18d_module_binding: Literal[True] = True
    module_visibility_only: Literal[True] = True
    grants_data_access: Literal[False] = False


class ModuleVisibilityApiEndpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["GET"] = "GET"
    path: Literal["/org/{org_id}/visible-modules"] = (
        "/org/{org_id}/visible-modules"
    )
    requires_authenticated_user: Literal[True] = True
    requires_active_c18c_membership: Literal[True] = True
    reads_c18d_module_bindings: Literal[True] = True
    returns_data_records: Literal[False] = False
    notes: str = (
        "Returns the current user's UI-visible modules for the active org context."
    )


class ModuleVisibilityApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c18e_module_visibility_api_design_v1"] = (
        "c18e_module_visibility_api_design_v1"
    )
    endpoint: ModuleVisibilityApiEndpoint = Field(
        default_factory=ModuleVisibilityApiEndpoint
    )
    response_shape: Literal[
        "{ user_id: string, org_id: string, visible_modules: VisibleModule[] }"
    ] = "{ user_id: string, org_id: string, visible_modules: VisibleModule[] }"
    ui_implemented: Literal[False] = False
    permission_system_implemented: Literal[False] = False
    migration_executed: Literal[True] = True


class ModuleVisibilityDataFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: Literal["c18e_user_org_modules_flow_v1"] = (
        "c18e_user_org_modules_flow_v1"
    )
    sequence: tuple[str, str, str, str] = (
        "user_id -> C18C active org memberships",
        "active org switch/request path -> org_id",
        "org_id -> C18D enabled module bindings",
        "C18E filter -> visible_modules for frontend rendering",
    )
    org_switch_changes_visible_modules: Literal[True] = True
    frontend_must_not_query_module_registry_directly: Literal[True] = True


class ModuleVisibilityFrontendRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c18e_frontend_filtering_rules_v1"] = (
        "c18e_frontend_filtering_rules_v1"
    )
    render_only_visible_modules: Literal[True] = True
    direct_module_registry_calls_allowed: Literal[False] = False
    bypass_org_filter_allowed: Literal[False] = False
    org_switch_must_refetch_visible_modules: Literal[True] = True
    frontend_grants_data_access: Literal[False] = False


class ModuleVisibilitySecurityBoundary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    boundary_id: Literal["c18e_security_boundary_v1"] = "c18e_security_boundary_v1"
    visible_modules_equals_data_access_permission: Literal[False] = False
    c18e_decides_data_access: Literal[False] = False
    data_access_controlled_by: Literal["C18C + C17"] = "C18C + C17"
    c18c_org_filter_still_required: Literal[True] = True
    c17_audit_boundary_still_required: Literal[True] = True
    cross_org_data_access_allowed: Literal[False] = False


class ModuleVisibilityCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C18E"] = "C18E"
    component: Literal["Org-Specific Module Visibility System"] = (
        "Org-Specific Module Visibility System"
    )
    completion_status: Literal["complete"] = "complete"
    algorithm_defined: Literal[True] = True
    get_visible_modules_implemented: Literal[True] = True
    c18c_integrated: Literal[True] = True
    c18d_integrated: Literal[True] = True
    c17_audit_hook_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    frontend_rules_defined: Literal[True] = True
    migration_executed: Literal[True] = True
    ui_implemented: Literal[False] = False
    permission_system_implemented: Literal[False] = False
    data_access_logic_added: Literal[False] = False


def get_module_visibility_algorithm() -> ModuleVisibilityAlgorithm:
    return ModuleVisibilityAlgorithm()


def get_module_visibility_api_design() -> ModuleVisibilityApiDesign:
    return ModuleVisibilityApiDesign()


def get_module_visibility_data_flow() -> ModuleVisibilityDataFlow:
    return ModuleVisibilityDataFlow()


def get_module_visibility_frontend_rules() -> ModuleVisibilityFrontendRules:
    return ModuleVisibilityFrontendRules()


def get_module_visibility_security_boundary() -> ModuleVisibilitySecurityBoundary:
    return ModuleVisibilitySecurityBoundary()


def get_module_visibility_completion_status() -> ModuleVisibilityCompletionStatus:
    return ModuleVisibilityCompletionStatus()
