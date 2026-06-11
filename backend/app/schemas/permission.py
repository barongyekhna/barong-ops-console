from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.permissions import (
    validate_scope,
)


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
