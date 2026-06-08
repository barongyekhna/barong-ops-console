from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...repositories.errors import create_error, get_error, list_errors
from ...repositories.jobs import get_job
from ...repositories.registry import get_agent, get_module, get_workflow
from ...schemas.common import ListResponse
from ...schemas.errors import SystemErrorCreate, SystemErrorResponse
from ...services.foundation_service import (
    commit_foundation_write,
    conflict,
    invalid_reference,
    not_found,
)
from ..deps import get_audit_context, get_current_user

router = APIRouter(prefix="/errors", tags=["errors"])


@router.get("", response_model=ListResponse[SystemErrorResponse])
def errors(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListResponse[SystemErrorResponse]:
    del user
    items = list_errors(db, limit=limit, offset=offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get("/{error_id}", response_model=SystemErrorResponse)
def error_detail(
    error_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SystemErrorResponse:
    del user
    error = get_error(db, error_id)
    if error is None:
        raise not_found("Error", error_id)
    return SystemErrorResponse.model_validate(error)


@router.post(
    "",
    response_model=SystemErrorResponse,
    status_code=status.HTTP_201_CREATED,
)
def error_create(
    payload: SystemErrorCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SystemErrorResponse:
    if get_error(db, payload.error_id) is not None:
        raise conflict("Error", payload.error_id)
    if payload.job_id and get_job(db, payload.job_id) is None:
        raise invalid_reference("Error job_id is not registered.")
    if payload.module_key and get_module(db, payload.module_key) is None:
        raise invalid_reference("Error module_key is not registered.")
    if payload.agent_key and get_agent(db, payload.agent_key) is None:
        raise invalid_reference("Error agent_key is not registered.")
    if payload.workflow_key and get_workflow(db, payload.workflow_key) is None:
        raise invalid_reference("Error workflow_key is not registered.")
    error = create_error(db, payload)
    commit_foundation_write(
        db,
        user=user,
        audit=get_audit_context(request),
        action="error.record_demo",
        target_type="system_error",
        target_id=payload.error_id,
        job_id=payload.job_id,
        details={
            "error_code": payload.error_code,
            "source": "foundation_demo",
        },
    )
    db.refresh(error)
    return SystemErrorResponse.model_validate(error)
