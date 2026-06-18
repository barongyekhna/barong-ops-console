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


class LogoutResponse(BaseModel):
    message: str
