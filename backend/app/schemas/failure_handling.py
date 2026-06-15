from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import reject_runtime_address_data, reject_sensitive_data
from .result_normalization import NormalizedWorkflowResult
from .webhook_gateway import WebhookGatewayDecision, WebhookGatewayRequest


FailureType = Literal[
    "webhook_timeout",
    "callback_failed",
    "gateway_rejected",
    "normalization_failed",
    "manual_failure",
    "retry_exhausted",
]
RetryDecisionStatus = Literal[
    "retry_scheduled",
    "retry_exhausted",
    "not_retryable",
]
DeadLetterQueueStatus = Literal[
    "retry_pending",
    "queued",
    "replayed",
    "closed",
]
TimeoutStatus = Literal["within_timeout", "timed_out"]
FallbackStatus = Literal["generated"]
RecoveryStatus = Literal["replay_prepared", "replay_rejected", "not_found"]

FAILURE_CONTEXT_ID_PATTERN = re.compile(r"^ctx\.c15c\.[0-9a-f]{16}$")
FAILURE_BLOCKED_VALUE_MARKERS = (
    "authorization:",
    "bearer ",
    "api_key=",
    "token=",
    "secret=",
    "credential=",
    "password=",
)


def validate_failure_context_id(value: str) -> str:
    if not FAILURE_CONTEXT_ID_PATTERN.fullmatch(value):
        raise ValueError("C15H context_id must use the C15C standard format.")
    return value


def reject_failure_runtime_data(value: Any) -> Any:
    reject_sensitive_data(value)
    reject_runtime_address_data(value)
    if isinstance(value, dict):
        for item in value.values():
            reject_failure_runtime_data(item)
    elif isinstance(value, list):
        for item in value:
            reject_failure_runtime_data(item)
    elif isinstance(value, str):
        lowered_value = value.lower()
        if any(marker in lowered_value for marker in FAILURE_BLOCKED_VALUE_MARKERS):
            raise ValueError(
                "Runtime access or credential values are not allowed in C15H."
            )
    return value


class FailureRetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: Literal["c15h_retry_policy_v1"] = "c15h_retry_policy_v1"
    automatic_retry_enabled: bool = True
    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_backoff_seconds: int = Field(default=2, ge=1, le=3600)
    backoff_multiplier: float = Field(default=2.0, ge=1.0, le=10.0)
    max_backoff_seconds: int = Field(default=300, ge=1, le=86400)
    retryable_failure_types: tuple[FailureType, ...] = (
        "webhook_timeout",
        "callback_failed",
        "gateway_rejected",
        "normalization_failed",
    )
    exponential_backoff_model: Literal[
        "initial_backoff_seconds * backoff_multiplier^(attempt - 1), capped"
    ] = "initial_backoff_seconds * backoff_multiplier^(attempt - 1), capped"
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_backoff_bounds(self) -> "FailureRetryPolicy":
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError(
                "C15H max_backoff_seconds must be greater than or equal to "
                "initial_backoff_seconds."
            )
        return self


class FailureHandlingRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    failure_type: FailureType
    reason: str = Field(min_length=1, max_length=700)
    attempt: int = Field(default=1, ge=1, le=100)
    task: str | None = Field(default=None, max_length=180)
    payload: dict[str, Any] = Field(default_factory=dict)
    retry_policy: FailureRetryPolicy = Field(default_factory=FailureRetryPolicy)

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_failure_context_id(value)

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        reject_failure_runtime_data(value)
        return value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        reject_failure_runtime_data(value)
        return value


class TimeoutEvaluationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    started_at: str = Field(min_length=1, max_length=40)
    checked_at: str | None = Field(default=None, max_length=40)
    timeout_seconds: int = Field(default=60, ge=1, le=86400)
    attempt: int = Field(default=1, ge=1, le=100)
    task: str | None = Field(default=None, max_length=180)
    payload: dict[str, Any] = Field(default_factory=dict)
    retry_policy: FailureRetryPolicy = Field(default_factory=FailureRetryPolicy)

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_failure_context_id(value)

    @field_validator("started_at", "checked_at")
    @classmethod
    def validate_timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        reject_failure_runtime_data(value)
        return value


class FailureRetryDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15H"] = "C15H"
    component: Literal["Retry Mechanism"] = "Retry Mechanism"
    context_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    failure_type: FailureType
    retry_status: RetryDecisionStatus
    attempt: int = Field(ge=1)
    next_attempt: int | None = Field(default=None, ge=1)
    max_attempts: int = Field(ge=1)
    automatic_retry_enabled: bool
    retry_allowed: bool
    backoff_seconds: int | None = Field(default=None, ge=1)
    next_retry_after: str | None = Field(default=None, max_length=40)
    exponential_backoff_applied: bool
    reason: str = Field(min_length=1, max_length=700)
    c15b_reentry_required: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    n8n_dispatch_performed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_failure_context_id(value)


class DeadLetterRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15H"] = "C15H"
    component: Literal["Dead Letter Queue"] = "Dead Letter Queue"
    dlq_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    failure_type: FailureType
    failure_reason: str = Field(min_length=1, max_length=700)
    attempt: int = Field(ge=1)
    status: DeadLetterQueueStatus
    failure_context: dict[str, Any] = Field(default_factory=dict)
    retry_decision: FailureRetryDecision
    failed_at: str = Field(min_length=1, max_length=40)
    replay_count: int = Field(default=0, ge=0)
    last_replayed_at: str | None = Field(default=None, max_length=40)
    manual_replay_allowed: Literal[True] = True
    context_id_stored: Literal[True] = True
    n8n_url_exposed: Literal[False] = False
    hidden_webhook_ref_exposed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_failure_context_id(value)

    @field_validator("failed_at", "last_replayed_at")
    @classmethod
    def validate_timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("failure_context")
    @classmethod
    def validate_failure_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        reject_failure_runtime_data(value)
        return value

    @field_validator("failure_reason")
    @classmethod
    def validate_failure_reason(cls, value: str) -> str:
        reject_failure_runtime_data(value)
        return value


class DeadLetterQueueResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[DeadLetterRecord]
    count: int = Field(ge=0)
    retry_pending_count: int = Field(ge=0)
    queued_count: int = Field(ge=0)
    replayed_count: int = Field(ge=0)
    context_id_indexed: Literal[True] = True
    manual_replay_supported: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False


class FallbackResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15H"] = "C15H"
    component: Literal["Fallback System"] = "Fallback System"
    fallback_status: FallbackStatus = "generated"
    fallback_mode: Literal["graceful_degradation"] = "graceful_degradation"
    context_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    status: Literal["failed"] = "failed"
    safe_message: str = Field(min_length=1, max_length=300)
    normalized_result: NormalizedWorkflowResult
    graceful_degradation: Literal[True] = True
    module_safe_failure_return: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_failure_context_id(value)


class FailureHandlingOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15H"] = "C15H"
    component: Literal["Failure Handling & Retry System"] = (
        "Failure Handling & Retry System"
    )
    handling_status: Literal[
        "retry_scheduled",
        "dead_lettered",
        "fallback_only",
    ]
    reason: str = Field(min_length=1, max_length=700)
    context_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    retry_decision: FailureRetryDecision
    fallback_response: FallbackResponse
    dlq_record: DeadLetterRecord
    execution_marked_failed: Literal[True] = True
    c15d_status_update_performed: bool
    c15d_status_update_reason: str = Field(min_length=1, max_length=300)
    runtime_execution_allowed: Literal[False] = False
    n8n_dispatch_performed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_failure_context_id(value)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        reject_failure_runtime_data(value)
        return value


class TimeoutHandlingDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15H"] = "C15H"
    component: Literal["Timeout Handling"] = "Timeout Handling"
    timeout_status: TimeoutStatus
    context_id: str = Field(min_length=1, max_length=180)
    module: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=180)
    elapsed_seconds: float = Field(ge=0)
    timeout_seconds: int = Field(ge=1)
    checked_at: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=700)
    failure_outcome: FailureHandlingOutcome | None = None
    fallback_triggered: bool
    execution_marked_failed: bool
    runtime_execution_allowed: Literal[False] = False
    n8n_dispatch_performed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_failure_context_id(value)

    @field_validator("checked_at")
    @classmethod
    def validate_checked_at(cls, value: str) -> str:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class ManualReplayRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    context_id: str = Field(min_length=1, max_length=180)
    reason: str = Field(default="Manual C15H replay requested.", max_length=300)
    force_replay: bool = False

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_failure_context_id(value)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        reject_failure_runtime_data(value)
        return value


class RecoveryPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15H"] = "C15H"
    component: Literal["Recovery Mechanism"] = "Recovery Mechanism"
    recovery_status: RecoveryStatus
    context_id: str = Field(min_length=1, max_length=180)
    reason: str = Field(min_length=1, max_length=700)
    manual_retry_triggered: bool
    context_based_recovery: Literal[True] = True
    reexecution_boundary: Literal["C15B Webhook Gateway"] = "C15B Webhook Gateway"
    c15b_reexecution_path: tuple[
        Literal["C15H manual replay"],
        Literal["C15B Webhook Gateway"],
        Literal["C15A Workflow Registry"],
        Literal["n8n boundary"],
    ] = (
        "C15H manual replay",
        "C15B Webhook Gateway",
        "C15A Workflow Registry",
        "n8n boundary",
    )
    dlq_record: DeadLetterRecord | None = None
    replay_payload: WebhookGatewayRequest | None = None
    c15b_gateway_decision: WebhookGatewayDecision | None = None
    fallback_response: FallbackResponse | None = None
    runtime_execution_allowed: Literal[False] = False
    n8n_dispatch_performed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False

    @field_validator("context_id")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        return validate_failure_context_id(value)


class RetrySystemDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c15h_retry_system_design_v1"] = (
        "c15h_retry_system_design_v1"
    )
    automatic_retry_supported: Literal[True] = True
    configurable_retry_count_supported: Literal[True] = True
    exponential_backoff_supported: Literal[True] = True
    default_policy: FailureRetryPolicy = Field(default_factory=FailureRetryPolicy)
    retry_flow: tuple[str, ...] = (
        "Classify the failure type.",
        "Check whether automatic retry is enabled and the failure is retryable.",
        "Compare the current attempt with max_attempts.",
        "Compute conceptual exponential backoff for the next attempt.",
        "Record retry scheduling without dispatching runtime work.",
    )
    c15b_reentry_required: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False


class TimeoutHandlingModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c15h_timeout_handling_model_v1"] = (
        "c15h_timeout_handling_model_v1"
    )
    timeout_detection: Literal["checked_at - started_at >= timeout_seconds"] = (
        "checked_at - started_at >= timeout_seconds"
    )
    timeout_failure_type: Literal["webhook_timeout"] = "webhook_timeout"
    timeout_marks_execution_failed: Literal[True] = True
    timeout_triggers_fallback: Literal[True] = True
    timeout_records_dlq_context: Literal[True] = True
    c15d_status_update_supported: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class DeadLetterQueueArchitecture(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    architecture_id: Literal["c15h_dead_letter_queue_v1"] = (
        "c15h_dead_letter_queue_v1"
    )
    storage_mode: Literal["in_memory_contract_store"] = "in_memory_contract_store"
    queue_key: Literal["context_id"] = "context_id"
    stored_fields: tuple[
        Literal["dlq_id"],
        Literal["context_id"],
        Literal["module"],
        Literal["workflow_id"],
        Literal["failure_type"],
        Literal["failure_reason"],
        Literal["attempt"],
        Literal["failure_context"],
        Literal["retry_decision"],
        Literal["failed_at"],
    ] = (
        "dlq_id",
        "context_id",
        "module",
        "workflow_id",
        "failure_type",
        "failure_reason",
        "attempt",
        "failure_context",
        "retry_decision",
        "failed_at",
    )
    failed_workflow_recorded: Literal[True] = True
    failure_context_id_stored: Literal[True] = True
    manual_replay_supported: Literal[True] = True
    credentials_stored: Literal[False] = False
    n8n_url_stored: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class FallbackStrategy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: Literal["c15h_fallback_strategy_v1"] = (
        "c15h_fallback_strategy_v1"
    )
    graceful_degradation_supported: Literal[True] = True
    fallback_response_generation_supported: Literal[True] = True
    module_safe_failure_return_supported: Literal[True] = True
    output_contract: Literal["C15E normalized workflow result"] = (
        "C15E normalized workflow result"
    )
    fallback_flow: tuple[str, ...] = (
        "Create a sanitized safe failure result.",
        "Normalize the fallback through the C15E result contract.",
        "Return module-safe failed status with recovery availability metadata.",
        "Avoid exposing workflow internals, credentials, or webhook references.",
    )
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False


class RecoveryFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: Literal["c15h_recovery_flow_v1"] = "c15h_recovery_flow_v1"
    manual_retry_trigger_supported: Literal[True] = True
    context_based_recovery_supported: Literal[True] = True
    reexecution_via_c15b_supported: Literal[True] = True
    flow: tuple[str, ...] = (
        "Operator selects a DLQ context_id.",
        "C15H loads the sanitized failure context.",
        "C15H builds a C15B ingress payload for the same module/workflow/context.",
        "C15B validates signature, C15A registration, and C15F binding.",
        "C15H returns the replay plan and gateway decision without dispatching n8n.",
    )
    c15b_only_reexecution_boundary: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    external_api_call_allowed: Literal[False] = False
    production_or_staging_change: Literal[False] = False


class FailureHandlingCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C15H"] = "C15H"
    component: Literal["Failure Handling & Retry System"] = (
        "Failure Handling & Retry System"
    )
    completion_status: Literal["complete"] = "complete"
    retry_system_defined: Literal[True] = True
    timeout_handling_defined: Literal[True] = True
    dead_letter_queue_defined: Literal[True] = True
    fallback_system_defined: Literal[True] = True
    recovery_mechanism_defined: Literal[True] = True
    automatic_retry_supported: Literal[True] = True
    configurable_retry_count_supported: Literal[True] = True
    exponential_backoff_supported: Literal[True] = True
    webhook_timeout_detected: Literal[True] = True
    failed_workflow_to_dlq_supported: Literal[True] = True
    manual_replay_supported: Literal[True] = True
    context_based_recovery_supported: Literal[True] = True
    reexecution_via_c15b_supported: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    no_external_api_change: Literal[True] = True
    no_external_api_call: Literal[True] = True
    no_production_change: Literal[True] = True
    no_staging_change: Literal[True] = True
    c15_full_system_complete: Literal[True] = True
    proceed_reason: str = Field(min_length=1, max_length=700)
