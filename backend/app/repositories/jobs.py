from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.job import AutomationJob, JobEvent
from ..schemas.jobs import JobCreate, JobEventCreate
from .tenant import current_tenant_org_id, tenant_org_id_for_create


def list_jobs(
    db: Session, *, limit: int, offset: int
) -> list[AutomationJob]:
    org_id = current_tenant_org_id()
    return list(
        db.scalars(
            select(AutomationJob)
            .where(AutomationJob.org_id == org_id)
            .order_by(AutomationJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def get_job(db: Session, job_id: str) -> AutomationJob | None:
    org_id = current_tenant_org_id()
    return db.scalar(
        select(AutomationJob).where(
            AutomationJob.job_id == job_id,
            AutomationJob.org_id == org_id,
        )
    )


def create_job(
    db: Session,
    *,
    payload: JobCreate,
    requested_by_user_id: int,
) -> AutomationJob:
    job = AutomationJob(
        org_id=tenant_org_id_for_create(),
        job_id=payload.job_id,
        module_id=payload.module_key,
        agent_id=payload.agent_key,
        workflow_id=payload.workflow_key,
        parent_job_id=payload.parent_job_id,
        requested_by_user_id=requested_by_user_id,
        status=payload.status,
        risk_level=payload.risk_level,
        input_payload=payload.input_payload,
        input_schema_version=payload.input_schema_version,
        idempotency_key=payload.idempotency_key,
        correlation_id=payload.correlation_id,
    )
    db.add(job)
    return job


def list_job_events(
    db: Session,
    *,
    job_id: str,
    limit: int,
    offset: int,
) -> list[JobEvent]:
    org_id = current_tenant_org_id()
    return list(
        db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.org_id == org_id)
            .order_by(JobEvent.id.asc())
            .limit(limit)
            .offset(offset)
        )
    )


def create_job_event(
    db: Session,
    *,
    job: AutomationJob,
    payload: JobEventCreate,
    actor_id: str,
) -> JobEvent:
    from_status = job.status if payload.to_status is not None else None
    event = JobEvent(
        org_id=job.org_id,
        job_id=job.job_id,
        event_type=payload.event_type,
        from_status=from_status,
        to_status=payload.to_status,
        actor_type="user",
        actor_id=actor_id,
        details=payload.details,
    )
    db.add(event)
    if payload.to_status is not None:
        job.status = payload.to_status
        db.add(job)
    return event
