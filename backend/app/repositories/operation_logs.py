import re
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models.operation_log import OperationLog
from ..schemas.common import is_runtime_address_key, sanitize_runtime_address_data

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
    return operation_log


def list_operation_logs(
    db: Session,
    *,
    limit: int,
    offset: int,
) -> list[OperationLog]:
    from sqlalchemy import select

    return list(
        db.scalars(
            select(OperationLog)
            .order_by(OperationLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def get_operation_log(
    db: Session,
    operation_id: str,
) -> OperationLog | None:
    from sqlalchemy import select

    return db.scalar(
        select(OperationLog).where(
            OperationLog.operation_id == operation_id
        )
    )
