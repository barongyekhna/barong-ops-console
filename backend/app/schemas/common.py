from collections.abc import Mapping
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "password_hash",
    "token",
    "secret",
    "authorization",
    "api_key",
    "private_key",
    "credential",
)
FOUNDATION_ID_PATTERN = (
    r"^(?:foundation|demo|n8n_test)[._-][A-Za-z0-9._-]+$"
)


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


class ListResponse(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
