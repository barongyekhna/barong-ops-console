from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models.operation_log import OperationLog

SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "password_hash",
    "token",
    "secret",
    "authorization",
    "api_key",
    "private_key",
)


def _sanitize_details(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_details(item)
            for key, item in value.items()
            if not any(
                marker in str(key).lower()
                for marker in SENSITIVE_KEY_MARKERS
            )
        }
    if isinstance(value, list):
        return [_sanitize_details(item) for item in value]
    return value


def create_operation_log(
    db: Session,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    result: str,
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
        result=result,
        error_code=error_code,
        request_id=request_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details=_sanitize_details(details) if details is not None else None,
    )
    db.add(operation_log)
    return operation_log
