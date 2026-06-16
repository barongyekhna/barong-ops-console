from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.permissions import (
    validate_scope,
)


class PermissionAction(StrEnum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"
    ADMIN = "admin"


class PermissionRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Permission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)
    org_id: str = Field(min_length=1, max_length=68)
    module_id: str = Field(min_length=1, max_length=128)
    actions: list[PermissionAction] = Field(min_length=1)
    role: PermissionRole

    @field_validator("user_id", "org_id", "module_id")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Permission identity fields must not be empty.")
        return normalized

    @field_validator("actions")
    @classmethod
    def deduplicate_actions(
        cls,
        actions: list[PermissionAction],
    ) -> list[PermissionAction]:
        seen: set[PermissionAction] = set()
        unique: list[PermissionAction] = []
        for action in actions:
            if action not in seen:
                seen.add(action)
                unique.append(action)
        return unique


class PermissionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)
    org_id: str = Field(min_length=1, max_length=68)
    module_id: str = Field(min_length=1, max_length=128)
    action: PermissionAction
    role: PermissionRole | None = None
    allowed: bool
    denied: bool
    denial_code: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=500)
    owner_override_applied: bool = False
    permission: Permission | None = None
    c18c_org_membership_checked: bool
    c18d_module_binding_checked: bool
    c18e_visibility_grants_permission: Literal[False] = False
    data_access_granted: Literal[False] = False

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "PermissionDecision":
        if self.denied == self.allowed:
            raise ValueError("PermissionDecision denied must be the inverse of allowed.")
        if self.allowed and self.denial_code is not None:
            raise ValueError("Allowed permission decisions must not include denial_code.")
        if self.denied and self.denial_code is None:
            raise ValueError("Denied permission decisions must include denial_code.")
        return self


class PermissionOrgIsolationRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c18f_org_isolation_rules_v1"] = (
        "c18f_org_isolation_rules_v1"
    )
    permission_scope: Literal["org"] = "org"
    rule: Literal["user.org_id != target.org_id -> DENY"] = (
        "user.org_id != target.org_id -> DENY"
    )
    active_c18c_membership_required: Literal[True] = True
    cross_org_permission_inheritance_allowed: Literal[False] = False
    cross_org_module_operation_allowed: Literal[False] = False


class PermissionModuleIsolationRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c18f_module_isolation_rules_v1"] = (
        "c18f_module_isolation_rules_v1"
    )
    c18d_binding_required: Literal[True] = True
    rule_unbound_module: Literal["module not bound to org -> DENY"] = (
        "module not bound to org -> DENY"
    )
    rule_bound_without_role: Literal["module bound but user lacks role -> DENY"] = (
        "module bound but user lacks role -> DENY"
    )
    module_visibility_is_not_execution_permission: Literal[True] = True


class PermissionOwnerOverrideLogic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    logic_id: Literal["c18f_owner_override_v1"] = "c18f_owner_override_v1"
    owner_role_source: Literal["users.role"] = "users.role"
    rule: Literal["if user.role == 'owner': RETURN ALLOW"] = (
        "if user.role == 'owner': RETURN ALLOW"
    )
    owner_can_access_all_orgs: Literal[True] = True
    owner_can_access_all_modules: Literal[True] = True
    owner_can_execute_all_actions: Literal[True] = True
    owner_bypasses_permission_check: Literal[True] = True


class PermissionGranularityModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c18f_permission_granularity_v1"] = (
        "c18f_permission_granularity_v1"
    )
    supported_actions: tuple[
        Literal["read"],
        Literal["write"],
        Literal["delete"],
        Literal["execute"],
        Literal["admin"],
    ] = ("read", "write", "delete", "execute", "admin")
    admin_role_actions: tuple[
        Literal["read"],
        Literal["write"],
        Literal["execute"],
    ] = ("read", "write", "execute")
    member_role_actions: tuple[Literal["read"]] = ("read",)
    k_series_actions: tuple[
        Literal["read"],
        Literal["write"],
        Literal["execute"],
    ] = ("read", "write", "execute")
    c_series_actions: tuple[Literal["admin"]] = ("admin",)
    p_series_actions: tuple[Literal["write"]] = ("write",)


class PermissionApiMiddlewareDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c18f_api_permission_middleware_v1"] = (
        "c18f_api_permission_middleware_v1"
    )
    implementation_path: Literal["backend/app/middleware/permission.py"] = (
        "backend/app/middleware/permission.py"
    )
    intercepts: tuple[
        Literal["api_request"],
        Literal["module_access"],
        Literal["workflow_execution_c15"],
        Literal["ai_execution_c14"],
        Literal["logs_access_c17"],
    ] = (
        "api_request",
        "module_access",
        "workflow_execution_c15",
        "ai_execution_c14",
        "logs_access_c17",
    )
    requires_org_context_for_enforcement: Literal[True] = True
    requires_module_context_for_enforcement: Literal[True] = True
    owner_override_first: Literal[True] = True


class PermissionC18Integration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c18f_c18c_c18d_c18e_integration_v1"] = (
        "c18f_c18c_c18d_c18e_integration_v1"
    )
    c18c_source: Literal["org_memberships"] = "org_memberships"
    c18d_source: Literal["module_bindings"] = "module_bindings"
    c18e_source: Literal["module visibility is advisory only"] = (
        "module visibility is advisory only"
    )
    uses_c18c_org_membership: Literal[True] = True
    uses_c18d_module_binding: Literal[True] = True
    c18e_grants_permission: Literal[False] = False
    modifies_c18a_to_c18e: Literal[False] = False


class PermissionSecurityBoundary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    boundary_id: Literal["c18f_security_boundary_v1"] = "c18f_security_boundary_v1"
    permission_equals_visibility: Literal[False] = False
    permission_equals_data_access: Literal[False] = False
    module_visibility_equals_module_execution_permission: Literal[False] = False
    data_access_controlled_by: Literal["C17"] = "C17"
    c18f_controls: Literal["what action a user may execute in org + module"] = (
        "what action a user may execute in org + module"
    )
    storage_changes_added: Literal[False] = False
    db_migration_executed: Literal[False] = False
    frontend_logic_added: Literal[False] = False


class PermissionIsolationCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C18F"] = "C18F"
    component: Literal["Permission Isolation Layer"] = "Permission Isolation Layer"
    completion_status: Literal["complete"] = "complete"
    permission_data_model_defined: Literal[True] = True
    check_permission_implemented: Literal[True] = True
    org_isolation_rules_defined: Literal[True] = True
    module_isolation_rules_defined: Literal[True] = True
    owner_override_logic_defined: Literal[True] = True
    api_middleware_design_defined: Literal[True] = True
    c18c_c18d_c18e_integrated: Literal[True] = True
    security_boundary_defined: Literal[True] = True
    migration_executed: Literal[False] = False
    ui_implemented: Literal[False] = False
    data_storage_changed: Literal[False] = False


class PermissionRegistryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    permission_key: str
    module_key: str
    category: str
    action: str
    label: str
    description: str | None
    risk_level: str
    menu_policy: str
    is_system: bool
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class UserPermissionAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: int
    permission_key: str
    scope_type: str
    scope_key: str
    granted_by_user_id: int | None
    reason: str | None
    is_enabled: bool
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PermissionAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: int
    permission_key: str
    permission_name: str | None
    description: str | None
    scope_type: str
    scope_id: str
    scope_key: str
    enabled: bool
    is_enabled: bool
    expires_at: datetime | None
    granted_by_user_id: int | None
    created_at: datetime
    updated_at: datetime
    reason: str | None
    risk_level: str | None
    high_risk: bool
    effective: bool


class RoleDefaultPermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    permission_key: str
    scope_type: str
    scope_key: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class PermissionAssignmentCreate(BaseModel):
    user_id: int | None = Field(default=None, gt=0)
    permission_key: str = Field(min_length=1, max_length=255)
    scope_type: str = "global"
    scope_id: str | None = Field(default=None, max_length=255)
    scope_key: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=4000)
    expires_at: datetime | None = None
    confirm_high_risk: bool = False
    confirmation_text: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_scope_fields(self) -> "PermissionAssignmentCreate":
        self.permission_key = self.permission_key.strip()
        if not self.permission_key:
            raise ValueError("Permission key must not be empty.")
        if (
            self.scope_id is not None
            and self.scope_key is not None
            and self.scope_id != self.scope_key
        ):
            raise ValueError("scope_id and scope_key must match when both are supplied.")
        requested_scope_key = self.scope_id or self.scope_key or "*"
        self.scope_type, self.scope_key = validate_scope(
            self.scope_type,
            requested_scope_key,
        )
        self.scope_id = self.scope_key
        return self


class PermissionAssignmentUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    permission_key: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    is_enabled: bool | None = None
    scope_type: str | None = None
    scope_id: str | None = Field(default=None, max_length=255)
    scope_key: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=4000)
    expires_at: datetime | None = None
    confirm_high_risk: bool = False
    confirmation_text: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def require_change(self) -> "PermissionAssignmentUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one assignment field must be supplied.")
        if (
            self.enabled is not None
            and self.is_enabled is not None
            and self.enabled != self.is_enabled
        ):
            raise ValueError("enabled and is_enabled must match when both are supplied.")
        if self.enabled is None and self.is_enabled is not None:
            self.enabled = self.is_enabled
        if self.permission_key is not None:
            self.permission_key = self.permission_key.strip()
        if (
            self.scope_id is not None
            and self.scope_key is not None
            and self.scope_id != self.scope_key
        ):
            raise ValueError("scope_id and scope_key must match when both are supplied.")
        if (
            self.scope_type is not None
            or self.scope_id is not None
            or self.scope_key is not None
        ):
            if self.scope_type is not None and (
                self.scope_id is not None or self.scope_key is not None
            ):
                requested_scope_key = self.scope_id or self.scope_key or "*"
                self.scope_type, self.scope_key = validate_scope(
                    self.scope_type,
                    requested_scope_key,
                )
                self.scope_id = self.scope_key
        return self


class PermissionAssignmentRevokeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=4000)


class PermissionAssignmentListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str
    role: str
    is_owner_full_access: bool
    owner_full_access_note: str | None = None
    assignments: list[PermissionAssignmentRead]


class PermissionAssignmentActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assignment: PermissionAssignmentRead
    operation_id: str


class UserEffectivePermissionScopeRead(BaseModel):
    permission_key: str
    scope_type: str
    scope_key: str
    expires_at: datetime | None


class UserEffectivePermissionsRead(BaseModel):
    user_id: int
    role: str
    is_owner_full_access: bool
    permissions: list[str]
    scoped_permissions: list[UserEffectivePermissionScopeRead]


class EffectivePermissionAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    permission_key: str
    scope_type: str
    scope_key: str


class EffectivePermissionScopeSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scope_type: str
    scope_key: str
    permission_keys: list[str]


class CurrentUserPermissionsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    is_owner_full_access: bool
    permission_keys: list[str]
    assignments: list[EffectivePermissionAssignmentRead]
    scope_summary: list[EffectivePermissionScopeSummaryRead]


class CurrentUserPermissionResponse(BaseModel):
    user_id: int
    role: str
    permissions: CurrentUserPermissionsRead


def get_permission_org_isolation_rules() -> PermissionOrgIsolationRules:
    return PermissionOrgIsolationRules()


def get_permission_module_isolation_rules() -> PermissionModuleIsolationRules:
    return PermissionModuleIsolationRules()


def get_permission_owner_override_logic() -> PermissionOwnerOverrideLogic:
    return PermissionOwnerOverrideLogic()


def get_permission_granularity_model() -> PermissionGranularityModel:
    return PermissionGranularityModel()


def get_permission_api_middleware_design() -> PermissionApiMiddlewareDesign:
    return PermissionApiMiddlewareDesign()


def get_permission_c18_integration() -> PermissionC18Integration:
    return PermissionC18Integration()


def get_permission_security_boundary() -> PermissionSecurityBoundary:
    return PermissionSecurityBoundary()


def get_permission_isolation_completion_status() -> PermissionIsolationCompletionStatus:
    return PermissionIsolationCompletionStatus()
