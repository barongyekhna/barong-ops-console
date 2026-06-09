from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.artifact import Artifact
from ..models.job import AutomationJob, JobEvent
from ..models.memory import MemoryEvent
from ..models.operation_log import OperationLog
from ..models.review import ReviewItem

FOUNDATION_DEMO_JOB_TYPE = "foundation_demo"
FOUNDATION_DEMO_MODULE_KEY = "foundation_demo"


def create_foundation_demo_event(
    db: Session,
    *,
    job: AutomationJob,
    event_type: str,
    actor_type: str,
    actor_id: str,
    to_status: str | None = None,
    details: dict[str, object] | None = None,
) -> JobEvent:
    event = JobEvent(
        job_id=job.job_id,
        event_type=event_type,
        from_status=None if event_type == "created" else job.status,
        to_status=to_status,
        actor_type=actor_type,
        actor_id=actor_id,
        details=details,
    )
    db.add(event)
    if to_status is not None:
        job.status = to_status
        db.add(job)
    return event


def get_latest_foundation_demo_job(db: Session) -> AutomationJob | None:
    return db.scalar(
        select(AutomationJob)
        .where(
            AutomationJob.module_id == FOUNDATION_DEMO_MODULE_KEY,
            AutomationJob.input_payload["job_type"].as_string()
            == FOUNDATION_DEMO_JOB_TYPE,
        )
        .order_by(AutomationJob.id.desc())
        .limit(1)
    )


def get_foundation_demo_artifact(
    db: Session, job_id: str
) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.job_id == job_id)
        .order_by(Artifact.id.desc())
        .limit(1)
    )


def get_foundation_demo_review(
    db: Session, job_id: str
) -> ReviewItem | None:
    return db.scalar(
        select(ReviewItem)
        .where(ReviewItem.job_id == job_id)
        .order_by(ReviewItem.id.desc())
        .limit(1)
    )


def get_foundation_demo_memory_event(
    db: Session, job_id: str
) -> MemoryEvent | None:
    return db.scalar(
        select(MemoryEvent)
        .where(MemoryEvent.job_id == job_id)
        .order_by(MemoryEvent.id.desc())
        .limit(1)
    )


def list_foundation_demo_events(
    db: Session, job_id: str
) -> list[JobEvent]:
    return list(
        db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.id.asc())
        )
    )


def list_foundation_demo_operation_logs(
    db: Session, job_id: str
) -> list[OperationLog]:
    return list(
        db.scalars(
            select(OperationLog)
            .where(OperationLog.job_id == job_id)
            .order_by(OperationLog.id.asc())
        )
    )
