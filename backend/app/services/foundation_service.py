from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.user import User
from ..repositories.operation_logs import create_operation_log
from .auth_service import AuditContext


def not_found(resource: str, resource_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{resource} '{resource_id}' was not found.",
    )


def conflict(resource: str, resource_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"{resource} '{resource_id}' already exists.",
    )


def invalid_reference(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=message,
    )


def commit_foundation_write(
    db: Session,
    *,
    user: User,
    audit: AuditContext,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any],
    job_id: str | None = None,
) -> None:
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(user.id),
        action=action,
        target_type=target_type,
        target_id=target_id,
        job_id=job_id,
        result="success",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={"scope": "foundation_demo", **details},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{target_type} '{target_id}' conflicts with existing data.",
        ) from None
