import re
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models.operation_log import OperationLog
from ..schemas.common import is_runtime_address_key, sanitize_runtime_address_data
from ..services.event_collector import emit_event
from .tenant import current_tenant_org_id, tenant_org_id_for_create

SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "password_hash",
    "token",
    "secret",
    "session_id",
    "cookie",
    "set-cookie",
    "signature",
    "nonce",
    "idempotency",
    "authorization",
    "api_key",
    "private_key",
    "credential",
)
INTERNAL_PATH_PATTERN = re.compile(
    r"/api/(?:backend|public|app|control-plane)(?:/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?"
)
INTERNAL_STAGE_PATTERN = re.compile(r"\bC(?:09|10|13|14|15|16)[A-Z]?\b")
INTERNAL_ROUTE_REDACTION = "[redacted-api-surface]"
INTERNAL_STAGE_REDACTION = "[redacted-internal-stage]"


def _sanitize_observability_string(value: str) -> str:
    sanitized = INTERNAL_PATH_PATTERN.sub(INTERNAL_ROUTE_REDACTION, value)
    sanitized = INTERNAL_STAGE_PATTERN.sub(INTERNAL_STAGE_REDACTION, sanitized)
    return sanitized


def _sanitize_details(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(marker in normalized_key for marker in SENSITIVE_KEY_MARKERS):
                continue
            if is_runtime_address_key(key):
                continue
            sanitized[str(key)] = _sanitize_details(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_details(item) for item in value]
    if isinstance(value, str):
        return sanitize_runtime_address_data(
            _sanitize_observability_string(value)
        )
    return sanitize_runtime_address_data(value)


def create_operation_log(
    db: Session,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    result: str,
    job_id: str | None = None,
    error_code: str | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> OperationLog:
    operation_log = OperationLog(
        org_id=tenant_org_id_for_create(),
        operation_id=str(uuid4()),
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        job_id=job_id,
        result=result,
        error_code=error_code,
        request_id=request_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details=_sanitize_details(details) if details is not None else None,
    )
    db.add(operation_log)
    emit_event(
        event_type="log.write",
        module="system",
        action="log.write",
        source="system",
        status="success",
        context_id=request_id,
        user_id=actor_id if actor_type == "user" else None,
        payload={
            "operation_log_id": operation_log.operation_id,
            "actor_type": actor_type,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "result": result,
            "error_code": error_code,
        },
    )
    return operation_log


def list_operation_logs(
    db: Session,
    *,
    limit: int,
    offset: int = 0,
    cursor: str | None = None,
) -> list[OperationLog]:
    from sqlalchemy import select

    org_id = current_tenant_org_id()
    statement = (
        select(OperationLog)
        .where(OperationLog.org_id == org_id)
        .order_by(OperationLog.id.desc())
    )
    if cursor is not None:
        statement = statement.where(OperationLog.id < int(cursor))
    fetch_limit = limit if cursor is not None else limit + offset
    logs = list(
        db.scalars(
            statement.limit(fetch_limit)
        )
    )
    if cursor is None and offset:
        logs = logs[offset : offset + limit]
    emit_event(
        event_type="log.read",
        module="system",
        action="log.read",
        source="system",
        status="success",
        payload={"operation": "list_operation_logs", "count": len(logs)},
    )
    return logs


def get_operation_log(
    db: Session,
    operation_id: str,
) -> OperationLog | None:
    from sqlalchemy import select

    org_id = current_tenant_org_id()
    operation_log = db.scalar(
        select(OperationLog).where(
            OperationLog.operation_id == operation_id,
            OperationLog.org_id == org_id,
        )
    )
    emit_event(
        event_type="log.read",
        module="system",
        action="log.read",
        source="system",
        status="success" if operation_log is not None else "failed",
        payload={"operation": "get_operation_log", "operation_id": operation_id},
    )
    return operation_log
