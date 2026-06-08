from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr


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


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: AuthenticatedUser


class LogoutResponse(BaseModel):
    message: str
