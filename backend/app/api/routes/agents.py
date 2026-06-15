from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...repositories.registry import (
    create_agent,
    get_agent,
    get_module,
    get_workflow,
    list_agents,
)
from ...schemas.common import ListResponse
from ...schemas.registry import AgentCreate, AgentResponse
from ...services.foundation_service import (
    commit_foundation_write,
    conflict,
    invalid_reference,
    not_found,
)
from ..deps import get_audit_context, require_rbac

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=ListResponse[AgentResponse])
def agents(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> ListResponse[AgentResponse]:
    del user
    items = list_agents(db, limit=limit, offset=offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get("/{agent_key}", response_model=AgentResponse)
def agent_detail(
    agent_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> AgentResponse:
    del user
    agent = get_agent(db, agent_key)
    if agent is None:
        raise not_found("Agent", agent_key)
    return AgentResponse.model_validate(agent)


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def agent_create(
    payload: AgentCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("REGISTRY", "admin")),
) -> AgentResponse:
    if get_agent(db, payload.agent_key) is not None:
        raise conflict("Agent", payload.agent_key)
    missing_modules = [
        key
        for key in payload.allowed_module_keys
        if get_module(db, key) is None
    ]
    missing_workflows = [
        key
        for key in payload.allowed_workflow_keys
        if get_workflow(db, key) is None
    ]
    if missing_modules or missing_workflows:
        raise invalid_reference(
            "Agent references unregistered foundation modules or workflows."
        )
    agent = create_agent(db, payload)
    commit_foundation_write(
        db,
        user=user,
        audit=get_audit_context(request),
        action="agent.create_demo",
        target_type="agent",
        target_id=payload.agent_key,
        details={"status": payload.status},
    )
    db.refresh(agent)
    return AgentResponse.model_validate(agent)
