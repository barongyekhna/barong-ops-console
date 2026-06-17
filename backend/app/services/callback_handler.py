from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..models.execution_state import (
    CallbackStateRecord,
    CallbackStateTransitionRecord,
    DLQStateRecord,
    ExecutionCallbackRecord,
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
PLATFORM_ORG_ID = "platform"


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
    """Compatibility facade backed by callback_state, not process memory."""

    def __init__(self, *, org_id: str = PLATFORM_ORG_ID) -> None:
        self.org_id = org_id

    def clear(self) -> None:
        with _managed_session() as (db, _):
            db.execute(delete(ExecutionCallbackRecord))
            db.execute(delete(CallbackStateTransitionRecord))
            db.execute(delete(CallbackStateRecord))
            db.commit()

    def bind_execution_request(
        self,
        request: ExecutionPayloadStandardRequest,
        *,
        bound_at: str | None = None,
    ) -> CallbackContextBinding:
        record = _storage_record_from_request(request, bound_at=bound_at)
        with _managed_session() as (db, _):
            row = persist_execution_result_binding(
                db,
                org_id=self.org_id,
                record=record,
            )
            return _binding_from_persistent(row)

    def get_binding(self, context_id: str) -> CallbackContextBinding | None:
        result = self.get_result(context_id)
        if result is None:
            return None
        return _binding_from_storage_record(result)

    def get_result(self, context_id: str) -> CallbackResultStorageRecord | None:
        with _managed_session() as (db, _):
            return load_execution_result_record(db, context_id=context_id)

    def update_status_from_callback(
        self,
        payload: CallbackHandlerPayload,
    ) -> tuple[CallbackContextBinding, CallbackResultStorageRecord]:
        with _managed_session() as (db, _):
            binding, record = update_persistent_result_from_callback(
                db,
                payload=payload,
                org_id=self.org_id,
            )
            db.commit()
            return binding, record


DEFAULT_CALLBACK_EXECUTION_STORE = CallbackExecutionStore()


def reset_callback_execution_store() -> None:
    DEFAULT_CALLBACK_EXECUTION_STORE.clear()


def _storage_record_from_request(
    request: ExecutionPayloadStandardRequest,
    *,
    bound_at: str | None = None,
) -> CallbackResultStorageRecord:
    timestamp = bound_at or _utc_now_timestamp()
    return CallbackResultStorageRecord(
        context_id=request.context_id,
        module=request.module,
        task=request.task,
        workflow_id=request.workflow_id,
        status="pending",
        original_request=request,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _binding_from_storage_record(
    record: CallbackResultStorageRecord,
) -> CallbackContextBinding:
    return CallbackContextBinding(
        context_id=record.context_id,
        module=record.module,
        task=record.task,
        workflow_id=record.workflow_id,
        original_request=record.original_request,
        status=record.status,
        bound_at=record.created_at,
    )


def _binding_from_persistent(row: CallbackStateRecord) -> CallbackContextBinding:
    return _binding_from_storage_record(_storage_record_from_persistent(row))


def bind_callback_context(
    request: ExecutionPayloadStandardRequest,
    *,
    store: CallbackExecutionStore | None = None,
    db: Session | None = None,
    org_id: str | None = None,
) -> CallbackContextBinding:
    if db is None:
        target_store = store or DEFAULT_CALLBACK_EXECUTION_STORE
        binding = target_store.bind_execution_request(request)
    else:
        record = _storage_record_from_request(request)
        try:
            row = persist_execution_result_binding(
                db,
                org_id=org_id or PLATFORM_ORG_ID,
                record=record,
            )
            binding = _binding_from_persistent(row)
        except Exception:
            db.rollback()
            raise

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
    if db is None:
        target_store = store or DEFAULT_CALLBACK_EXECUTION_STORE
        binding, record = target_store.update_status_from_callback(payload)
    else:
        try:
            binding, record = update_persistent_result_from_callback(
                db,
                payload=payload,
                org_id=org_id,
                provided_signature=provided_signature,
            )
            db.commit()
        except CallbackContextBindingError as exc:
            db.rollback()
            persist_execution_dlq(
                db,
                org_id=org_id,
                payload=payload,
                reason=str(exc),
                last_error="callback_context_binding_error",
            )
            raise
        except CallbackStatusTransitionError:
            db.rollback()
            raise
        except IntegrityError:
            db.rollback()
            existing = load_execution_result_record(db, context_id=payload.context_id)
            if existing is None:
                raise CallbackStatusTransitionError(
                    "C15D callback idempotency or terminal transition conflicted."
                ) from None
            if (
                payload.status in TERMINAL_STATUSES
                and existing.status in TERMINAL_STATUSES
                and existing.status != payload.status
            ):
                raise CallbackStatusTransitionError(
                    "C15D execution already has a different terminal state."
                ) from None
            binding = _binding_from_storage_record(existing)
            record = existing
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
) -> CallbackStateRecord:
    existing = db.scalar(
        select(CallbackStateRecord).where(
            CallbackStateRecord.context_id == record.context_id
        )
    )
    if (
        existing is not None
        and record.status == "pending"
        and not _same_standard_request(
            ExecutionPayloadStandardRequest.model_validate(existing.original_request),
            record.original_request,
        )
    ):
        raise CallbackContextBindingError(
            "C15D context_id is already bound to a different C15C request."
        )
    data = {
        "org_id": org_id,
        "result_id": _stable_record_id(
            "execution_result",
            {"context_id": record.context_id, "workflow_id": record.workflow_id},
        ),
        "context_id": record.context_id,
        "execution_id": record.context_id,
        "trace_id": record.context_id,
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
        existing = CallbackStateRecord(**data)
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
    commit: bool = True,
) -> ExecutionCallbackRecord:
    payload_json = payload.model_dump(mode="json")
    digest = _payload_digest(payload)
    idempotency_key = _callback_idempotency_key(payload)
    callback_id = _stable_record_id(
        "execution_callback",
        {
            "context_id": payload.context_id,
            "workflow_id": payload.workflow_id,
            "idempotency_key": idempotency_key,
        },
    )
    record = db.scalar(
        select(ExecutionCallbackRecord).where(
            ExecutionCallbackRecord.idempotency_key == idempotency_key
        )
    )
    data = {
        "org_id": org_id,
        "callback_id": callback_id,
        "idempotency_key": idempotency_key,
        "context_id": payload.context_id,
        "execution_id": payload.context_id,
        "trace_id": payload.context_id,
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
    if commit:
        db.commit()
        db.refresh(record)
    else:
        db.flush()
    return record


def persist_execution_dlq(
    db: Session,
    *,
    org_id: str | None,
    payload: CallbackHandlerPayload,
    reason: str,
    last_error: str | None = None,
    commit: bool = True,
) -> DLQStateRecord | None:
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
        select(DLQStateRecord).where(DLQStateRecord.dlq_id == dlq_id)
    )
    data = {
        "org_id": org_id,
        "dlq_id": dlq_id,
        "context_id": payload.context_id,
        "execution_id": payload.context_id,
        "trace_id": payload.context_id,
        "module_key": payload.module,
        "workflow_id": payload.workflow_id,
        "failure_type": "callback_failed",
        "status": "retryable",
        "reason": reason,
        "payload": payload.model_dump(mode="json"),
        "failure_context": {
            "payload": payload.model_dump(mode="json"),
            "reason": reason,
        },
        "retry_decision": {},
        "attempt": 1,
        "retry_count": 0,
        "replayable": True,
        "last_error": last_error,
    }
    if record is None:
        record = DLQStateRecord(**data)
        db.add(record)
    else:
        for key, value in data.items():
            if key == "retry_count":
                continue
            setattr(record, key, value)
    if commit:
        db.commit()
        db.refresh(record)
    else:
        db.flush()
    return record


def load_execution_result_org_id(
    db: Session,
    *,
    context_id: str,
) -> str | None:
    row = db.scalar(
        select(CallbackStateRecord.org_id).where(
            CallbackStateRecord.context_id == context_id
        )
    )
    return row


def load_execution_result_record(
    db: Session,
    *,
    context_id: str,
) -> CallbackResultStorageRecord | None:
    row = db.scalar(
        select(CallbackStateRecord).where(
            CallbackStateRecord.context_id == context_id
        )
    )
    if row is None:
        return None
    return _storage_record_from_persistent(row)


def update_persistent_result_from_callback(
    db: Session,
    *,
    payload: CallbackHandlerPayload,
    org_id: str | None = None,
    provided_signature: str | None = None,
) -> tuple[CallbackContextBinding, CallbackResultStorageRecord]:
    row = db.scalar(
        select(CallbackStateRecord)
        .where(CallbackStateRecord.context_id == payload.context_id)
        .with_for_update()
    )
    if row is None:
        raise CallbackContextBindingError(
            "C15D callback context_id is not bound to a durable execution result."
        )
    record = _storage_record_from_persistent(row)
    binding = _binding_from_storage_record(record)
    if payload.module != binding.module:
        raise CallbackContextBindingError(
            "C15D callback module does not match the bound C15C request."
        )
    if payload.workflow_id != binding.workflow_id:
        raise CallbackContextBindingError(
            "C15D callback workflow_id does not match the bound C15C request."
        )

    idempotency_key = _callback_idempotency_key(payload)
    existing_callback = db.scalar(
        select(ExecutionCallbackRecord).where(
            ExecutionCallbackRecord.idempotency_key == idempotency_key
        )
    )
    if existing_callback is not None:
        return binding, record

    persist_execution_callback(
        db,
        org_id=org_id or row.org_id,
        payload=payload,
        provided_signature=provided_signature,
        commit=False,
    )

    if payload.status not in ALLOWED_STATUS_TRANSITIONS[record.status]:
        raise CallbackStatusTransitionError(
            "C15D status transition is not allowed: "
            f"{record.status} -> {payload.status}."
        )

    received_at = _utc_now_timestamp()
    started_at = record.started_at
    completed_at = record.completed_at
    if payload.status in ("running", "success", "failed") and started_at is None:
        started_at = received_at
    if payload.status in TERMINAL_STATUSES and completed_at is None:
        completed_at = received_at

    status_changed = payload.status != record.status
    if status_changed:
        db.add(
            CallbackStateTransitionRecord(
                transition_id=_stable_record_id(
                    "callback_transition",
                    {
                        "execution_id": row.execution_id,
                        "idempotency_key": idempotency_key,
                    },
                ),
                context_id=row.context_id,
                execution_id=row.execution_id,
                from_status=record.status,
                to_status=payload.status,
                idempotency_key=idempotency_key,
                payload_digest=_payload_digest(payload),
                created_at=datetime.now(UTC),
            )
        )

    row.status = payload.status
    row.workflow_output = payload.output
    row.execution_metadata = payload.execution_metadata
    row.callbacks_received = record.callbacks_received + 1
    row.signature_validated = True
    row.payload_validated = True
    row.started_at = _parse_optional_timestamp(started_at)
    row.completed_at = _parse_optional_timestamp(completed_at)
    db.flush()
    updated_record = _storage_record_from_persistent(row)
    return _binding_from_storage_record(updated_record), updated_record


def retry_execution_dlq(
    db: Session,
    *,
    dlq_id: str,
) -> DLQStateRecord:
    row = db.scalar(select(DLQStateRecord).where(DLQStateRecord.dlq_id == dlq_id))
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
) -> DLQStateRecord:
    row = db.scalar(select(DLQStateRecord).where(DLQStateRecord.dlq_id == dlq_id))
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
    row: CallbackStateRecord,
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


@contextmanager
def _managed_session(db: Session | None = None):
    if db is not None:
        yield db, False
        return

    from ..db.session import SessionLocal

    with SessionLocal() as session:
        yield session, True


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
