from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..models.user import User
from ..schemas.shared_module import (
    SHARED_MODULE_ORG_ID_PATTERN,
    OrgSharedModulesResponse,
    SharedModule,
    SharedModuleCreateRequest,
    SharedModuleListResponse,
    SharedModuleUpdateOrgsRequest,
)
from ..services.shared_module_registry import (
    SharedModuleAlreadyExistsError,
    SharedModuleNotFoundError,
    SharedModulePermissionDeniedError,
    create_shared_module,
    list_org_shared_modules_for_actor,
    list_shared_modules,
    update_shared_module_orgs,
)
from .deps import get_audit_context, get_current_user, require_owner

router = APIRouter(tags=["shared-module"])

OrgIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=68,
        pattern=SHARED_MODULE_ORG_ID_PATTERN.pattern,
    ),
]


def _raise_shared_module_error(exc: Exception) -> NoReturn:
    if isinstance(exc, SharedModuleAlreadyExistsError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shared module already exists.",
        ) from None
    if isinstance(exc, SharedModuleNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared module not found.",
        ) from None
    if isinstance(exc, SharedModulePermissionDeniedError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Shared module permission denied.",
        ) from None
    if isinstance(exc, (ValidationError, ValueError)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    raise exc


@router.post(
    "/module/shared/create",
    response_model=SharedModule,
    status_code=status.HTTP_201_CREATED,
)
def shared_module_create(
    payload: SharedModuleCreateRequest,
    owner: User = Depends(require_owner),
) -> SharedModule:
    try:
        return create_shared_module(payload, actor=owner)
    except Exception as exc:
        _raise_shared_module_error(exc)


@router.post("/module/shared/update-orgs", response_model=SharedModule)
def shared_module_update_orgs(
    payload: SharedModuleUpdateOrgsRequest,
    owner: User = Depends(require_owner),
) -> SharedModule:
    try:
        return update_shared_module_orgs(payload, actor=owner)
    except Exception as exc:
        _raise_shared_module_error(exc)


@router.get("/module/shared/list", response_model=SharedModuleListResponse)
def shared_module_list(
    owner: User = Depends(require_owner),
) -> SharedModuleListResponse:
    try:
        return list_shared_modules(actor=owner)
    except Exception as exc:
        _raise_shared_module_error(exc)


@router.get(
    "/org/{org_id}/shared-modules",
    response_model=OrgSharedModulesResponse,
)
def org_shared_modules(
    request: Request,
    org_id: OrgIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> OrgSharedModulesResponse:
    get_audit_context(request)
    try:
        return list_org_shared_modules_for_actor(db, org_id=org_id, actor=actor)
    except Exception as exc:
        _raise_shared_module_error(exc)
