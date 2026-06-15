from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...repositories.registry import (
    create_workflow,
    get_workflow,
    list_workflows,
)
from ...schemas.common import ListResponse
from ...schemas.registry import WorkflowCreate, WorkflowResponse
from ...services.foundation_service import (
    commit_foundation_write,
    conflict,
    not_found,
)
from ..deps import get_audit_context, require_rbac

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("", response_model=ListResponse[WorkflowResponse])
def workflows(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ListResponse[WorkflowResponse]:
    del user
    items = list_workflows(db, limit=limit, offset=offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get("/{workflow_key}", response_model=WorkflowResponse)
def workflow_detail(
    workflow_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> WorkflowResponse:
    del user
    workflow = get_workflow(db, workflow_key)
    if workflow is None:
        raise not_found("Workflow", workflow_key)
    return WorkflowResponse.model_validate(workflow)


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
def workflow_create(
    payload: WorkflowCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> WorkflowResponse:
    if get_workflow(db, payload.workflow_key) is not None:
        raise conflict("Workflow", payload.workflow_key)
    workflow = create_workflow(db, payload)
    commit_foundation_write(
        db,
        user=user,
        audit=get_audit_context(request),
        action="workflow.create_demo",
        target_type="workflow",
        target_id=payload.workflow_key,
        details={
            "status": payload.status,
            "execution": "metadata_only",
        },
    )
    db.refresh(workflow)
    return WorkflowResponse.model_validate(workflow)
