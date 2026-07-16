from functools import lru_cache
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .release_registry import SYSTEM_RELEASE_VERSION

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
    app_version: str = SYSTEM_RELEASE_VERSION
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
    wp_base_url: str | None = Field(default=None, max_length=2048)
    wp_app_user: str | None = Field(default=None, max_length=255)
    wp_app_password: SecretStr | None = None
    wp_request_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    wp_request_max_attempts: int = Field(default=3, ge=1, le=5)
    webhook_gateway_signing_secret: SecretStr | None = None
    api_key_encryption_secret: SecretStr | None = None
    c19_record_store_url: str | None = Field(default=None, max_length=2048)
    c19_record_store_token: SecretStr | None = Field(
        default=None,
        min_length=32,
    )
    c19_record_store_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    c19_record_event_poll_seconds: float = Field(default=1.0, ge=0.25, le=10.0)
    c19_event_stream_lifetime_seconds: int = Field(default=20, ge=10, le=60)
    c19_rate_limit_window_seconds: int = Field(default=60, ge=10, le=3600)
    c19_write_user_rate_limit_attempts: int = Field(
        default=180,
        ge=10,
        le=10000,
    )
    c19_write_ip_rate_limit_attempts: int = Field(
        default=1800,
        ge=100,
        le=100000,
    )
    c19_stream_user_rate_limit_attempts: int = Field(
        default=30,
        ge=5,
        le=1000,
    )
    c19_stream_ip_rate_limit_attempts: int = Field(
        default=300,
        ge=10,
        le=10000,
    )
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
    db_pool_size: int = Field(default=30, gt=0, le=200)
    db_max_overflow: int = Field(default=70, ge=0, le=500)
    db_pool_recycle_seconds: int = Field(default=1200, gt=0, le=86400)
    db_statement_timeout_ms: int = Field(default=8000, gt=0, le=60000)
    db_idle_in_transaction_session_timeout_ms: int = Field(
        default=10000,
        gt=0,
        le=60000,
    )

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
        "api_key_encryption_secret",
        "c19_record_store_url",
        "c19_record_store_token",
        "wp_base_url",
        "wp_app_user",
        "wp_app_password",
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
        "db_pool_size",
        "db_max_overflow",
        "db_pool_recycle_seconds",
        "db_statement_timeout_ms",
        "db_idle_in_transaction_session_timeout_ms",
        "c19_record_store_timeout_seconds",
        "c19_record_event_poll_seconds",
        "c19_event_stream_lifetime_seconds",
        "c19_rate_limit_window_seconds",
        "c19_write_user_rate_limit_attempts",
        "c19_write_ip_rate_limit_attempts",
        "c19_stream_user_rate_limit_attempts",
        "c19_stream_ip_rate_limit_attempts",
        "wp_request_timeout_seconds",
        "wp_request_max_attempts",
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
            "db_pool_size": 30,
            "db_max_overflow": 70,
            "db_pool_recycle_seconds": 1200,
            "db_statement_timeout_ms": 8000,
            "db_idle_in_transaction_session_timeout_ms": 10000,
            "c19_record_store_timeout_seconds": 5.0,
            "c19_record_event_poll_seconds": 1.0,
            "c19_event_stream_lifetime_seconds": 20,
            "c19_rate_limit_window_seconds": 60,
            "c19_write_user_rate_limit_attempts": 180,
            "c19_write_ip_rate_limit_attempts": 1800,
            "c19_stream_user_rate_limit_attempts": 30,
            "c19_stream_ip_rate_limit_attempts": 300,
            "wp_request_timeout_seconds": 10.0,
            "wp_request_max_attempts": 3,
        }
        return defaults[info.field_name]


@lru_cache
def get_settings() -> Settings:
    return Settings()
