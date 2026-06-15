from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .ai_execution_binding import AIExecutionCapability
from .common import reject_sensitive_data
from .workflow_registry import WorkflowRegistryStatus


ExecutionPayloadNormalizationStatus = Literal["accepted", "rejected"]
RUNTIME_PAYLOAD_KEY_MARKERS = (
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
RUNTIME_PAYLOAD_VALUE_MARKERS = (
    "http://",
    "https://",
    "n8n-webhook-ref://",
    "authorization:",
    "bearer ",
)


def reject_runtime_payload_data(value: Any) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(
                marker in normalized_key
                for marker in RUNTIME_PAYLOAD_KEY_MARKERS
            ):
                raise ValueError(
                    "Runtime access fields are not allowed in C15C payload."
                )
            reject_runtime_payload_data(item)
    elif isinstance(value, list):
        for item in value:
            reject_runtime_payload_data(item)
    elif isinstance(value, str):
        lowered_value = value.lower()
        if any(marker in lowered_value for marker in RUNTIME_PAYLOAD_VALUE_MARKERS):
            raise ValueError(
                "Runtime access values are not allowed in C15C payload."
            )
    return value


class ExecutionPayloadMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: AIExecutionCapability
    model: str = Field(min_length=1, max_length=180)
    key_id: str = Field(min_length=1, max_length=180)


class ExecutionPayloadStandardRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: str = Field(min_length=1, max_length=128)
    task: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    workflow_id: str = Field(min_length=1, max_length=180)
    execution: ExecutionPayloadMetadata
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
        reject_runtime_payload_data(value)
        return value


class ExecutionPayloadTraceChain(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: str = Field(min_length=1, max_length=128)
    task: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    workflow_id: str | None = Field(default=None, max_length=180)
    capability: AIExecutionCapability | None = None
    model: str | None = Field(default=None, max_length=180)
    key_id: str | None = Field(default=None, max_length=180)
    chain: tuple[str, ...]
    context_id_is_standardized: Literal[True] = True
    traceable_execution_chain: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False


class ExecutionPayloadNormalizationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15C"] = "C15C"
    component: Literal["Execution Payload Standardization Layer"] = (
        "Execution Payload Standardization Layer"
    )
    normalization_status: ExecutionPayloadNormalizationStatus
    reason: str = Field(min_length=1, max_length=700)
    module: str | None = Field(default=None, max_length=128)
    task: str | None = Field(default=None, max_length=180)
    context_id: str | None = Field(default=None, max_length=180)
    workflow_id: str | None = Field(default=None, max_length=180)
    execution: ExecutionPayloadMetadata | None = None
    standardized_request: ExecutionPayloadStandardRequest | None = None
    trace_chain: ExecutionPayloadTraceChain | None = None
    c15a_workflow_lookup_source: Literal["C15A registry"] = "C15A registry"
    c14x_execution_metadata_source: Literal[
        "C14X capability binding engine"
    ] = "C14X capability binding engine"
    c15a_registered: bool = False
    c15a_bound_to_module: bool = False
    c15a_workflow_status: WorkflowRegistryStatus | Literal["unregistered"] = (
        "unregistered"
    )
    workflow_mapping_validated: bool = False
    context_standardized: bool = False
    execution_metadata_attached: bool = False
    standardized_request_schema_valid: bool = False
    runtime_execution_allowed: Literal[False] = False
    n8n_dispatch_performed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False


class ExecutionPayloadStandardizationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c15c_standard_request_schema_v1"] = (
        "c15c_standard_request_schema_v1"
    )
    required_fields: tuple[
        Literal["module"],
        Literal["task"],
        Literal["context_id"],
        Literal["workflow_id"],
        Literal["execution"],
        Literal["payload"],
        Literal["timestamp"],
    ] = (
        "module",
        "task",
        "context_id",
        "workflow_id",
        "execution",
        "payload",
        "timestamp",
    )
    execution_shape: tuple[
        Literal["capability"],
        Literal["model"],
        Literal["key_id"],
    ] = ("capability", "model", "key_id")
    payload_schema: dict[str, Any] = Field(
        default_factory=lambda: {
            "module": "registered module key",
            "task": "module task or action normalized into a common field",
            "context_id": "ctx.c15c.<16 hex chars>",
            "workflow_id": "C15A active workflow id",
            "execution": {
                "capability": "C14X capability",
                "model": "C14X locked model reference",
                "key_id": "C14X binding key",
            },
            "payload": "credential-free JSON object",
            "timestamp": "ISO-8601 normalization timestamp",
        }
    )
    extra_top_level_fields_allowed: Literal[False] = False
    workflow_id_caller_override_allowed: Literal[False] = False
    execution_metadata_caller_override_allowed: Literal[False] = False
    no_runtime_execution: Literal[True] = True
    no_model_invocation: Literal[True] = True
    no_external_api_call: Literal[True] = True


class ExecutionPayloadNormalizationEngineDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine_id: Literal["c15c_normalization_engine_v1"] = (
        "c15c_normalization_engine_v1"
    )
    flow: tuple[str, ...] = (
        "Read module-specific request aliases.",
        "Normalize module/task/payload fields into the standard request shape.",
        "Standardize context_id as ctx.c15c.<hash>.",
        "Auto attach workflow_id from C15A active module binding.",
        "Auto attach execution metadata from C14X capability binding.",
        "Validate the final standard request schema.",
        "Return a normalization decision without dispatching runtime work.",
    )
    module_aliases: tuple[str, ...] = ("module", "module_key")
    task_aliases: tuple[str, ...] = ("task", "action", "operation")
    context_aliases: tuple[str, ...] = (
        "context_id",
        "contextId",
        "correlation_id",
        "trace_id",
        "context",
    )
    workflow_mapping_source: Literal["C15A registry"] = "C15A registry"
    execution_metadata_source: Literal["C14X capability binding engine"] = (
        "C14X capability binding engine"
    )
    missing_workflow_behavior: Literal["reject_without_fallback"] = (
        "reject_without_fallback"
    )
    missing_execution_binding_behavior: Literal["reject_without_fallback"] = (
        "reject_without_fallback"
    )
    runtime_execution_allowed: Literal[False] = False
    n8n_dispatch_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class ExecutionPayloadContextRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rules_id: Literal["c15c_context_standardization_rules_v1"] = (
        "c15c_context_standardization_rules_v1"
    )
    context_id_pattern: Literal["^ctx\\.c15c\\.[0-9a-f]{16}$"] = (
        "^ctx\\.c15c\\.[0-9a-f]{16}$"
    )
    module_specific_context_format_allowed: Literal[False] = False
    raw_context_value_returned: Literal[False] = False
    context_hash_inputs: tuple[
        Literal["module"],
        Literal["task"],
        Literal["raw_context"],
        Literal["timestamp"],
    ] = ("module", "task", "raw_context", "timestamp")
    trace_chain_fields: tuple[
        Literal["module"],
        Literal["task"],
        Literal["context_id"],
        Literal["workflow_id"],
        Literal["capability"],
        Literal["model"],
        Literal["key_id"],
    ] = (
        "module",
        "task",
        "context_id",
        "workflow_id",
        "capability",
        "model",
        "key_id",
    )
    no_runtime_execution: Literal[True] = True


class ExecutionPayloadWorkflowMappingIntegration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c15c_c15a_workflow_mapping_v1"] = (
        "c15c_c15a_workflow_mapping_v1"
    )
    mapping_rule: Literal["module -> active workflow_id"] = (
        "module -> active workflow_id"
    )
    registry_source: Literal["C15A registry"] = "C15A registry"
    validate_workflow_exists: Literal[True] = True
    validate_module_binding: Literal[True] = True
    require_active_workflow_status: Literal[True] = True
    invalid_mapping_behavior: Literal["reject_without_fallback"] = (
        "reject_without_fallback"
    )
    ambiguous_active_workflow_behavior: Literal["reject_without_guessing"] = (
        "reject_without_guessing"
    )
    hidden_webhook_ref_exposed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    n8n_dispatch_allowed: Literal[False] = False


class ExecutionPayloadCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15C"] = "C15C"
    component: Literal["Execution Payload Standardization Layer"] = (
        "Execution Payload Standardization Layer"
    )
    completion_status: Literal["complete"] = "complete"
    payload_standardization_model_defined: Literal[True] = True
    normalization_engine_defined: Literal[True] = True
    context_standard_rules_defined: Literal[True] = True
    workflow_mapping_integrated: Literal[True] = True
    c15a_registry_integration_defined: Literal[True] = True
    c14x_execution_metadata_integration_defined: Literal[True] = True
    invalid_mapping_rejected: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    n8n_dispatch_allowed: Literal[False] = False
    model_invocation_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    no_production_or_staging_change: Literal[True] = True
    can_proceed_to_c15d: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=700)
