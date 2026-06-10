from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.permissions import (
    validate_permission_key,
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
    user_id: int = Field(gt=0)
    permission_key: str
    scope_type: str = "global"
    scope_key: str = "*"
    granted_by_user_id: int | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=4000)
    expires_at: datetime | None = None

    @field_validator("permission_key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return validate_permission_key(value)

    @model_validator(mode="after")
    def validate_scope_fields(self) -> "PermissionAssignmentCreate":
        self.scope_type, self.scope_key = validate_scope(
            self.scope_type,
            self.scope_key,
        )
        return self


class PermissionAssignmentUpdate(BaseModel):
    is_enabled: bool | None = None
    reason: str | None = Field(default=None, max_length=4000)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def require_change(self) -> "PermissionAssignmentUpdate":
        if (
            self.is_enabled is None
            and self.reason is None
            and self.expires_at is None
        ):
            raise ValueError("At least one assignment field must be supplied.")
        return self


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
