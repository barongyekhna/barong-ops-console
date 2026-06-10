from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from ..core.roles import validate_assignable_user_role

ManagedUserRole = str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=12, max_length=256)
    role: ManagedUserRole
    is_active: bool = True

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        return validate_assignable_user_role(value)

    @model_validator(mode="after")
    def strip_username(self) -> "UserCreate":
        self.username = self.username.strip()
        if not self.username:
            raise ValueError("Username must not be empty.")
        return self


class UserUpdate(BaseModel):
    role: ManagedUserRole | None = None
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_assignable_user_role(value)

    @model_validator(mode="after")
    def require_change(self) -> "UserUpdate":
        if self.role is None and self.is_active is None:
            raise ValueError("At least one user field must be supplied.")
        return self


class PasswordResetRequest(BaseModel):
    new_password: SecretStr = Field(min_length=12, max_length=256)


class UserRoleResponse(BaseModel):
    name: str
    label: str
    description: str
    human_or_agent: str
    c04_status: str
    assignable: bool


class UserRolesResponse(BaseModel):
    assignable_roles: list[UserRoleResponse]
    standard_roles: list[UserRoleResponse]
