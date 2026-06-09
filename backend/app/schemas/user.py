from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

ManagedUserRole = Literal["viewer", "operator", "reviewer"]


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

    @model_validator(mode="after")
    def strip_username(self) -> "UserCreate":
        self.username = self.username.strip()
        if not self.username:
            raise ValueError("Username must not be empty.")
        return self


class UserUpdate(BaseModel):
    role: ManagedUserRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "UserUpdate":
        if self.role is None and self.is_active is None:
            raise ValueError("At least one user field must be supplied.")
        return self


class PasswordResetRequest(BaseModel):
    new_password: SecretStr = Field(min_length=12, max_length=256)
