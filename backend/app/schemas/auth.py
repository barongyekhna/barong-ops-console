from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .permission import CurrentUserPermissionsRead


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=256)


class AuthenticatedUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    organization_id: str | None
    must_change_password: bool
    is_active: bool
    last_login_at: datetime | None


class AuthenticatedUserWithPermissions(AuthenticatedUser):
    permissions: CurrentUserPermissionsRead


class AuthContextResponse(BaseModel):
    user_id: int
    org_id: str | None
    role: str | None
    module_scope: list[str] = Field(default_factory=list)
    context_available: bool
    resolution_source: str | None


class LoginResponse(BaseModel):
    user: AuthenticatedUser
    session_token: str
    auth_complete: bool = True
    require_password_change: bool = False
    message: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: SecretStr = Field(min_length=1, max_length=256)
    new_password: SecretStr = Field(min_length=12, max_length=256)


class ChangePasswordResponse(BaseModel):
    user: AuthenticatedUser
    message: str


class LogoutResponse(BaseModel):
    message: str
