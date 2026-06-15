from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EXAMPLE_DATABASE_URL = (
    "postgresql+psycopg://"
    "barong_console_example:barong_console_example"
    "@db:5432/barong_console_example"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    app_name: str = "barong-ops-console-backend"
    app_env: str = "development"
    app_version: str = "0.1.0"
    database_url: str = EXAMPLE_DATABASE_URL
    auth_session_expire_minutes: int = Field(default=60, gt=0, le=1440)
    auth_session_cookie_name: str = Field(
        default="barong_ops_session",
        min_length=1,
        max_length=128,
    )
    auth_session_cookie_path: str = Field(
        default="/api/backend",
        min_length=1,
        max_length=255,
    )
    auth_session_cookie_samesite: Literal["strict", "lax"] = "strict"
    auth_session_cookie_secure: bool | None = None
    owner_username: str | None = None
    owner_password: SecretStr | None = None
    n8n_test_webhook_url: str = ""
    n8n_test_callback_secret: SecretStr | None = None
    n8n_test_request_timeout_seconds: int = Field(
        default=10,
        gt=0,
        le=60,
    )
    webhook_gateway_signing_secret: SecretStr | None = None
    webhook_gateway_signature_tolerance_seconds: int = Field(
        default=300,
        gt=0,
        le=900,
    )

    @field_validator(
        "auth_session_cookie_name",
        "auth_session_cookie_path",
        "auth_session_cookie_samesite",
        mode="before",
    )
    @classmethod
    def default_empty_session_strings(
        cls,
        value: Any,
        info: ValidationInfo,
    ) -> Any:
        if value != "":
            if (
                info.field_name == "auth_session_cookie_samesite"
                and isinstance(value, str)
            ):
                return value.lower()
            return value
        defaults = {
            "auth_session_cookie_name": "barong_ops_session",
            "auth_session_cookie_path": "/api/backend",
            "auth_session_cookie_samesite": "strict",
        }
        return defaults[info.field_name]

    @field_validator("auth_session_cookie_secure", mode="before")
    @classmethod
    def default_empty_session_secure(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator("auth_session_expire_minutes", mode="before")
    @classmethod
    def default_empty_session_expiry(cls, value: Any) -> Any:
        if value == "":
            return 60
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
