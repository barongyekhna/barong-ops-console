from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter, sleep
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..models.user import User
from ..repositories.operation_logs import create_operation_log
from ..schemas.common import sanitize_runtime_address_data
from ..schemas.n8n_webhook_test import (
    N8N_WEBHOOK_TEST_MODULE_KEY,
    N8nWebhookInjectedKeyRead,
    N8nWebhookTestRunRequest,
    N8nWebhookTestRunResponse,
)
from .auth_service import AuditContext
from .module_execution_gate import ModuleExecutionContext

N8N_WEBHOOK_MAX_ATTEMPTS = 2
N8N_WEBHOOK_RETRY_BACKOFF_SECONDS = 0.2
RETRYABLE_WEBHOOK_STATUS_CODES = frozenset((408, 429, 500, 502, 503, 504))


class N8nWebhookTestError(RuntimeError):
    status_code = 502
    error_code = "n8n_webhook_test_failed"


class N8nWebhookConfigurationError(N8nWebhookTestError):
    status_code = 503
    error_code = "n8n_webhook_url_missing"


class N8nWebhookConnectionError(N8nWebhookTestError):
    status_code = 502
    error_code = "n8n_webhook_connection_failed"


class N8nWebhookResponseError(N8nWebhookTestError):
    status_code = 502
    error_code = "n8n_webhook_response_failed"


def _webhook_url(settings: Settings) -> str:
    value = settings.n8n_test_webhook_url.strip()
    if not value:
        raise N8nWebhookConfigurationError("N8N_TEST_WEBHOOK_URL is not configured.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise N8nWebhookConfigurationError("N8N_TEST_WEBHOOK_URL must be HTTP(S).")
    if parsed.username or parsed.password:
        raise N8nWebhookConfigurationError(
            "N8N_TEST_WEBHOOK_URL must not contain credentials."
        )
    return value


def _response_body(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type.lower():
        try:
            return sanitize_runtime_address_data(response.json())
        except ValueError:
            return {"unparseable_json": True}
    text = response.text[:4000]
    return sanitize_runtime_address_data({"text": text})


def _send_webhook_with_retries(
    *,
    target_url: str,
    headers: dict[str, str],
    request_payload: dict[str, Any],
    timeout_seconds: int,
    attempt_records: list[dict[str, Any]],
) -> httpx.Response:
    last_http_error: httpx.HTTPError | None = None
    last_timeout_error: httpx.TimeoutException | None = None
    for attempt in range(1, N8N_WEBHOOK_MAX_ATTEMPTS + 1):
        attempt_started = perf_counter()
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(
                    target_url,
                    headers=headers,
                    json=request_payload,
                )
        except httpx.TimeoutException as exc:
            last_timeout_error = exc
            attempt_records.append(
                {
                    "attempt": attempt,
                    "elapsed_ms": round((perf_counter() - attempt_started) * 1000, 3),
                    "error": "timeout",
                    "retryable": attempt < N8N_WEBHOOK_MAX_ATTEMPTS,
                }
            )
            if attempt >= N8N_WEBHOOK_MAX_ATTEMPTS:
                raise
        except httpx.HTTPError as exc:
            last_http_error = exc
            attempt_records.append(
                {
                    "attempt": attempt,
                    "elapsed_ms": round((perf_counter() - attempt_started) * 1000, 3),
                    "error": type(exc).__name__,
                    "retryable": attempt < N8N_WEBHOOK_MAX_ATTEMPTS,
                }
            )
            if attempt >= N8N_WEBHOOK_MAX_ATTEMPTS:
                raise
        else:
            retryable = response.status_code in RETRYABLE_WEBHOOK_STATUS_CODES
            attempt_records.append(
                {
                    "attempt": attempt,
                    "elapsed_ms": round((perf_counter() - attempt_started) * 1000, 3),
                    "status_code": response.status_code,
                    "retryable": retryable
                    and attempt < N8N_WEBHOOK_MAX_ATTEMPTS,
                }
            )
            if not retryable or attempt >= N8N_WEBHOOK_MAX_ATTEMPTS:
                return response

        if attempt < N8N_WEBHOOK_MAX_ATTEMPTS:
            sleep(N8N_WEBHOOK_RETRY_BACKOFF_SECONDS)

    if last_timeout_error is not None:
        raise last_timeout_error
    if last_http_error is not None:
        raise last_http_error
    raise N8nWebhookConnectionError("n8n webhook request failed.")


def _audit(
    db: Session,
    *,
    user: User,
    audit: AuditContext,
    result: str,
    run_id: str,
    org_id: str,
    error_code: str | None = None,
    details: dict[str, Any] | None = None,
):
    return create_operation_log(
        db,
        actor_type="user",
        actor_id=str(user.id),
        action="n8n_webhook_test.run",
        target_type="module",
        target_id=N8N_WEBHOOK_TEST_MODULE_KEY,
        result=result,
        error_code=error_code,
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={
            "run_id": run_id,
            "org_id": org_id,
            "module_id": N8N_WEBHOOK_TEST_MODULE_KEY,
            **(details or {}),
        },
    )


def run_n8n_webhook_test(
    db: Session,
    *,
    user: User,
    payload: N8nWebhookTestRunRequest,
    audit: AuditContext,
    settings: Settings,
    execution_context: ModuleExecutionContext,
) -> N8nWebhookTestRunResponse:
    run_id = f"n8n_webhook_test_{uuid4().hex}"
    started = perf_counter()
    webhook_key = execution_context.key_for_step("webhook")
    injected_key = N8nWebhookInjectedKeyRead(
        key_alias=webhook_key.key_alias,
        key_id=webhook_key.key_id,
        key_name=webhook_key.name,
        header_name=webhook_key.header_name,
    )

    try:
        target_url = _webhook_url(settings)
    except N8nWebhookConfigurationError as exc:
        operation_log = _audit(
            db,
            user=user,
            audit=audit,
            result="failure",
            run_id=run_id,
            org_id=execution_context.org_id,
            error_code=exc.error_code,
            details={
                "request_sent": False,
                "attempts": 0,
                "retry_count": 0,
                "key_alias": webhook_key.key_alias,
                "key_id": webhook_key.key_id,
            },
        )
        db.commit()
        exc.args = (str(exc), operation_log.operation_id)
        raise

    request_payload = {
        "run_id": run_id,
        "module_id": N8N_WEBHOOK_TEST_MODULE_KEY,
        "org_id": execution_context.org_id,
        "correlation_id": payload.correlation_id,
        "triggered_by_user_id": str(user.id),
        "sent_at": datetime.now(UTC).isoformat(),
        "payload": payload.payload,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        webhook_key.header_name: webhook_key.header_value,
        "X-Barong-Module-Id": N8N_WEBHOOK_TEST_MODULE_KEY,
        "X-Barong-Run-Id": run_id,
        "X-Barong-Org-Id": execution_context.org_id,
    }

    attempt_records: list[dict[str, Any]] = []
    try:
        response = _send_webhook_with_retries(
            target_url=target_url,
            headers=headers,
            request_payload=request_payload,
            timeout_seconds=settings.n8n_test_request_timeout_seconds,
            attempt_records=attempt_records,
        )
    except httpx.TimeoutException as exc:
        attempt_count = len(attempt_records)
        operation_log = _audit(
            db,
            user=user,
            audit=audit,
            result="failure",
            run_id=run_id,
            org_id=execution_context.org_id,
            error_code="n8n_webhook_timeout",
            details={
                "request_sent": True,
                "response_returned": False,
                "attempts": attempt_count,
                "retry_count": max(0, attempt_count - 1),
                "attempt_records": attempt_records,
                "key_alias": webhook_key.key_alias,
                "key_id": webhook_key.key_id,
            },
        )
        db.commit()
        wrapped = N8nWebhookConnectionError("n8n webhook request timed out.")
        wrapped.status_code = 504
        wrapped.error_code = "n8n_webhook_timeout"
        wrapped.args = (
            str(wrapped),
            operation_log.operation_id,
            {
                "attempts": attempt_count,
                "retry_count": max(0, attempt_count - 1),
            },
        )
        raise wrapped from exc
    except httpx.HTTPError as exc:
        attempt_count = len(attempt_records)
        operation_log = _audit(
            db,
            user=user,
            audit=audit,
            result="failure",
            run_id=run_id,
            org_id=execution_context.org_id,
            error_code=N8nWebhookConnectionError.error_code,
            details={
                "request_sent": True,
                "response_returned": False,
                "attempts": attempt_count,
                "retry_count": max(0, attempt_count - 1),
                "attempt_records": attempt_records,
                "key_alias": webhook_key.key_alias,
                "key_id": webhook_key.key_id,
            },
        )
        db.commit()
        wrapped = N8nWebhookConnectionError("n8n webhook request failed.")
        wrapped.args = (
            str(wrapped),
            operation_log.operation_id,
            {
                "attempts": attempt_count,
                "retry_count": max(0, attempt_count - 1),
            },
        )
        raise wrapped from exc

    duration_ms = round((perf_counter() - started) * 1000, 3)
    body = _response_body(response)
    response_ok = 200 <= response.status_code < 300
    attempt_count = len(attempt_records)
    operation_log = _audit(
        db,
        user=user,
        audit=audit,
        result="success" if response_ok else "failure",
        run_id=run_id,
        org_id=execution_context.org_id,
        error_code=None if response_ok else N8nWebhookResponseError.error_code,
        details={
            "request_sent": True,
            "n8n_received": response_ok,
            "response_returned": True,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "attempts": attempt_count,
            "retry_count": max(0, attempt_count - 1),
            "attempt_records": attempt_records,
            "key_alias": webhook_key.key_alias,
            "key_id": webhook_key.key_id,
            "response_body": body,
        },
    )

    result = N8nWebhookTestRunResponse(
        run_id=run_id,
        module_id=N8N_WEBHOOK_TEST_MODULE_KEY,
        org_id=execution_context.org_id,
        request_sent=True,
        n8n_received=response_ok,
        response_returned=True,
        logs_stored=True,
        success=response_ok,
        status_code=response.status_code,
        duration_ms=duration_ms,
        attempts=attempt_count,
        retry_count=max(0, attempt_count - 1),
        operation_log_id=operation_log.operation_id,
        injected_key=injected_key,
        response_body=body,
        error_code=None if response_ok else N8nWebhookResponseError.error_code,
        error_message=None if response_ok else "n8n returned a non-2xx response.",
    )
    if response_ok:
        db.commit()
        return result

    db.commit()
    exc = N8nWebhookResponseError("n8n returned a non-2xx response.")
    exc.args = (str(exc), operation_log.operation_id, result.model_dump(mode="json"))
    raise exc
