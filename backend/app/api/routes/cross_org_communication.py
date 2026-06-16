from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.cross_org_communication import CrossOrgCheckRequest, CrossOrgDecision
from ...services.cross_org_communication import can_communicate
from ..deps import get_audit_context, get_current_user

router = APIRouter(prefix="/comm/cross-org", tags=["cross-org-communication"])


@router.post("/check", response_model=CrossOrgDecision)
def check_cross_org_permission(
    payload: CrossOrgCheckRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CrossOrgDecision:
    return can_communicate(
        db,
        payload=payload,
        actor=actor,
        audit=get_audit_context(request),
    )
