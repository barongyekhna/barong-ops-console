from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import reject_sensitive_data
from .workflow_registry import WorkflowRegistryStatus


WebhookGatewayStatus = Literal["accepted", "rejected"]
WebhookGatewayRouteNode = Literal[
    "requester",
    "C15B Webhook Gateway",
    "C15A Workflow Registry",
    "hidden n8n webhook reference",
    "n8n",
]

DIRECT_ACCESS_KEY_MARKERS = (
    "n8n_webhook",
    "webhook_url",
    "webhook",
    "endpoint",
    "url",
    "authorization",
    "api_key",
    "token",
    "secret",
    "credential",
)
DIRECT_ACCESS_VALUE_MARKERS = (
    "http://",
    "https://",
    "n8n-webhook-ref://",
    "authorization:",
    "bearer ",
)


def _reject_direct_access_data(value: Any) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered_key = str(key).lower()
            if any(marker in lowered_key for marker in DIRECT_ACCESS_KEY_MARKERS):
                raise ValueError("Direct n8n access fields are not allowed.")
            _reject_direct_access_data(item)
    elif isinstance(value, list):
        for item in value:
            _reject_direct_access_data(item)
    elif isinstance(value, str):
        lowered_value = value.lower()
        if any(marker in lowered_value for marker in DIRECT_ACCESS_VALUE_MARKERS):
            raise ValueError("Direct n8n access values are not allowed.")
    return value


class WebhookGatewayRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(min_length=1, max_length=40)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        reject_sensitive_data(value)
        return _reject_direct_access_data(value)


class WebhookGatewayDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15B"] = "C15B"
    component: Literal["Webhook Gateway"] = "Webhook Gateway"
    gateway_status: WebhookGatewayStatus
    reason: str = Field(min_length=1, max_length=500)
    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    standardized_payload: WebhookGatewayRequest
    signature_validated: Literal[True] = True
    workflow_lookup_source: Literal["C15A registry"] = "C15A registry"
    c15a_registered: bool
    c15a_bound_to_module: bool
    c15a_workflow_status: WorkflowRegistryStatus | Literal["unregistered"]
    c15a_execution_allowed: bool
    hidden_webhook_reference_resolved: bool
    n8n_url_exposed: Literal[False] = False
    real_n8n_webhook_address_exposed: Literal[False] = False
    direct_n8n_access_allowed: Literal[False] = False
    direct_workflow_call_allowed: Literal[False] = False
    gateway_bypass_allowed: Literal[False] = False
    n8n_dispatch_performed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False


class WebhookGatewayDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c15b_webhook_gateway_design_v1"] = (
        "c15b_webhook_gateway_design_v1"
    )
    entrypoint: Literal["POST /webhook-gateway/ingress"] = (
        "POST /webhook-gateway/ingress"
    )
    route: tuple[WebhookGatewayRouteNode, ...] = (
        "requester",
        "C15B Webhook Gateway",
        "C15A Workflow Registry",
        "hidden n8n webhook reference",
        "n8n",
    )
    all_requests_must_enter_gateway: Literal[True] = True
    c15a_registry_required: Literal[True] = True
    hardcoded_webhook_url_allowed: Literal[False] = False
    n8n_url_exposure_allowed: Literal[False] = False
    direct_n8n_access_allowed: Literal[False] = False
    gateway_bypass_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    no_production_or_staging_change: Literal[True] = True


class WebhookGatewaySignatureModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c15b_signature_verification_v1"] = (
        "c15b_signature_verification_v1"
    )
    algorithm: Literal["HMAC-SHA256"] = "HMAC-SHA256"
    signature_header: Literal["X-Barong-Gateway-Signature"] = (
        "X-Barong-Gateway-Signature"
    )
    signature_prefix: Literal["sha256="] = "sha256="
    signed_payload_shape: tuple[
        Literal["module"],
        Literal["workflow_id"],
        Literal["context_id"],
        Literal["payload"],
        Literal["timestamp"],
    ] = ("module", "workflow_id", "context_id", "payload", "timestamp")
    timestamp_required: Literal[True] = True
    invalid_signature_rejected: Literal[True] = True
    unsigned_request_rejected: Literal[True] = True
    replay_window_seconds: int = Field(gt=0, le=900)
    secret_exposed_in_response: Literal[False] = False


class WebhookGatewayPayloadFormat(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    format_id: Literal["c15b_standard_payload_v1"] = (
        "c15b_standard_payload_v1"
    )
    required_fields: tuple[
        Literal["module"],
        Literal["workflow_id"],
        Literal["context_id"],
        Literal["payload"],
        Literal["timestamp"],
    ] = ("module", "workflow_id", "context_id", "payload", "timestamp")
    extra_fields_allowed: Literal[False] = False
    payload_may_contain_direct_n8n_access: Literal[False] = False
    payload_may_contain_credentials: Literal[False] = False
    standardized_shape: dict[str, str] = Field(
        default_factory=lambda: {
            "module": "registered module key",
            "workflow_id": "C15A workflow id",
            "context_id": "caller context correlation id",
            "payload": "credential-free JSON object",
            "timestamp": "ISO-8601 signing timestamp",
        }
    )


class WebhookGatewayLookupFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: Literal["c15b_c15a_lookup_flow_v1"] = (
        "c15b_c15a_lookup_flow_v1"
    )
    steps: tuple[str, ...] = (
        "Validate C15B request signature.",
        "Validate standard payload shape.",
        "Lookup workflow through C15A registry decision.",
        "Require registered, module-bound, active workflow status.",
        "Resolve only the hidden webhook reference internally.",
        "Return gateway decision without exposing n8n URL.",
    )
    registry_source: Literal["C15A registry"] = "C15A registry"
    hardcoded_webhook_url_allowed: Literal[False] = False
    unregistered_workflow_allowed: Literal[False] = False
    inactive_workflow_allowed: Literal[False] = False
    deprecated_workflow_allowed: Literal[False] = False
    error_workflow_allowed: Literal[False] = False
    no_runtime_execution: Literal[True] = True


class WebhookGatewayCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15B"] = "C15B"
    component: Literal["Webhook Gateway"] = "Webhook Gateway"
    completion_status: Literal["complete"] = "complete"
    gateway_design_defined: Literal[True] = True
    signature_verification_defined: Literal[True] = True
    invalid_request_rejected: Literal[True] = True
    payload_standardization_defined: Literal[True] = True
    c15a_lookup_integrated: Literal[True] = True
    hardcoded_webhook_url_allowed: Literal[False] = False
    n8n_url_exposure_allowed: Literal[False] = False
    direct_workflow_call_allowed: Literal[False] = False
    gateway_bypass_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    no_production_or_staging_change: Literal[True] = True
    can_proceed_to_c15c: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=500)
