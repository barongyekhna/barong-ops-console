from collections.abc import Mapping
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "password_hash",
    "token",
    "secret",
    "session_id",
    "cookie",
    "set-cookie",
    "signature",
    "nonce",
    "idempotency",
    "authorization",
    "api_key",
    "private_key",
    "credential",
)
RUNTIME_ADDRESS_KEY_MARKERS = (
    "n8n_webhook",
    "webhook_url",
    "provider_url",
    "endpoint_url",
    "callback_url",
    "target_url",
)
RUNTIME_ADDRESS_KEY_EXACT = frozenset(
    (
        "url",
        "endpoint",
        "endpoint_ref",
        "webhook",
    )
)
RUNTIME_ADDRESS_VALUE_MARKERS = (
    "http://",
    "https://",
    "n8n-webhook-ref://",
)
RUNTIME_ADDRESS_REDACTION = "[redacted-runtime-address]"
FOUNDATION_ID_PATTERN = (
    r"^(?:foundation|demo|n8n_test)[._-][A-Za-z0-9._-]+$"
)


def is_runtime_address_key(key: object) -> bool:
    normalized_key = str(key).lower()
    return normalized_key in RUNTIME_ADDRESS_KEY_EXACT or any(
        marker in normalized_key for marker in RUNTIME_ADDRESS_KEY_MARKERS
    )


def contains_runtime_address_data(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if is_runtime_address_key(key) or contains_runtime_address_data(item):
                return True
    elif isinstance(value, list):
        return any(contains_runtime_address_data(item) for item in value)
    elif isinstance(value, str):
        lowered_value = value.lower()
        return any(marker in lowered_value for marker in RUNTIME_ADDRESS_VALUE_MARKERS)
    return False


def sanitize_runtime_address_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_runtime_address_data(item)
            for key, item in value.items()
            if not is_runtime_address_key(key)
        }
    if isinstance(value, list):
        return [sanitize_runtime_address_data(item) for item in value]
    if isinstance(value, str) and contains_runtime_address_data(value):
        return RUNTIME_ADDRESS_REDACTION
    return value


def reject_runtime_address_data(value: Any) -> Any:
    if contains_runtime_address_data(value):
        raise ValueError("Runtime URL or webhook reference data is not allowed.")
    return value


def reject_sensitive_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(marker in normalized_key for marker in SENSITIVE_KEY_MARKERS):
                raise ValueError("Sensitive credential fields are not allowed.")
            reject_sensitive_data(item)
    elif isinstance(value, list):
        for item in value:
            reject_sensitive_data(item)
    return value


ItemT = TypeVar("ItemT")


class ApiErrorInfo(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    retryable: bool = True


class ListResponse(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    cursor: str | None = None
    next_cursor: str | None = None
    degraded: bool = False
    source: str = "live"
    error: ApiErrorInfo | None = None
