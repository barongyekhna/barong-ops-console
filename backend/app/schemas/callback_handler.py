from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import reject_sensitive_data
from .execution_payload_standardization import ExecutionPayloadStandardRequest


CallbackExecutionStatus = Literal["pending", "running", "success", "failed"]
CallbackProcessingStatus = Literal["accepted", "rejected"]
CallbackModuleFamily = Literal["K", "P", "SEO", "generic"]

CALLBACK_BLOCKED_KEY_MARKERS = (
    "webhook_url",
    "webhook",
    "endpoint",
    "url",
    "authorization",
    "api_key",
    "token",
    "secret",
    "credential",
    "password",
)
CALLBACK_BLOCKED_VALUE_MARKERS = (
    "http://",
    "https://",
    "n8n-webhook-ref://",
    "authorization:",
    "bearer ",
)
CALLBACK_CONTEXT_ID_PATTERN = re.compile(r"^ctx\.c15c\.[0-9a-f]{16}$")


def reject_callback_runtime_data(value: Any) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(
                marker in normalized_key for marker in CALLBACK_BLOCKED_KEY_MARKERS
            ):
                raise ValueError(
                    "Callback runtime access or credential fields are not allowed."
                )
            reject_callback_runtime_data(item)
    elif isinstance(value, list):
        for item in value:
            reject_callback_runtime_data(item)
    elif isinstance(value, str):
        lowered_value = value.lower()
        if any(
            marker in lowered_value for marker in CALLBACK_BLOCKED_VALUE_MARKERS
        ):
            raise ValueError(
                "Callback runtime access or credential values are not allowed."
            )
    return value


def validate_callback_context_id(value: str) -> str:
    if not CALLBACK_CONTEXT_ID_PATTERN.fullmatch(value):
        raise ValueError("C15D context_id must use the C15C standard format.")
    return value


class CallbackHandlerPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    status: CallbackExecutionStatus
    output: dict[str, Any] = Field(default_factory=dict)
    execution_metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(min_length=1, max_length=40)
    nonce: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    idempotency_key: str | None = Field(
        default=None,
        min_length=8,
        max_length=180,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_callback_context_id(value)

    @field_validator("output", "execution_metadata")
    @classmethod
    def validate_callback_data(cls, value: dict[str, Any]) -> dict[str, Any]:
        reject_sensitive_data(value)
        reject_callback_runtime_data(value)
        return value


class CallbackContextBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15D"] = "C15D"
    component: Literal["Context Binding System"] = "Context Binding System"
    context_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    task: str = Field(min_length=1, max_length=180)
    workflow_id: str = Field(min_length=1, max_length=180)
    original_request: ExecutionPayloadStandardRequest
    status: CallbackExecutionStatus = "pending"
    bound_at: str = Field(min_length=1, max_length=40)
    c15c_execution_request_bound: Literal[True] = True
    context_id_lookup_required: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_callback_context_id(value)


class CallbackResultStorageRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15D"] = "C15D"
    component: Literal["Result Storage"] = "Result Storage"
    context_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    task: str = Field(min_length=1, max_length=180)
    workflow_id: str = Field(min_length=1, max_length=180)
    status: CallbackExecutionStatus
    original_request: ExecutionPayloadStandardRequest
    workflow_output: dict[str, Any] = Field(default_factory=dict)
    execution_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(min_length=1, max_length=40)
    updated_at: str = Field(min_length=1, max_length=40)
    started_at: str | None = Field(default=None, max_length=40)
    completed_at: str | None = Field(default=None, max_length=40)
    callbacks_received: int = Field(default=0, ge=0)
    signature_validated: bool = False
    payload_validated: bool = False
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_callback_context_id(value)


class CallbackStandardizedModuleResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15D"] = "C15D"
    component: Literal["Module Notification System"] = (
        "Module Notification System"
    )
    context_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    module_family: CallbackModuleFamily
    workflow_id: str = Field(min_length=1, max_length=180)
    status: CallbackExecutionStatus
    output: dict[str, Any] = Field(default_factory=dict)
    execution_metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(min_length=1, max_length=40)
    standardized_result: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_callback_context_id(value)


class CallbackModuleNotification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    notification_status: Literal["prepared"] = "prepared"
    notification_mode: Literal["in_process_contract"] = "in_process_contract"
    module: str = Field(min_length=1, max_length=128)
    module_family: CallbackModuleFamily
    context_id: str = Field(min_length=1, max_length=180)
    standardized_result: CallbackStandardizedModuleResult
    module_notification_prepared: Literal[True] = True
    external_module_call_performed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_callback_context_id(value)


class CallbackHandlerResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15D"] = "C15D"
    component: Literal["Callback Handler System"] = "Callback Handler System"
    processing_status: CallbackProcessingStatus
    reason: str = Field(min_length=1, max_length=700)
    context_binding: CallbackContextBinding
    status: CallbackExecutionStatus
    stored_result: CallbackResultStorageRecord
    module_notification: CallbackModuleNotification
    signature_validated: Literal[True] = True
    payload_validated: Literal[True] = True
    context_bound_to_c15c_request: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    n8n_dispatch_performed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False


class CallbackHandlerDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c15d_callback_handler_design_v1"] = (
        "c15d_callback_handler_design_v1"
    )
    entrypoint: Literal["POST /api/control-plane/callback-handler/receiver"] = (
        "POST /api/control-plane/callback-handler/receiver"
    )
    route: tuple[str, ...] = (
        "n8n webhook callback",
        "C15D Callback Receiver",
        "C15B signature verification",
        "C15D Context Binding System",
        "C15D Execution Status Manager",
        "C15D Result Storage",
        "C15D Module Notification System",
    )
    callback_payload_required_fields: tuple[
        Literal["module"],
        Literal["workflow_id"],
        Literal["context_id"],
        Literal["status"],
        Literal["output"],
        Literal["execution_metadata"],
        Literal["timestamp"],
    ] = (
        "module",
        "workflow_id",
        "context_id",
        "status",
        "output",
        "execution_metadata",
        "timestamp",
    )
    optional_callback_fields: tuple[
        Literal["nonce"],
        Literal["idempotency_key"],
    ] = ("nonce", "idempotency_key")
    signature_header: Literal["X-Barong-Gateway-Signature"] = (
        "X-Barong-Gateway-Signature"
    )
    signature_source: Literal["C15B HMAC-SHA256 verification model"] = (
        "C15B HMAC-SHA256 verification model"
    )
    no_execution_trigger: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_or_staging_change: Literal[True] = True
    replay_nonce_required: Literal[True] = True
    idempotency_key_required: Literal[True] = True


class CallbackContextBindingModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c15d_context_binding_model_v1"] = (
        "c15d_context_binding_model_v1"
    )
    lookup_key: Literal["context_id"] = "context_id"
    context_id_pattern: Literal["^ctx\\.c15c\\.[0-9a-f]{16}$"] = (
        "^ctx\\.c15c\\.[0-9a-f]{16}$"
    )
    bound_request_type: Literal["C15C ExecutionPayloadStandardRequest"] = (
        "C15C ExecutionPayloadStandardRequest"
    )
    callback_context_must_exist: Literal[True] = True
    module_must_match_bound_request: Literal[True] = True
    workflow_must_match_bound_request: Literal[True] = True
    unknown_context_behavior: Literal["reject_callback"] = "reject_callback"
    runtime_execution_allowed: Literal[False] = False


class CallbackStatusManagementModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c15d_status_management_v1"] = (
        "c15d_status_management_v1"
    )
    allowed_statuses: tuple[CallbackExecutionStatus, ...] = (
        "pending",
        "running",
        "success",
        "failed",
    )
    allowed_transitions: dict[str, tuple[CallbackExecutionStatus, ...]] = Field(
        default_factory=lambda: {
            "pending": ("pending", "running", "success", "failed"),
            "running": ("running", "success", "failed"),
            "success": ("success",),
            "failed": ("failed",),
        }
    )
    terminal_statuses: tuple[Literal["success"], Literal["failed"]] = (
        "success",
        "failed",
    )
    invalid_transition_behavior: Literal["reject_callback"] = (
        "reject_callback"
    )
    duplicate_terminal_callback_behavior: Literal["idempotent_return"] = (
        "idempotent_return"
    )
    runtime_execution_allowed: Literal[False] = False


class CallbackResultStorageModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c15d_result_storage_model_v1"] = (
        "c15d_result_storage_model_v1"
    )
    storage_key: Literal["context_id"] = "context_id"
    stored_fields: tuple[
        Literal["workflow_output"],
        Literal["execution_metadata"],
        Literal["created_at"],
        Literal["updated_at"],
        Literal["started_at"],
        Literal["completed_at"],
        Literal["callbacks_received"],
    ] = (
        "workflow_output",
        "execution_metadata",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "callbacks_received",
    )
    storage_mode: Literal["in_memory_contract_store"] = (
        "in_memory_contract_store"
    )
    credentials_stored: Literal[False] = False
    n8n_url_stored: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class CallbackModuleNotificationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c15d_module_notification_model_v1"] = (
        "c15d_module_notification_model_v1"
    )
    supported_module_families: tuple[
        Literal["K"],
        Literal["P"],
        Literal["SEO"],
    ] = ("K", "P", "SEO")
    notification_mode: Literal["in_process_contract"] = "in_process_contract"
    standardized_result_returned: Literal[True] = True
    external_module_call_performed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False


class CallbackHandlerCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15D"] = "C15D"
    component: Literal["Callback Handler System"] = "Callback Handler System"
    completion_status: Literal["complete"] = "complete"
    callback_receiver_defined: Literal[True] = True
    payload_validation_defined: Literal[True] = True
    c15b_signature_verification_reused: Literal[True] = True
    context_binding_defined: Literal[True] = True
    replay_protection_defined: Literal[True] = True
    idempotency_enforced: Literal[True] = True
    status_management_defined: Literal[True] = True
    result_storage_defined: Literal[True] = True
    module_notification_defined: Literal[True] = True
    no_execution_trigger: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_or_staging_change: Literal[True] = True
    can_proceed_to_c15e: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=700)
