from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...repositories.jobs import (
    create_job,
    create_job_event,
    get_job,
    list_job_events,
    list_jobs,
)
from ...repositories.registry import get_agent, get_module, get_workflow
from ...schemas.common import ListResponse
from ...schemas.jobs import (
    JobCreate,
    JobEventCreate,
    JobEventResponse,
    JobResponse,
)
from ...services.foundation_service import (
    commit_foundation_write,
    conflict,
    invalid_reference,
    not_found,
)
from ..deps import get_audit_context, require_rbac

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=ListResponse[JobResponse])
def jobs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None, pattern=r"^\d+$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("OPERATIONS", "read")),
) -> ListResponse[JobResponse]:
    del user
    items = list_jobs(db, limit=limit, offset=offset, cursor=cursor)
    next_cursor = str(items[-1].id) if len(items) == limit else None
    return ListResponse(
        items=items,
        count=len(items),
        limit=limit,
        offset=offset,
        cursor=cursor,
        next_cursor=next_cursor,
    )


@router.get("/{job_id}", response_model=JobResponse)
def job_detail(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("OPERATIONS", "read")),
) -> JobResponse:
    del user
    job = get_job(db, job_id)
    if job is None:
        raise not_found("Job", job_id)
    return JobResponse.model_validate(job)


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def job_create(
    payload: JobCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("OPERATIONS", "write")),
) -> JobResponse:
    if get_job(db, payload.job_id) is not None:
        raise conflict("Job", payload.job_id)
    if get_module(db, payload.module_key) is None:
        raise invalid_reference("Job module_key is not registered.")
    if payload.agent_key and get_agent(db, payload.agent_key) is None:
        raise invalid_reference("Job agent_key is not registered.")
    if payload.workflow_key and get_workflow(db, payload.workflow_key) is None:
        raise invalid_reference("Job workflow_key is not registered.")
    if payload.parent_job_id and get_job(db, payload.parent_job_id) is None:
        raise invalid_reference("Job parent_job_id is not registered.")

    job = create_job(db, payload=payload, requested_by_user_id=user.id)
    commit_foundation_write(
        db,
        user=user,
        audit=get_audit_context(request),
        action="job.create_demo",
        target_type="job",
        target_id=payload.job_id,
        job_id=payload.job_id,
        details={
            "status": payload.status,
            "execution": "not_triggered",
        },
    )
    db.refresh(job)
    return JobResponse.model_validate(job)


@router.get(
    "/{job_id}/events",
    response_model=ListResponse[JobEventResponse],
)
def job_events(
    job_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None, pattern=r"^\d+$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("OPERATIONS", "read")),
) -> ListResponse[JobEventResponse]:
    del user
    if get_job(db, job_id) is None:
        raise not_found("Job", job_id)
    items = list_job_events(
        db,
        job_id=job_id,
        limit=limit,
        offset=offset,
        cursor=cursor,
    )
    next_cursor = str(items[-1].id) if len(items) == limit else None
    return ListResponse(
        items=items,
        count=len(items),
        limit=limit,
        offset=offset,
        cursor=cursor,
        next_cursor=next_cursor,
    )


@router.post(
    "/{job_id}/events",
    response_model=JobEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def job_event_create(
    job_id: str,
    payload: JobEventCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("OPERATIONS", "write")),
) -> JobEventResponse:
    job = get_job(db, job_id)
    if job is None:
        raise not_found("Job", job_id)
    event = create_job_event(
        db,
        job=job,
        payload=payload,
        actor_id=str(user.id),
    )
    commit_foundation_write(
        db,
        user=user,
        audit=get_audit_context(request),
        action="job.event.append",
        target_type="job_event",
        target_id=f"{job_id}:{payload.event_type}",
        job_id=job_id,
        details={
            "event_type": payload.event_type,
            "to_status": payload.to_status,
        },
    )
    db.refresh(event)
    return JobEventResponse.model_validate(event)
