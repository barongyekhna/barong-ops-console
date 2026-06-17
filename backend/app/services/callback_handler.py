from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..models.execution_state import (
    ExecutionCallbackRecord,
    ExecutionDLQRecord,
    ExecutionResultRecord,
)
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
from .event_collector import record_workflow_event
from .replay_protection import ReplayProtectionError, register_replay_key
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


class CallbackHandlerReplayError(RuntimeError):
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
        payload.model_dump(mode="json", exclude_none=True),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _payload_digest(payload: CallbackHandlerPayload) -> str:
    return hashlib.sha256(
        canonical_callback_payload(payload).encode("utf-8")
    ).hexdigest()


def _stable_record_id(prefix: str, value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{prefix}_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:24]}"


def _callback_nonce_key(payload: CallbackHandlerPayload) -> str:
    nonce = payload.nonce or f"legacy-sha256:{_payload_digest(payload)}"
    return f"{payload.module}:{payload.workflow_id}:{payload.context_id}:{nonce}"


def _callback_idempotency_key(payload: CallbackHandlerPayload) -> str:
    key = payload.idempotency_key or f"legacy-sha256:{_payload_digest(payload)}"
    return f"{payload.module}:{payload.workflow_id}:{payload.context_id}:{key}"


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
    db: Session | None = None,
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

    try:
        register_replay_key(
            scope="c15d.callback_nonce",
            key=_callback_nonce_key(payload),
            payload_digest=_payload_digest(payload),
            ttl_seconds=settings.webhook_replay_nonce_ttl_seconds,
            db=db,
        )
        register_replay_key(
            scope="c15d.callback_idempotency",
            key=_callback_idempotency_key(payload),
            payload_digest=_payload_digest(payload),
            ttl_seconds=settings.webhook_replay_nonce_ttl_seconds,
            db=db,
        )
    except ReplayProtectionError as exc:
        raise CallbackHandlerReplayError(str(exc)) from None


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
    db: Session | None = None,
    org_id: str | None = None,
) -> CallbackContextBinding:
    target_store = store or DEFAULT_CALLBACK_EXECUTION_STORE
    binding = target_store.bind_execution_request(request)
    record = target_store.get_result(request.context_id)
    if db is not None and org_id is not None and record is not None:
        persist_execution_result_binding(db, org_id=org_id, record=record)
    record_workflow_event(
        event_type="workflow.execution.start",
        action="workflow.execution.start",
        context_id=binding.context_id,
        workflow_id=binding.workflow_id,
        module_key=binding.module,
        status="pending",
        source="backend",
        payload={"task": binding.task},
    )
    return binding


def get_callback_result(
    context_id: str,
    *,
    store: CallbackExecutionStore | None = None,
    db: Session | None = None,
) -> CallbackResultStorageRecord | None:
    if db is not None:
        persistent = load_execution_result_record(db, context_id=context_id)
        if persistent is not None:
            return persistent
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
    db: Session | None = None,
    org_id: str | None = None,
    store: CallbackExecutionStore | None = None,
) -> CallbackHandlerResult:
    verify_callback_signature(
        payload,
        provided_signature=provided_signature,
        settings=settings,
        db=db,
    )
    target_store = store or DEFAULT_CALLBACK_EXECUTION_STORE
    try:
        binding, record = target_store.update_status_from_callback(payload)
    except CallbackContextBindingError as exc:
        if db is None:
            raise
        try:
            binding, record = update_persistent_result_from_callback(
                db,
                payload=payload,
            )
        except CallbackContextBindingError:
            persist_execution_dlq(
                db,
                org_id=org_id,
                payload=payload,
                reason=str(exc),
                last_error="callback_context_binding_error",
            )
            raise

    if db is not None:
        callback_org_id = org_id or load_execution_result_org_id(
            db,
            context_id=payload.context_id,
        )
        if callback_org_id is not None:
            persist_execution_callback(
                db,
                org_id=callback_org_id,
                payload=payload,
                provided_signature=provided_signature,
            )
            persist_execution_result_binding(
                db,
                org_id=callback_org_id,
                record=record,
            )
    notification = _build_module_notification(record)
    record_workflow_event(
        event_type=(
            "workflow.execution.end"
            if record.status in TERMINAL_STATUSES
            else "workflow.execution.status"
        ),
        action="workflow.execution.status",
        context_id=record.context_id,
        workflow_id=record.workflow_id,
        module_key=record.module,
        status="failed" if record.status == "failed" else "success",
        source="n8n",
        payload={
            "execution_status": record.status,
            "callbacks_received": record.callbacks_received,
        },
    )
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
    record_workflow_event(
        event_type=(
            "workflow.execution.end"
            if updated_record.status in TERMINAL_STATUSES
            else "workflow.execution.status"
        ),
        action="workflow.execution.status",
        context_id=updated_record.context_id,
        workflow_id=updated_record.workflow_id,
        module_key=updated_record.module,
        status="failed" if updated_record.status == "failed" else "success",
        source="backend",
        payload={"execution_status": updated_record.status},
    )
    return updated_record


def persist_execution_result_binding(
    db: Session,
    *,
    org_id: str,
    record: CallbackResultStorageRecord,
) -> ExecutionResultRecord:
    existing = db.scalar(
        select(ExecutionResultRecord).where(
            ExecutionResultRecord.context_id == record.context_id
        )
    )
    data = {
        "org_id": org_id,
        "result_id": _stable_record_id(
            "execution_result",
            {"context_id": record.context_id, "workflow_id": record.workflow_id},
        ),
        "context_id": record.context_id,
        "execution_id": record.context_id,
        "module_key": record.module,
        "task": record.task,
        "workflow_id": record.workflow_id,
        "status": record.status,
        "original_request": record.original_request.model_dump(mode="json"),
        "workflow_output": record.workflow_output,
        "execution_metadata": record.execution_metadata,
        "callbacks_received": record.callbacks_received,
        "signature_validated": record.signature_validated,
        "payload_validated": record.payload_validated,
        "started_at": _parse_optional_timestamp(record.started_at),
        "completed_at": _parse_optional_timestamp(record.completed_at),
    }
    if existing is None:
        existing = ExecutionResultRecord(**data)
        db.add(existing)
    else:
        for key, value in data.items():
            if key == "result_id":
                continue
            setattr(existing, key, value)
    db.commit()
    db.refresh(existing)
    return existing


def persist_execution_callback(
    db: Session,
    *,
    org_id: str,
    payload: CallbackHandlerPayload,
    provided_signature: str | None,
) -> ExecutionCallbackRecord:
    payload_json = payload.model_dump(mode="json")
    digest = _payload_digest(payload)
    callback_id = _stable_record_id(
        "execution_callback",
        {
            "context_id": payload.context_id,
            "workflow_id": payload.workflow_id,
            "digest": digest,
            "status": payload.status,
        },
    )
    record = db.scalar(
        select(ExecutionCallbackRecord).where(
            ExecutionCallbackRecord.callback_id == callback_id
        )
    )
    data = {
        "org_id": org_id,
        "callback_id": callback_id,
        "context_id": payload.context_id,
        "execution_id": payload.context_id,
        "module_key": payload.module,
        "workflow_id": payload.workflow_id,
        "status": payload.status,
        "signature_status": "validated" if provided_signature else "missing",
        "payload_digest": digest,
        "payload": payload_json,
        "validation_result": {
            "signature_validated": True,
            "payload_validated": True,
            "runtime_execution_allowed": False,
        },
        "received_at": datetime.now(UTC),
    }
    if record is None:
        record = ExecutionCallbackRecord(**data)
        db.add(record)
    else:
        for key, value in data.items():
            setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


def persist_execution_dlq(
    db: Session,
    *,
    org_id: str | None,
    payload: CallbackHandlerPayload,
    reason: str,
    last_error: str | None = None,
) -> ExecutionDLQRecord | None:
    if org_id is None:
        return None
    dlq_id = _stable_record_id(
        "execution_dlq",
        {
            "context_id": payload.context_id,
            "workflow_id": payload.workflow_id,
            "reason": reason,
        },
    )
    record = db.scalar(
        select(ExecutionDLQRecord).where(ExecutionDLQRecord.dlq_id == dlq_id)
    )
    data = {
        "org_id": org_id,
        "dlq_id": dlq_id,
        "context_id": payload.context_id,
        "execution_id": payload.context_id,
        "module_key": payload.module,
        "workflow_id": payload.workflow_id,
        "status": "retryable",
        "reason": reason,
        "payload": payload.model_dump(mode="json"),
        "retry_count": 0,
        "replayable": True,
        "last_error": last_error,
    }
    if record is None:
        record = ExecutionDLQRecord(**data)
        db.add(record)
    else:
        for key, value in data.items():
            if key == "retry_count":
                continue
            setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


def load_execution_result_org_id(
    db: Session,
    *,
    context_id: str,
) -> str | None:
    row = db.scalar(
        select(ExecutionResultRecord.org_id).where(
            ExecutionResultRecord.context_id == context_id
        )
    )
    return row


def load_execution_result_record(
    db: Session,
    *,
    context_id: str,
) -> CallbackResultStorageRecord | None:
    row = db.scalar(
        select(ExecutionResultRecord).where(
            ExecutionResultRecord.context_id == context_id
        )
    )
    if row is None:
        return None
    return _storage_record_from_persistent(row)


def update_persistent_result_from_callback(
    db: Session,
    *,
    payload: CallbackHandlerPayload,
) -> tuple[CallbackContextBinding, CallbackResultStorageRecord]:
    row = db.scalar(
        select(ExecutionResultRecord).where(
            ExecutionResultRecord.context_id == payload.context_id
        )
    )
    if row is None:
        raise CallbackContextBindingError(
            "C15D callback context_id is not bound to a durable execution result."
        )
    record = _storage_record_from_persistent(row)
    binding = CallbackContextBinding(
        context_id=record.context_id,
        module=record.module,
        task=record.task,
        workflow_id=record.workflow_id,
        original_request=record.original_request,
        status=record.status,
        bound_at=record.created_at,
    )
    temporary_store = CallbackExecutionStore()
    temporary_store._bindings[payload.context_id] = binding
    temporary_store._records[payload.context_id] = record
    updated_binding, updated_record = temporary_store.update_status_from_callback(
        payload
    )
    persist_execution_result_binding(db, org_id=row.org_id, record=updated_record)
    return updated_binding, updated_record


def retry_execution_dlq(
    db: Session,
    *,
    dlq_id: str,
) -> ExecutionDLQRecord:
    row = db.scalar(select(ExecutionDLQRecord).where(ExecutionDLQRecord.dlq_id == dlq_id))
    if row is None:
        raise CallbackContextBindingError("Execution DLQ record was not found.")
    row.retry_count += 1
    row.status = "retry_scheduled"
    row.retry_after = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row


def replay_execution_dlq(
    db: Session,
    *,
    dlq_id: str,
) -> ExecutionDLQRecord:
    row = db.scalar(select(ExecutionDLQRecord).where(ExecutionDLQRecord.dlq_id == dlq_id))
    if row is None:
        raise CallbackContextBindingError("Execution DLQ record was not found.")
    if not row.replayable:
        raise CallbackStatusTransitionError("Execution DLQ record is not replayable.")
    row.status = "replay_ready"
    row.retry_count += 1
    db.commit()
    db.refresh(row)
    return row


def _parse_optional_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return _parse_timestamp(value)


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def _storage_record_from_persistent(
    row: ExecutionResultRecord,
) -> CallbackResultStorageRecord:
    return CallbackResultStorageRecord(
        context_id=row.context_id,
        module=row.module_key,
        task=row.task,
        workflow_id=row.workflow_id,
        status=row.status,
        original_request=ExecutionPayloadStandardRequest.model_validate(
            row.original_request
        ),
        workflow_output=row.workflow_output,
        execution_metadata=row.execution_metadata,
        created_at=_format_timestamp(row.created_at) or _utc_now_timestamp(),
        updated_at=_format_timestamp(row.updated_at) or _utc_now_timestamp(),
        started_at=_format_timestamp(row.started_at),
        completed_at=_format_timestamp(row.completed_at),
        callbacks_received=row.callbacks_received,
        signature_validated=row.signature_validated,
        payload_validated=row.payload_validated,
    )


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
