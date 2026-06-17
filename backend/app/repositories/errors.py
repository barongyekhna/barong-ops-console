from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.error import SystemError
from ..schemas.errors import SystemErrorCreate
from .tenant import current_tenant_org_id, tenant_org_id_for_create


def list_errors(
    db: Session, *, limit: int, offset: int
) -> list[SystemError]:
    org_id = current_tenant_org_id()
    rows = list(
        db.scalars(
            select(SystemError)
            .where(SystemError.org_id == org_id)
            .order_by(SystemError.id.desc())
            .limit(limit + offset)
        )
    )
    return rows[offset : offset + limit]


def get_error(db: Session, error_id: str) -> SystemError | None:
    org_id = current_tenant_org_id()
    return db.scalar(
        select(SystemError).where(
            SystemError.error_id == error_id,
            SystemError.org_id == org_id,
        )
    )


def create_error(db: Session, payload: SystemErrorCreate) -> SystemError:
    error = SystemError(
        org_id=tenant_org_id_for_create(),
        error_id=payload.error_id,
        error_code=payload.error_code,
        severity=payload.severity,
        status=payload.status,
        message=payload.message,
        details=payload.details,
        job_id=payload.job_id,
        module_id=payload.module_key,
        agent_id=payload.agent_key,
        workflow_id=payload.workflow_key,
        correlation_id=payload.correlation_id,
    )
    db.add(error)
    return error
