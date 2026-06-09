from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.artifact import Artifact
from ..models.error import SystemError
from ..models.job import AutomationJob, JobEvent
from ..models.memory import MemoryEvent
from ..models.operation_log import OperationLog
from ..models.review import ReviewItem

N8N_TEST_MODULE_KEY = "n8n_test_bridge"
N8N_TEST_AGENT_KEY = "n8n_test_agent"
N8N_TEST_WORKFLOW_KEY = "n8n_test_webhook_workflow"
N8N_TEST_RUN_TYPE = "n8n_test_bridge"


def create_n8n_test_event(
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


def get_latest_n8n_test_job(db: Session) -> AutomationJob | None:
    return db.scalar(
        select(AutomationJob)
        .where(
            AutomationJob.module_id == N8N_TEST_MODULE_KEY,
            AutomationJob.input_payload["run_type"].as_string()
            == N8N_TEST_RUN_TYPE,
        )
        .order_by(AutomationJob.id.desc())
        .limit(1)
    )


def list_n8n_test_events(
    db: Session,
    job_id: str,
) -> list[JobEvent]:
    return list(
        db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.id.asc())
        )
    )


def get_n8n_test_artifact(db: Session, job_id: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.job_id == job_id)
        .order_by(Artifact.id.desc())
        .limit(1)
    )


def get_n8n_test_review(db: Session, job_id: str) -> ReviewItem | None:
    return db.scalar(
        select(ReviewItem)
        .where(ReviewItem.job_id == job_id)
        .order_by(ReviewItem.id.desc())
        .limit(1)
    )


def get_n8n_test_memory_event(
    db: Session,
    job_id: str,
) -> MemoryEvent | None:
    return db.scalar(
        select(MemoryEvent)
        .where(MemoryEvent.job_id == job_id)
        .order_by(MemoryEvent.id.desc())
        .limit(1)
    )


def get_n8n_test_error(db: Session, job_id: str) -> SystemError | None:
    return db.scalar(
        select(SystemError)
        .where(SystemError.job_id == job_id)
        .order_by(SystemError.id.desc())
        .limit(1)
    )


def list_n8n_test_operation_logs(
    db: Session,
    job_id: str,
) -> list[OperationLog]:
    return list(
        db.scalars(
            select(OperationLog)
            .where(OperationLog.job_id == job_id)
            .order_by(OperationLog.id.asc())
        )
    )
