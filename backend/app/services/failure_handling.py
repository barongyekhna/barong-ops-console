from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..models.execution_state import DLQStateRecord
from ..schemas.failure_handling import (
    DeadLetterQueueArchitecture,
    DeadLetterQueueResponse,
    DeadLetterQueueStatus,
    DeadLetterRecord,
    FailureHandlingCompletionStatus,
    FailureHandlingOutcome,
    FailureHandlingRequest,
    FailureRetryDecision,
    FailureRetryPolicy,
    FallbackResponse,
    FallbackStrategy,
    ManualReplayRequest,
    RecoveryFlow,
    RecoveryPlan,
    RetryDecisionStatus,
    RetrySystemDesign,
    TimeoutEvaluationRequest,
    TimeoutHandlingDecision,
    TimeoutHandlingModel,
)
from ..schemas.webhook_gateway import WebhookGatewayRequest
from .callback_handler import (
    CallbackContextBindingError,
    CallbackStatusTransitionError,
    PLATFORM_ORG_ID,
    update_execution_status,
)
from .event_collector import record_workflow_event
from .result_normalization import normalize_workflow_result
from .webhook_gateway import (
    WebhookGatewayConfigurationError,
    WebhookGatewaySignatureError,
    build_webhook_gateway_decision,
    sign_webhook_gateway_payload,
)


class FailureRecoveryError(RuntimeError):
    pass


def _secret_value(value: SecretStr | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _utc_now_timestamp() -> str:
    return _timestamp(_utc_now())


def _timestamp(value: datetime) -> str:
    normalized = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=UTC)
    return (
        normalized.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _backoff_seconds(attempt: int, policy: FailureRetryPolicy) -> int:
    computed = policy.initial_backoff_seconds * (
        policy.backoff_multiplier ** max(attempt - 1, 0)
    )
    return min(int(computed), policy.max_backoff_seconds)


def _dlq_id(
    *,
    context_id: str,
    module: str,
    workflow_id: str,
) -> str:
    digest = hashlib.sha256(
        _canonical_json(
            {
                "context_id": context_id,
                "module": module,
                "workflow_id": workflow_id,
            }
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"dlq.c15h.{digest}"


def _build_retry_decision(
    request: FailureHandlingRequest,
    *,
    now: datetime,
) -> FailureRetryDecision:
    policy = request.retry_policy
    retryable = request.failure_type in policy.retryable_failure_types
    retry_allowed = (
        policy.automatic_retry_enabled
        and retryable
        and request.attempt < policy.max_attempts
    )

    if retry_allowed:
        backoff = _backoff_seconds(request.attempt, policy)
        next_retry = now + timedelta(seconds=backoff)
        return FailureRetryDecision(
            context_id=request.context_id,
            module=request.module,
            workflow_id=request.workflow_id,
            failure_type=request.failure_type,
            retry_status="retry_scheduled",
            attempt=request.attempt,
            next_attempt=request.attempt + 1,
            max_attempts=policy.max_attempts,
            automatic_retry_enabled=policy.automatic_retry_enabled,
            retry_allowed=True,
            backoff_seconds=backoff,
            next_retry_after=_timestamp(next_retry),
            exponential_backoff_applied=True,
            reason=(
                "C15H scheduled an automatic retry using conceptual exponential "
                "backoff. Runtime dispatch remains blocked until C15B re-entry."
            ),
        )

    if not policy.automatic_retry_enabled or not retryable:
        return FailureRetryDecision(
            context_id=request.context_id,
            module=request.module,
            workflow_id=request.workflow_id,
            failure_type=request.failure_type,
            retry_status="not_retryable",
            attempt=request.attempt,
            max_attempts=policy.max_attempts,
            automatic_retry_enabled=policy.automatic_retry_enabled,
            retry_allowed=False,
            exponential_backoff_applied=False,
            reason=(
                "C15H did not schedule an automatic retry because the failure "
                "is not retryable or automatic retry is disabled."
            ),
        )

    return FailureRetryDecision(
        context_id=request.context_id,
        module=request.module,
        workflow_id=request.workflow_id,
        failure_type=request.failure_type,
        retry_status="retry_exhausted",
        attempt=request.attempt,
        max_attempts=policy.max_attempts,
        automatic_retry_enabled=policy.automatic_retry_enabled,
        retry_allowed=False,
        exponential_backoff_applied=False,
        reason=(
            "C15H exhausted the configured retry count and moved the failure "
            "context to DLQ for manual recovery."
        ),
    )


def _dlq_status(retry_status: RetryDecisionStatus) -> DeadLetterQueueStatus:
    if retry_status == "retry_scheduled":
        return "retry_pending"
    return "queued"


class DeadLetterQueueStore:
    """DB-backed DLQ facade; dlq_state is the source of truth."""

    def __init__(
        self,
        *,
        db: Session | None = None,
        org_id: str = PLATFORM_ORG_ID,
    ) -> None:
        self._db = db
        self.org_id = org_id

    def clear(self) -> None:
        with self._session() as db:
            db.execute(delete(DLQStateRecord))
            db.commit()

    def list_records(self) -> list[DeadLetterRecord]:
        with self._session() as db:
            rows = tuple(
                db.scalars(
                    select(DLQStateRecord)
                    .where(DLQStateRecord.org_id == self.org_id)
                    .order_by(DLQStateRecord.created_at.desc(), DLQStateRecord.id.desc())
                )
            )
        records: list[DeadLetterRecord] = []
        for row in rows:
            if row.context_id is None or row.workflow_id is None:
                continue
            try:
                records.append(_dead_letter_record_from_row(row))
            except ValueError:
                continue
        return records

    def get(self, context_id: str) -> DeadLetterRecord | None:
        with self._session() as db:
            row = db.scalar(
                select(DLQStateRecord)
                .where(
                    DLQStateRecord.org_id == self.org_id,
                    DLQStateRecord.context_id == context_id,
                )
                .order_by(DLQStateRecord.created_at.desc(), DLQStateRecord.id.desc())
                .limit(1)
            )
        if row is None or row.context_id is None or row.workflow_id is None:
            return None
        try:
            return _dead_letter_record_from_row(row)
        except ValueError:
            return None

    def get_row(self, context_id: str) -> DLQStateRecord | None:
        with self._session() as db:
            return db.scalar(
                select(DLQStateRecord)
                .where(
                    DLQStateRecord.org_id == self.org_id,
                    DLQStateRecord.context_id == context_id,
                )
                .order_by(DLQStateRecord.created_at.desc(), DLQStateRecord.id.desc())
                .limit(1)
            )

    def record_failure(
        self,
        request: FailureHandlingRequest,
        *,
        retry_decision: FailureRetryDecision,
        failed_at: str,
    ) -> DeadLetterRecord:
        failure_context = {
            "task": request.task,
            "payload": request.payload,
            "failure_type": request.failure_type,
            "attempt": request.attempt,
        }
        dlq_id = _dlq_id(
            context_id=request.context_id,
            module=request.module,
            workflow_id=request.workflow_id,
        )
        with self._session() as db:
            row = db.scalar(
                select(DLQStateRecord).where(DLQStateRecord.dlq_id == dlq_id)
            )
            if row is None:
                row = DLQStateRecord(
                    org_id=self.org_id,
                    dlq_id=dlq_id,
                    context_id=request.context_id,
                    execution_id=request.context_id,
                    trace_id=request.context_id,
                    module_key=request.module,
                    workflow_id=request.workflow_id,
                    failure_type=request.failure_type,
                    status=_dlq_status(retry_decision.retry_status),
                    reason=request.reason,
                    payload=request.payload,
                    failure_context=failure_context,
                    retry_decision=retry_decision.model_dump(mode="json"),
                    attempt=request.attempt,
                    retry_count=max(request.attempt - 1, 0),
                    retry_after=_parse_optional_timestamp(
                        retry_decision.next_retry_after
                    ),
                    replay_count=0,
                    replayable=True,
                )
                db.add(row)
            else:
                row.status = _dlq_status(retry_decision.retry_status)
                row.reason = request.reason
                row.payload = request.payload
                row.failure_context = failure_context
                row.retry_decision = retry_decision.model_dump(mode="json")
                row.attempt = request.attempt
                row.retry_count = max(request.attempt - 1, row.retry_count)
                row.retry_after = _parse_optional_timestamp(
                    retry_decision.next_retry_after
                )
                row.replayable = True
            db.commit()
            db.refresh(row)
            return _dead_letter_record_from_row(row)

    def mark_replayed(
        self,
        record: DeadLetterRecord,
        *,
        replayed_at: str,
    ) -> DeadLetterRecord:
        with self._session() as db:
            row = db.scalar(
                select(DLQStateRecord).where(DLQStateRecord.dlq_id == record.dlq_id)
            )
            if row is None:
                return record
            row.status = "replayed"
            row.replay_count = record.replay_count + 1
            row.last_replayed_at = _parse_timestamp(replayed_at)
            db.commit()
            db.refresh(row)
            return _dead_letter_record_from_row(row)

    def _session(self):
        if self._db is not None:
            class _ExistingSession:
                def __enter__(_self) -> Session:
                    return self._db  # type: ignore[return-value]

                def __exit__(_self, *_exc: object) -> None:
                    return None

            return _ExistingSession()

        from ..db.session import SessionLocal

        return SessionLocal()


DEFAULT_DEAD_LETTER_QUEUE = DeadLetterQueueStore()


def reset_dead_letter_queue() -> None:
    DEFAULT_DEAD_LETTER_QUEUE.clear()


def _parse_optional_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return _parse_timestamp(value)


def _format_optional_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _timestamp(value)


def _dead_letter_record_from_row(row: DLQStateRecord) -> DeadLetterRecord:
    retry_decision = FailureRetryDecision.model_validate(row.retry_decision)
    context_id = row.context_id or retry_decision.context_id
    module = row.module_key or retry_decision.module
    workflow_id = row.workflow_id or retry_decision.workflow_id
    failure_type = row.failure_type or retry_decision.failure_type
    return DeadLetterRecord(
        dlq_id=row.dlq_id,
        context_id=context_id,
        module=module,
        workflow_id=workflow_id,
        failure_type=failure_type,  # type: ignore[arg-type]
        failure_reason=row.reason,
        attempt=row.attempt,
        status=row.status,  # type: ignore[arg-type]
        failure_context=dict(row.failure_context),
        retry_decision=retry_decision,
        failed_at=_timestamp(row.created_at),
        replay_count=row.replay_count,
        last_replayed_at=_format_optional_timestamp(row.last_replayed_at),
    )


def _build_fallback_response(request: FailureHandlingRequest) -> FallbackResponse:
    safe_result = {
        "context_id": request.context_id,
        "module": request.module,
        "workflow_id": request.workflow_id,
        "status": "failed",
        "result": {
            "summary": "Workflow execution failed safely.",
            "items": [],
            "data": {
                "failure_type": request.failure_type,
                "attempt": request.attempt,
                "recovery_available": True,
                "safe_failure": True,
            },
        },
    }
    normalized_result = normalize_workflow_result(
        safe_result,
        context_id=request.context_id,
        module=request.module,
        workflow_id=request.workflow_id,
        status="failed",
    )
    return FallbackResponse(
        context_id=request.context_id,
        module=request.module,
        workflow_id=request.workflow_id,
        safe_message=(
            "Workflow execution failed safely; a fallback response was returned."
        ),
        normalized_result=normalized_result,
    )


def _mark_execution_failed(
    request: FailureHandlingRequest,
) -> tuple[bool, str]:
    try:
        update_execution_status(
            request.context_id,
            "failed",
            output={
                "summary": "Workflow execution failed safely.",
                "data": {
                    "failure_type": request.failure_type,
                    "safe_failure": True,
                },
            },
            execution_metadata={
                "failure_stage": "C15H",
                "failure_type": request.failure_type,
            },
        )
    except (CallbackContextBindingError, CallbackStatusTransitionError):
        return (
            False,
            "C15D status was not updated; C15H recorded the failed state.",
        )
    return True, "C15D execution status was updated to failed."


def handle_failure(
    request: FailureHandlingRequest,
    *,
    store: DeadLetterQueueStore | None = None,
    db: Session | None = None,
    org_id: str | None = None,
    now: datetime | None = None,
) -> FailureHandlingOutcome:
    failure_time = now or _utc_now()
    failure_timestamp = _timestamp(failure_time)
    retry_decision = _build_retry_decision(request, now=failure_time)
    fallback_response = _build_fallback_response(request)
    c15d_updated, c15d_reason = _mark_execution_failed(request)
    target_store = store or DeadLetterQueueStore(
        db=db,
        org_id=org_id or PLATFORM_ORG_ID,
    )
    dlq_record = target_store.record_failure(
        request,
        retry_decision=retry_decision,
        failed_at=failure_timestamp,
    )
    handling_status = (
        "retry_scheduled"
        if retry_decision.retry_status == "retry_scheduled"
        else "dead_lettered"
    )
    record_workflow_event(
        event_type="workflow.failure",
        action="workflow.failure",
        context_id=request.context_id,
        workflow_id=request.workflow_id,
        module_key=request.module,
        status="failed",
        source="backend",
        payload={
            "failure_type": request.failure_type,
            "attempt": request.attempt,
            "handling_status": handling_status,
            "dlq_id": dlq_record.dlq_id,
        },
    )
    record_workflow_event(
        event_type="workflow.retry",
        action="workflow.retry",
        context_id=request.context_id,
        workflow_id=request.workflow_id,
        module_key=request.module,
        status=(
            "pending"
            if retry_decision.retry_status == "retry_scheduled"
            else "failed"
        ),
        source="backend",
        payload=retry_decision.model_dump(mode="json"),
    )
    return FailureHandlingOutcome(
        handling_status=handling_status,
        reason=(
            "C15H handled the failure with retry evaluation, DLQ recording, "
            "safe fallback generation, and failed-state marking."
        ),
        context_id=request.context_id,
        module=request.module,
        workflow_id=request.workflow_id,
        retry_decision=retry_decision,
        fallback_response=fallback_response,
        dlq_record=dlq_record,
        c15d_status_update_performed=c15d_updated,
        c15d_status_update_reason=c15d_reason,
    )


def evaluate_timeout(
    request: TimeoutEvaluationRequest,
    *,
    store: DeadLetterQueueStore | None = None,
    db: Session | None = None,
    org_id: str | None = None,
) -> TimeoutHandlingDecision:
    started_at = _parse_timestamp(request.started_at)
    checked_at = (
        _parse_timestamp(request.checked_at)
        if request.checked_at is not None
        else _utc_now()
    )
    elapsed_seconds = max((checked_at - started_at).total_seconds(), 0.0)
    checked_timestamp = _timestamp(checked_at)
    if elapsed_seconds < request.timeout_seconds:
        record_workflow_event(
            event_type="workflow.timeout",
            action="workflow.timeout.evaluate",
            context_id=request.context_id,
            workflow_id=request.workflow_id,
            module_key=request.module,
            status="success",
            source="backend",
            payload={
                "timeout_status": "within_timeout",
                "elapsed_seconds": elapsed_seconds,
                "timeout_seconds": request.timeout_seconds,
            },
        )
        return TimeoutHandlingDecision(
            timeout_status="within_timeout",
            context_id=request.context_id,
            module=request.module,
            workflow_id=request.workflow_id,
            elapsed_seconds=elapsed_seconds,
            timeout_seconds=request.timeout_seconds,
            checked_at=checked_timestamp,
            reason=(
                "C15H checked the webhook execution window and no timeout "
                "was detected."
            ),
            fallback_triggered=False,
            execution_marked_failed=False,
        )

    failure_outcome = handle_failure(
        FailureHandlingRequest(
            module=request.module,
            workflow_id=request.workflow_id,
            context_id=request.context_id,
            failure_type="webhook_timeout",
            reason=(
                "Webhook timeout detected by C15H after "
                f"{elapsed_seconds:.3f} seconds."
            ),
            attempt=request.attempt,
            task=request.task,
            payload=request.payload,
            retry_policy=request.retry_policy,
        ),
        store=store,
        db=db,
        org_id=org_id,
        now=checked_at,
    )
    record_workflow_event(
        event_type="workflow.timeout",
        action="workflow.timeout.evaluate",
        context_id=request.context_id,
        workflow_id=request.workflow_id,
        module_key=request.module,
        status="failed",
        source="backend",
        payload={
            "timeout_status": "timed_out",
            "elapsed_seconds": elapsed_seconds,
            "timeout_seconds": request.timeout_seconds,
        },
    )
    return TimeoutHandlingDecision(
        timeout_status="timed_out",
        context_id=request.context_id,
        module=request.module,
        workflow_id=request.workflow_id,
        elapsed_seconds=elapsed_seconds,
        timeout_seconds=request.timeout_seconds,
        checked_at=checked_timestamp,
        reason=(
            "C15H detected a webhook timeout, marked the execution as failed, "
            "generated fallback state, and recorded the failure context."
        ),
        failure_outcome=failure_outcome,
        fallback_triggered=True,
        execution_marked_failed=True,
    )


def list_dead_letter_records(
    *,
    store: DeadLetterQueueStore | None = None,
    db: Session | None = None,
    org_id: str | None = None,
) -> DeadLetterQueueResponse:
    target_store = store or DeadLetterQueueStore(
        db=db,
        org_id=org_id or PLATFORM_ORG_ID,
    )
    records = target_store.list_records()
    return DeadLetterQueueResponse(
        items=records,
        count=len(records),
        retry_pending_count=sum(
            1 for record in records if record.status == "retry_pending"
        ),
        queued_count=sum(1 for record in records if record.status == "queued"),
        replayed_count=sum(1 for record in records if record.status == "replayed"),
    )


def get_dead_letter_record(
    context_id: str,
    *,
    store: DeadLetterQueueStore | None = None,
    db: Session | None = None,
    org_id: str | None = None,
) -> DeadLetterRecord | None:
    target_store = store or DeadLetterQueueStore(
        db=db,
        org_id=org_id or PLATFORM_ORG_ID,
    )
    return target_store.get(context_id)


def manual_replay_context(
    request: ManualReplayRequest,
    *,
    settings: Settings,
    db: Session | None = None,
    store: DeadLetterQueueStore | None = None,
    org_id: str | None = None,
) -> RecoveryPlan:
    target_store = store or DeadLetterQueueStore(
        db=db,
        org_id=org_id or PLATFORM_ORG_ID,
    )
    record = target_store.get(request.context_id)
    if record is None:
        record_workflow_event(
            event_type="workflow.retry",
            action="workflow.manual_replay",
            context_id=request.context_id,
            workflow_id=None,
            module_key=None,
            status="failed",
            source="backend",
            payload={"recovery_status": "not_found"},
        )
        return RecoveryPlan(
            recovery_status="not_found",
            context_id=request.context_id,
            reason="C15H could not find a DLQ record for the context_id.",
            manual_retry_triggered=False,
        )

    fallback = _build_fallback_response(
        FailureHandlingRequest(
            module=record.module,
            workflow_id=record.workflow_id,
            context_id=record.context_id,
            failure_type=record.failure_type,
            reason=record.failure_reason,
            attempt=record.attempt,
            payload=record.failure_context.get("payload", {}),
        )
    )
    if record.status == "closed" or (
        record.status == "replayed" and not request.force_replay
    ):
        record_workflow_event(
            event_type="workflow.retry",
            action="workflow.manual_replay",
            context_id=request.context_id,
            workflow_id=record.workflow_id,
            module_key=record.module,
            status="failed",
            source="backend",
            payload={"recovery_status": "replay_rejected"},
        )
        return RecoveryPlan(
            recovery_status="replay_rejected",
            context_id=request.context_id,
            reason=(
                "C15H rejected manual replay because the DLQ record is closed "
                "or already replayed."
            ),
            manual_retry_triggered=True,
            dlq_record=record,
            fallback_response=fallback,
        )

    secret = _secret_value(settings.webhook_gateway_signing_secret)
    if not secret:
        raise FailureRecoveryError(
            "C15H manual replay requires the C15B gateway signing secret."
        )

    payload_value = record.failure_context.get("payload", {})
    replay_payload = WebhookGatewayRequest(
        module=record.module,
        workflow_id=record.workflow_id,
        context_id=record.context_id,
        payload=payload_value if isinstance(payload_value, dict) else {},
        timestamp=_utc_now_timestamp(),
        nonce=f"c15h.{uuid4().hex}",
    )
    signature = sign_webhook_gateway_payload(
        replay_payload,
        secret=settings.webhook_gateway_signing_secret,
    )
    try:
        gateway_decision = build_webhook_gateway_decision(
            replay_payload,
            provided_signature=signature,
            settings=settings,
            db=db,
        )
    except (WebhookGatewayConfigurationError, WebhookGatewaySignatureError) as exc:
        raise FailureRecoveryError(str(exc)) from exc

    if gateway_decision.gateway_status != "accepted":
        record_workflow_event(
            event_type="workflow.retry",
            action="workflow.manual_replay",
            context_id=request.context_id,
            workflow_id=record.workflow_id,
            module_key=record.module,
            status="failed",
            source="backend",
            payload={"recovery_status": "replay_rejected"},
        )
        return RecoveryPlan(
            recovery_status="replay_rejected",
            context_id=request.context_id,
            reason=(
                "C15H routed manual replay through C15B, but the gateway "
                "decision rejected re-entry."
            ),
            manual_retry_triggered=True,
            dlq_record=record,
            replay_payload=replay_payload,
            c15b_gateway_decision=gateway_decision,
            fallback_response=fallback,
        )

    updated_record = target_store.mark_replayed(
        record,
        replayed_at=_utc_now_timestamp(),
    )
    record_workflow_event(
        event_type="workflow.retry",
        action="workflow.manual_replay",
        context_id=request.context_id,
        workflow_id=record.workflow_id,
        module_key=record.module,
        status="pending",
        source="backend",
        payload={"recovery_status": "replay_prepared"},
    )
    return RecoveryPlan(
        recovery_status="replay_prepared",
        context_id=request.context_id,
        reason=(
            "C15H prepared manual replay through the C15B gateway boundary. "
            "No n8n dispatch was performed by C15H."
        ),
        manual_retry_triggered=True,
        dlq_record=updated_record,
        replay_payload=replay_payload,
        c15b_gateway_decision=gateway_decision,
        fallback_response=fallback,
    )


def get_retry_system_design() -> RetrySystemDesign:
    return RetrySystemDesign()


def get_timeout_handling_model() -> TimeoutHandlingModel:
    return TimeoutHandlingModel()


def get_dead_letter_queue_architecture() -> DeadLetterQueueArchitecture:
    return DeadLetterQueueArchitecture()


def get_fallback_strategy() -> FallbackStrategy:
    return FallbackStrategy()


def get_recovery_flow() -> RecoveryFlow:
    return RecoveryFlow()


def get_failure_handling_completion_status() -> FailureHandlingCompletionStatus:
    return FailureHandlingCompletionStatus(
        proceed_reason=(
            "C15H defines automatic retry decisions, configurable retry count, "
            "conceptual exponential backoff, webhook timeout failure handling, "
            "DLQ context storage, safe fallback response generation, and "
            "manual context-based recovery through C15B without runtime "
            "execution or external API changes."
        )
    )
