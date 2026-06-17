from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..models.user import User
from ..schemas.module_binding import (
    MODULE_BINDING_ID_PATTERN,
    MODULE_BINDING_ORG_ID_PATTERN,
    ModuleBindRequest,
    ModuleBinding,
    OrgVisibleModulesResponse,
)
from ..services.module_binding_service import (
    ModuleBindingNotFoundError,
    ModuleBindingPermissionDeniedError,
    bind_module_to_org,
    get_module_binding_for_actor,
    list_org_visible_modules_for_actor,
)
from .deps import get_audit_context, get_current_user, require_owner

router = APIRouter(tags=["module-binding"])

ModuleIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=128,
        pattern=MODULE_BINDING_ID_PATTERN.pattern,
    ),
]
OrgIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=68,
        pattern=MODULE_BINDING_ORG_ID_PATTERN.pattern,
    ),
]


def _raise_module_binding_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ModuleBindingNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Module binding not found.",
        ) from None
    if isinstance(exc, ModuleBindingPermissionDeniedError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Module binding permission denied.",
        ) from None
    raise exc


@router.post(
    "/module/bind",
    response_model=ModuleBinding,
    status_code=status.HTTP_201_CREATED,
)
def module_bind(
    payload: ModuleBindRequest,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> ModuleBinding:
    try:
        return bind_module_to_org(payload, actor=owner, db=db)
    except Exception as exc:
        _raise_module_binding_error(exc)


@router.get("/module/{module_id}/bindings", response_model=ModuleBinding)
def module_bindings(
    module_id: ModuleIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ModuleBinding:
    try:
        return get_module_binding_for_actor(db, module_id=module_id, actor=actor)
    except Exception as exc:
        _raise_module_binding_error(exc)


@router.get("/org/{org_id}/modules", response_model=OrgVisibleModulesResponse)
def org_visible_modules(
    org_id: OrgIdPath,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> OrgVisibleModulesResponse:
    get_audit_context(request)
    try:
        return list_org_visible_modules_for_actor(db, org_id=org_id, actor=actor)
    except Exception as exc:
        _raise_module_binding_error(exc)
