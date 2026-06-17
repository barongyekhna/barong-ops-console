import re
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sqlalchemy import insert, inspect, select
from sqlalchemy.orm import Session

from ..db.compatibility import table_exists
from ..models.operation_log import OperationLog
from ..schemas.common import is_runtime_address_key, sanitize_runtime_address_data
from ..services.event_collector import emit_event
from .tenant import (
    ROLLOUT_BACKFILL_ORG_ID,
    current_tenant_org_id,
    tenant_org_id_for_create,
)

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

C05B_OPERATION_LOG_COLUMNS = (
    OperationLog.id,
    OperationLog.operation_id,
    OperationLog.actor_type,
    OperationLog.actor_id,
    OperationLog.action,
    OperationLog.target_type,
    OperationLog.target_id,
    OperationLog.job_id,
    OperationLog.result,
    OperationLog.error_code,
    OperationLog.request_id,
    OperationLog.ip_address,
    OperationLog.user_agent,
    OperationLog.details,
    OperationLog.created_at,
)


def operation_logs_org_id_available(db: Session) -> bool:
    if not table_exists(db, "operation_logs"):
        return False
    columns = {
        column["name"]
        for column in inspect(db.get_bind()).get_columns("operation_logs")
    }
    return "org_id" in columns


def _operation_log_from_row(row: Any) -> OperationLog:
    values = {
        column.key: getattr(row, column.key)
        for column in C05B_OPERATION_LOG_COLUMNS
    }
    values["org_id"] = ROLLOUT_BACKFILL_ORG_ID
    return OperationLog(**values)


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
    values = {
        "operation_id": str(uuid4()),
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "job_id": job_id,
        "result": result,
        "error_code": error_code,
        "request_id": request_id,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "details": _sanitize_details(details) if details is not None else None,
    }
    if operation_logs_org_id_available(db):
        operation_log = OperationLog(
            org_id=tenant_org_id_for_create(),
            **values,
        )
        db.add(operation_log)
    else:
        row = db.execute(
            insert(OperationLog)
            .values(**values)
            .returning(OperationLog.id, OperationLog.created_at)
        ).one()
        operation_log = OperationLog(
            id=row.id,
            created_at=row.created_at,
            org_id=ROLLOUT_BACKFILL_ORG_ID,
            **values,
        )
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
    has_org_id = operation_logs_org_id_available(db)
    if has_org_id:
        org_id = current_tenant_org_id()
        statement = (
            select(OperationLog)
            .where(OperationLog.org_id == org_id)
            .order_by(OperationLog.id.desc())
        )
    else:
        statement = select(*C05B_OPERATION_LOG_COLUMNS).order_by(
            OperationLog.id.desc()
        )
    if cursor is not None:
        statement = statement.where(OperationLog.id < int(cursor))
    fetch_limit = limit if cursor is not None else limit + offset
    if has_org_id:
        logs = list(db.scalars(statement.limit(fetch_limit)))
    else:
        logs = [
            _operation_log_from_row(row)
            for row in db.execute(statement.limit(fetch_limit))
        ]
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
    if operation_logs_org_id_available(db):
        org_id = current_tenant_org_id()
        operation_log = db.scalar(
            select(OperationLog).where(
                OperationLog.operation_id == operation_id,
                OperationLog.org_id == org_id,
            )
        )
    else:
        row = db.execute(
            select(*C05B_OPERATION_LOG_COLUMNS).where(
                OperationLog.operation_id == operation_id,
            )
        ).first()
        operation_log = _operation_log_from_row(row) if row is not None else None
    emit_event(
        event_type="log.read",
        module="system",
        action="log.read",
        source="system",
        status="success" if operation_log is not None else "failed",
        payload={"operation": "get_operation_log", "operation_id": operation_id},
    )
    return operation_log
