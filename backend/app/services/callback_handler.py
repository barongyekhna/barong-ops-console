from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

from ..core.config import Settings
from ..schemas.callback_handler import (
    CallbackContextBinding,
    CallbackContextBindingModel,
    CallbackExecutionStatus,
    CallbackHandlerCompletionStatus,
    CallbackHandlerDesign,
    CallbackHandlerPayload,
    CallbackHandlerResult,
    CallbackModuleFamily,
    CallbackModuleNotification,
    CallbackModuleNotificationModel,
    CallbackResultStorageModel,
    CallbackResultStorageRecord,
    CallbackStandardizedModuleResult,
    CallbackStatusManagementModel,
)
from ..schemas.execution_payload_standardization import (
    ExecutionPayloadStandardRequest,
)
from .webhook_gateway import SIGNATURE_PREFIX


ALLOWED_STATUS_TRANSITIONS: dict[
    CallbackExecutionStatus,
    tuple[CallbackExecutionStatus, ...],
] = {
    "pending": ("pending", "running", "success", "failed"),
    "running": ("running", "success", "failed"),
    "success": ("success",),
    "failed": ("failed",),
}
TERMINAL_STATUSES = frozenset(("success", "failed"))


class CallbackHandlerConfigurationError(RuntimeError):
    pass


class CallbackHandlerSignatureError(RuntimeError):
    pass


class CallbackContextBindingError(RuntimeError):
    pass


class CallbackStatusTransitionError(RuntimeError):
    pass


def _secret_value(value: SecretStr | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)


def _utc_now_timestamp() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def canonical_callback_payload(payload: CallbackHandlerPayload) -> str:
    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def sign_callback_payload(
    payload: CallbackHandlerPayload,
    *,
    secret: SecretStr | str,
) -> str:
    secret_text = _secret_value(secret)
    digest = hmac.new(
        secret_text.encode("utf-8"),
        canonical_callback_payload(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_callback_signature(
    payload: CallbackHandlerPayload,
    *,
    provided_signature: str | None,
    settings: Settings,
) -> None:
    secret = _secret_value(settings.webhook_gateway_signing_secret)
    if not secret:
        raise CallbackHandlerConfigurationError(
            "C15D callback signing secret is not configured."
        )
    if not provided_signature:
        raise CallbackHandlerSignatureError(
            "C15D callback signature is required."
        )

    expected_signature = sign_callback_payload(payload, secret=secret)
    candidate = provided_signature.strip()
    if not candidate.startswith(SIGNATURE_PREFIX):
        candidate = f"{SIGNATURE_PREFIX}{candidate}"
    if not hmac.compare_digest(candidate, expected_signature):
        raise CallbackHandlerSignatureError(
            "C15D callback signature is invalid."
        )

    signed_at = _parse_timestamp(payload.timestamp)
    age_seconds = abs((datetime.now(UTC) - signed_at).total_seconds())
    if age_seconds > settings.webhook_gateway_signature_tolerance_seconds:
        raise CallbackHandlerSignatureError(
            "C15D callback timestamp is outside the accepted window."
        )


def _module_family(module: str) -> CallbackModuleFamily:
    normalized = module.lower().replace("_", ".")
    if normalized.startswith(("k.", "business.k.")) or ".k." in normalized:
        return "K"
    if normalized.startswith(("seo.", "business.seo.")) or ".seo." in normalized:
        return "SEO"
    if (
        normalized.startswith(("p.", "business.p.", "products."))
        or normalized == "business.products"
        or ".products" in normalized
    ):
        return "P"
    return "generic"


def _same_standard_request(
    left: ExecutionPayloadStandardRequest,
    right: ExecutionPayloadStandardRequest,
) -> bool:
    return left.model_dump(mode="json") == right.model_dump(mode="json")


class CallbackExecutionStore:
    def __init__(self) -> None:
        self._bindings: dict[str, CallbackContextBinding] = {}
        self._records: dict[str, CallbackResultStorageRecord] = {}

    def clear(self) -> None:
        self._bindings.clear()
        self._records.clear()

    def bind_execution_request(
        self,
        request: ExecutionPayloadStandardRequest,
        *,
        bound_at: str | None = None,
    ) -> CallbackContextBinding:
        context_id = request.context_id
        existing = self._bindings.get(context_id)
        if existing is not None:
            if not _same_standard_request(existing.original_request, request):
                raise CallbackContextBindingError(
                    "C15D context_id is already bound to a different C15C request."
                )
            return existing

        timestamp = bound_at or _utc_now_timestamp()
        binding = CallbackContextBinding(
            context_id=context_id,
            module=request.module,
            task=request.task,
            workflow_id=request.workflow_id,
            original_request=request,
            bound_at=timestamp,
        )
        self._bindings[context_id] = binding
        self._records[context_id] = CallbackResultStorageRecord(
            context_id=context_id,
            module=request.module,
            task=request.task,
            workflow_id=request.workflow_id,
            status="pending",
            original_request=request,
            created_at=timestamp,
            updated_at=timestamp,
        )
        return binding

    def get_binding(self, context_id: str) -> CallbackContextBinding | None:
        return self._bindings.get(context_id)

    def get_result(self, context_id: str) -> CallbackResultStorageRecord | None:
        return self._records.get(context_id)

    def update_status_from_callback(
        self,
        payload: CallbackHandlerPayload,
    ) -> tuple[CallbackContextBinding, CallbackResultStorageRecord]:
        binding = self._bindings.get(payload.context_id)
        if binding is None:
            raise CallbackContextBindingError(
                "C15D callback context_id is not bound to a C15C execution request."
            )
        if payload.module != binding.module:
            raise CallbackContextBindingError(
                "C15D callback module does not match the bound C15C request."
            )
        if payload.workflow_id != binding.workflow_id:
            raise CallbackContextBindingError(
                "C15D callback workflow_id does not match the bound C15C request."
            )

        record = self._records[payload.context_id]
        if payload.status not in ALLOWED_STATUS_TRANSITIONS[record.status]:
            raise CallbackStatusTransitionError(
                "C15D status transition is not allowed: "
                f"{record.status} -> {payload.status}."
            )

        if record.status in TERMINAL_STATUSES and payload.status == record.status:
            return binding, record

        received_at = _utc_now_timestamp()
        started_at = record.started_at
        completed_at = record.completed_at
        if payload.status in ("running", "success", "failed") and started_at is None:
            started_at = received_at
        if payload.status in TERMINAL_STATUSES:
            completed_at = received_at

        updated_record = record.model_copy(
            update={
                "status": payload.status,
                "workflow_output": payload.output,
                "execution_metadata": payload.execution_metadata,
                "updated_at": received_at,
                "started_at": started_at,
                "completed_at": completed_at,
                "callbacks_received": record.callbacks_received + 1,
                "signature_validated": True,
                "payload_validated": True,
            }
        )
        updated_binding = binding.model_copy(update={"status": payload.status})
        self._records[payload.context_id] = updated_record
        self._bindings[payload.context_id] = updated_binding
        return updated_binding, updated_record


DEFAULT_CALLBACK_EXECUTION_STORE = CallbackExecutionStore()


def reset_callback_execution_store() -> None:
    DEFAULT_CALLBACK_EXECUTION_STORE.clear()


def bind_callback_context(
    request: ExecutionPayloadStandardRequest,
    *,
    store: CallbackExecutionStore | None = None,
) -> CallbackContextBinding:
    target_store = store or DEFAULT_CALLBACK_EXECUTION_STORE
    return target_store.bind_execution_request(request)


def get_callback_result(
    context_id: str,
    *,
    store: CallbackExecutionStore | None = None,
) -> CallbackResultStorageRecord | None:
    target_store = store or DEFAULT_CALLBACK_EXECUTION_STORE
    return target_store.get_result(context_id)


def _build_module_notification(
    record: CallbackResultStorageRecord,
) -> CallbackModuleNotification:
    family = _module_family(record.module)
    standardized_result = CallbackStandardizedModuleResult(
        context_id=record.context_id,
        module=record.module,
        module_family=family,
        workflow_id=record.workflow_id,
        status=record.status,
        output=record.workflow_output,
        execution_metadata=record.execution_metadata,
        updated_at=record.updated_at,
    )
    return CallbackModuleNotification(
        module=record.module,
        module_family=family,
        context_id=record.context_id,
        standardized_result=standardized_result,
    )


def handle_callback(
    payload: CallbackHandlerPayload,
    *,
    provided_signature: str | None,
    settings: Settings,
    store: CallbackExecutionStore | None = None,
) -> CallbackHandlerResult:
    verify_callback_signature(
        payload,
        provided_signature=provided_signature,
        settings=settings,
    )
    target_store = store or DEFAULT_CALLBACK_EXECUTION_STORE
    binding, record = target_store.update_status_from_callback(payload)
    notification = _build_module_notification(record)
    return CallbackHandlerResult(
        processing_status="accepted",
        reason=(
            "C15D validated the callback payload and signature, bound it to the "
            "C15C execution request by context_id, updated status/result storage, "
            "and prepared the module notification without triggering execution."
        ),
        context_binding=binding,
        status=record.status,
        stored_result=record,
        module_notification=notification,
    )


def update_execution_status(
    context_id: str,
    status: CallbackExecutionStatus,
    *,
    output: dict[str, Any] | None = None,
    execution_metadata: dict[str, Any] | None = None,
    store: CallbackExecutionStore | None = None,
) -> CallbackResultStorageRecord:
    target_store = store or DEFAULT_CALLBACK_EXECUTION_STORE
    record = target_store.get_result(context_id)
    if record is None:
        raise CallbackContextBindingError(
            "C15D status update context_id is not bound to a C15C execution request."
        )
    payload = CallbackHandlerPayload(
        module=record.module,
        workflow_id=record.workflow_id,
        context_id=context_id,
        status=status,
        output=output or record.workflow_output,
        execution_metadata=execution_metadata or record.execution_metadata,
        timestamp=_utc_now_timestamp(),
    )
    _, updated_record = target_store.update_status_from_callback(payload)
    return updated_record


def get_callback_handler_design() -> CallbackHandlerDesign:
    return CallbackHandlerDesign()


def get_context_binding_model() -> CallbackContextBindingModel:
    return CallbackContextBindingModel()


def get_status_management_model() -> CallbackStatusManagementModel:
    return CallbackStatusManagementModel()


def get_result_storage_model() -> CallbackResultStorageModel:
    return CallbackResultStorageModel()


def get_module_notification_model() -> CallbackModuleNotificationModel:
    return CallbackModuleNotificationModel()


def get_callback_handler_completion_status() -> CallbackHandlerCompletionStatus:
    return CallbackHandlerCompletionStatus(
        proceed_reason=(
            "C15D implements the signed callback receiver, C15C context binding, "
            "pending/running/success/failed status manager, result storage model, "
            "and K/P/SEO module notification contract without execution triggers "
            "or external API calls."
        )
    )
