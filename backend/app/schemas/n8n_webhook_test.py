from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import reject_runtime_address_data, reject_sensitive_data

N8N_WEBHOOK_TEST_MODULE_KEY = "integration.n8n_webhook_test_bridge"


class N8nWebhookTestRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_id: str | None = Field(default=None, min_length=1, max_length=40)
    key_alias: str = Field(default="n8n", min_length=1, max_length=80)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("key_alias")
    @classmethod
    def normalize_key_alias(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("key_alias must not be empty.")
        return normalized

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        reject_sensitive_data(value)
        reject_runtime_address_data(value)
        return value


class N8nWebhookInjectedKeyRead(BaseModel):
    key_alias: str
    key_id: str
    key_name: str
    header_name: str
    injected: Literal[True] = True


class N8nWebhookTestRunResponse(BaseModel):
    run_id: str
    module_id: Literal["integration.n8n_webhook_test_bridge"]
    org_id: str
    request_sent: bool
    n8n_received: bool
    response_returned: bool
    logs_stored: bool
    success: bool
    status_code: int | None = None
    duration_ms: float
    attempts: int = 1
    retry_count: int = 0
    operation_log_id: str | None = None
    injected_key: N8nWebhookInjectedKeyRead
    response_body: Any | None = None
    error_code: str | None = None
    error_message: str | None = None
