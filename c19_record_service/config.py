"""Environment-owned configuration for the standalone C19 record service."""

from __future__ import annotations

import os
from dataclasses import dataclass


class RecordServiceConfigurationError(RuntimeError):
    """Raised before startup when a required secret or database is missing."""


def _reject_placeholder(name: str, value: str) -> None:
    if "CHANGE-ME" in value.upper():
        raise RecordServiceConfigurationError(
            f"{name} contains a deployment placeholder"
        )


def escape_alembic_url(database_url: str) -> str:
    """Escape ConfigParser interpolation without changing the SQLAlchemy URL."""

    return database_url.replace("%", "%%")


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RecordServiceConfigurationError(f"{name} must be configured")
    return value


def _positive_integer(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RecordServiceConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RecordServiceConfigurationError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class RecordServiceSettings:
    """Configuration isolated from Barong's application settings."""

    database_url: str
    service_token: str
    cursor_signing_secret: str
    cursor_ttl_seconds: int = 86_400
    max_message_chars: int = 10_000

    def __post_init__(self) -> None:
        if not self.database_url.strip():
            raise RecordServiceConfigurationError(
                "C19_RECORD_DATABASE_URL must be configured"
            )
        _reject_placeholder("C19_RECORD_DATABASE_URL", self.database_url)
        if len(self.service_token) < 32:
            raise RecordServiceConfigurationError(
                "C19_RECORD_SERVICE_TOKEN must contain at least 32 characters"
            )
        _reject_placeholder("C19_RECORD_SERVICE_TOKEN", self.service_token)
        if len(self.cursor_signing_secret) < 32:
            raise RecordServiceConfigurationError(
                "C19_RECORD_CURSOR_SIGNING_SECRET must contain at least 32 characters"
            )
        _reject_placeholder(
            "C19_RECORD_CURSOR_SIGNING_SECRET", self.cursor_signing_secret
        )
        if self.cursor_ttl_seconds <= 0:
            raise RecordServiceConfigurationError(
                "C19_RECORD_CURSOR_TTL_SECONDS must be positive"
            )
        if self.max_message_chars <= 0:
            raise RecordServiceConfigurationError(
                "C19_RECORD_MAX_MESSAGE_CHARS must be positive"
            )

    @classmethod
    def from_environment(cls) -> "RecordServiceSettings":
        return cls(
            database_url=_required_environment("C19_RECORD_DATABASE_URL"),
            service_token=_required_environment("C19_RECORD_SERVICE_TOKEN"),
            cursor_signing_secret=_required_environment(
                "C19_RECORD_CURSOR_SIGNING_SECRET"
            ),
            cursor_ttl_seconds=_positive_integer(
                "C19_RECORD_CURSOR_TTL_SECONDS", 86_400
            ),
            max_message_chars=_positive_integer(
                "C19_RECORD_MAX_MESSAGE_CHARS", 10_000
            ),
        )
