from functools import lru_cache
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EXAMPLE_DATABASE_URL = (
    "postgresql+psycopg://"
    "barong_console_example:barong_console_example"
    "@db:5432/barong_console_example"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "barong-ops-console-backend"
    app_env: str = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "ENV", "app_env", "env"),
    )
    app_debug: bool = False
    app_docs_enabled: bool | None = None
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
    auth_session_cookie_samesite: Literal["strict", "lax", "none"] = "lax"
    auth_session_cookie_secure: bool | None = None
    auth_session_cookie_domain: str | None = None
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
    webhook_replay_nonce_ttl_seconds: int = Field(default=900, gt=0, le=3600)
    ops_alert_webhook_url: str | None = None
    ops_alert_webhook_timeout_seconds: int = Field(default=5, gt=0, le=30)
    control_plane_stealth_mode: bool | None = None
    login_ip_rate_limit_attempts: int = Field(default=20, gt=0, le=1000)
    login_user_rate_limit_attempts: int = Field(default=10, gt=0, le=1000)
    login_endpoint_rate_limit_attempts: int = Field(default=200, gt=0, le=10000)
    login_ip_rate_limit_window_seconds: int = Field(default=900, gt=0, le=86400)
    login_failed_attempt_lockout_threshold: int = Field(default=5, gt=0, le=100)
    login_failed_attempt_base_delay_seconds: int = Field(
        default=2,
        ge=0,
        le=300,
    )
    login_failed_attempt_max_delay_seconds: int = Field(
        default=60,
        ge=0,
        le=3600,
    )
    login_account_lockout_minutes: int = Field(default=15, gt=0, le=1440)

    @field_validator("app_env", mode="before")
    @classmethod
    def default_empty_app_env(cls, value: Any) -> Any:
        if value is None or value == "":
            return "development"
        if isinstance(value, str):
            return value.strip()
        return value

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
            "auth_session_cookie_samesite": "lax",
        }
        return defaults[info.field_name]

    @field_validator("auth_session_cookie_secure", mode="before")
    @classmethod
    def default_empty_session_secure(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator(
        "app_docs_enabled",
        "control_plane_stealth_mode",
        "ops_alert_webhook_url",
        "auth_session_cookie_domain",
        mode="before",
    )
    @classmethod
    def default_empty_optional_values(cls, value: Any) -> Any:
        if value == "":
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("auth_session_expire_minutes", mode="before")
    @classmethod
    def default_empty_session_expiry(cls, value: Any) -> Any:
        if value == "":
            return 60
        return value

    @field_validator(
        "webhook_replay_nonce_ttl_seconds",
        "login_ip_rate_limit_attempts",
        "login_user_rate_limit_attempts",
        "login_endpoint_rate_limit_attempts",
        "login_ip_rate_limit_window_seconds",
        "login_failed_attempt_lockout_threshold",
        "login_failed_attempt_base_delay_seconds",
        "login_failed_attempt_max_delay_seconds",
        "login_account_lockout_minutes",
        "ops_alert_webhook_timeout_seconds",
        mode="before",
    )
    @classmethod
    def default_empty_security_numbers(
        cls,
        value: Any,
        info: ValidationInfo,
    ) -> Any:
        if value != "":
            return value
        defaults = {
            "webhook_replay_nonce_ttl_seconds": 900,
            "login_ip_rate_limit_attempts": 20,
            "login_user_rate_limit_attempts": 10,
            "login_endpoint_rate_limit_attempts": 200,
            "login_ip_rate_limit_window_seconds": 900,
            "login_failed_attempt_lockout_threshold": 5,
            "login_failed_attempt_base_delay_seconds": 2,
            "login_failed_attempt_max_delay_seconds": 60,
            "login_account_lockout_minutes": 15,
            "ops_alert_webhook_timeout_seconds": 5,
        }
        return defaults[info.field_name]


@lru_cache
def get_settings() -> Settings:
    return Settings()
