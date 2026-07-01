from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


ApiKeyStatus = Literal["active", "disabled", "deleted"]
ApiKeyBindingStatus = Literal["active", "disabled"]


class KeyType(str, Enum):
    CUSTOM = "custom"
    SERP = "serp"
    OPENAI = "openai"
    CHATGPT = "chatgpt"
    CLAUDE_OPUS = "claude_opus"
    DEEPSEEK = "deepseek"
    N8N = "n8n"
    KEEPA = "keepa"


def _validate_provider_url(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("API key URL must use HTTP or HTTPS.")
    if parsed.username or parsed.password:
        raise ValueError("API key URL must not contain credentials.")
    if not parsed.netloc:
        raise ValueError("API key URL must include a host.")
    if parsed.query or parsed.fragment:
        raise ValueError("API key URL must not contain query or fragment data.")
    return normalized


def _normalize_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Name must not be empty.")
    return normalized


def _normalize_alias(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    if not normalized:
        return "default"
    return normalized


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=500)
    key_value: SecretStr = Field(min_length=1, max_length=4096)
    key_type: KeyType = KeyType.CUSTOM

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _normalize_name(value)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_provider_url(value)


class ApiKeyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    key_value: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    status: ApiKeyStatus | None = None
    key_type: KeyType | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _normalize_name(value) if value is not None else None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return _validate_provider_url(value) if value is not None else None


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key_id: str = Field(min_length=1, max_length=40)
    org_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=500)
    key_type: KeyType = KeyType.CUSTOM
    provider: str = Field(default="custom", min_length=1, max_length=80)
    auth_type: str = Field(default="api_key", min_length=1, max_length=80)
    scope: list[str] = Field(default_factory=list)
    validation_endpoint: str | None = Field(default=None, max_length=500)
    key_hash_prefix: str = Field(min_length=1, max_length=16)
    status: ApiKeyStatus
    runtime_state: Literal["enabled", "disabled"] = "disabled"
    assigned_module_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None


class ApiKeyListResponse(BaseModel):
    items: list[ApiKeyRead]
    count: int = Field(ge=0)


class ApiKeyCreateResponse(BaseModel):
    item: ApiKeyRead


class ApiKeyUpdateResponse(BaseModel):
    item: ApiKeyRead


class ApiKeyDeleteResponse(BaseModel):
    key_id: str
    status: Literal["deleted"] = "deleted"


class ApiKeyBindingCreateRequest(BaseModel):
    module_id: str = Field(min_length=1, max_length=128)
    key_id: str = Field(min_length=1, max_length=40)
    key_alias: str = Field(default="default", min_length=1, max_length=80)

    @field_validator("key_alias")
    @classmethod
    def validate_key_alias(cls, value: str) -> str:
        return _normalize_alias(value)


class ApiKeyBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    binding_id: str = Field(min_length=1, max_length=40)
    org_id: str = Field(min_length=1, max_length=40)
    module_id: str = Field(min_length=1, max_length=128)
    key_id: str = Field(min_length=1, max_length=40)
    key_alias: str = Field(min_length=1, max_length=80)
    key_name: str = Field(min_length=1, max_length=120)
    key_url: str = Field(min_length=1, max_length=500)
    key_type: KeyType = KeyType.CUSTOM
    provider: str = Field(default="custom", min_length=1, max_length=80)
    status: ApiKeyBindingStatus
    created_at: datetime
    updated_at: datetime


class ApiKeyBindingListResponse(BaseModel):
    items: list[ApiKeyBindingRead]
    count: int = Field(ge=0)


class ApiKeyBindingCreateResponse(BaseModel):
    item: ApiKeyBindingRead


class ApiKeyBindingDeleteResponse(BaseModel):
    binding_id: str
    status: Literal["disabled"] = "disabled"


class ApiKeyTypeRead(BaseModel):
    type: KeyType
    name: str
    description: str
    provider: str
    auth_type: str
    enabled: bool
    scope: list[str]
    validation_endpoint: str | None = None
    default_url: str | None = None


class ApiKeyTypeListResponse(BaseModel):
    items: list[ApiKeyTypeRead]
    count: int = Field(ge=0)
