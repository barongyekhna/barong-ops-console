from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..models.user import User
from ..schemas.module_binding import MODULE_BINDING_ORG_ID_PATTERN
from ..schemas.module_visibility import ModuleVisibilityResponse
from ..services.module_visibility_service import (
    ModuleVisibilityActiveOrgContextRequiredError,
    ModuleVisibilityMembershipRequiredError,
    get_visible_modules,
)
from .deps import get_audit_context, get_current_user

router = APIRouter(tags=["module-visibility"])

OrgIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=68,
        pattern=MODULE_BINDING_ORG_ID_PATTERN.pattern,
    ),
]


def _raise_module_visibility_error(exc: Exception) -> NoReturn:
    if isinstance(
        exc,
        (
            ModuleVisibilityActiveOrgContextRequiredError,
            ModuleVisibilityMembershipRequiredError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active organization context is required.",
        ) from None
    raise exc


@router.get(
    "/org/{org_id}/visible-modules",
    response_model=ModuleVisibilityResponse,
)
def org_visible_modules(
    request: Request,
    org_id: OrgIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ModuleVisibilityResponse:
    get_audit_context(request)
    try:
        return get_visible_modules(
            db,
            user_id=str(actor.id),
            active_org_id=org_id,
        )
    except Exception as exc:
        _raise_module_visibility_error(exc)
