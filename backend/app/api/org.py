from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..models.user import User
from ..schemas.organization import (
    ORG_ID_PATTERN,
    Organization,
    OrganizationCreate,
    OrganizationLifecycleUpdate,
)
from ..services.organization_lifecycle import (
    OrganizationDuplicateError,
    OrganizationNotFoundError,
    OrganizationOwnerDeniedError,
    OrganizationStatusConflictError,
    activate_organization,
    create_organization,
    delete_organization,
    suspend_organization,
    update_organization,
)
from .deps import get_audit_context, get_current_user

router = APIRouter(prefix="/org", tags=["organization"])
OrgIdPath = Annotated[str, Path(pattern=ORG_ID_PATTERN.pattern)]


def _raise_lifecycle_error(exc: Exception) -> NoReturn:
    if isinstance(exc, OrganizationNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    if isinstance(exc, OrganizationOwnerDeniedError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization owner_user_id required.",
        ) from None
    if isinstance(exc, (OrganizationDuplicateError, OrganizationStatusConflictError)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    raise exc


@router.post(
    "/create",
    response_model=Organization,
    status_code=status.HTTP_201_CREATED,
)
def org_create(
    payload: OrganizationCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Organization:
    try:
        return create_organization(
            db,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_lifecycle_error(exc)


@router.patch("/{org_id}", response_model=Organization)
def org_update(
    payload: OrganizationLifecycleUpdate,
    request: Request,
    org_id: OrgIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Organization:
    try:
        return update_organization(
            db,
            org_id=org_id,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_lifecycle_error(exc)


@router.delete("/{org_id}", response_model=Organization)
def org_delete(
    request: Request,
    org_id: OrgIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Organization:
    try:
        return delete_organization(
            db,
            org_id=org_id,
            actor=actor,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_lifecycle_error(exc)


@router.post("/{org_id}/activate", response_model=Organization)
def org_activate(
    request: Request,
    org_id: OrgIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Organization:
    try:
        return activate_organization(
            db,
            org_id=org_id,
            actor=actor,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_lifecycle_error(exc)


@router.post("/{org_id}/suspend", response_model=Organization)
def org_suspend(
    request: Request,
    org_id: OrgIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Organization:
    try:
        return suspend_organization(
            db,
            org_id=org_id,
            actor=actor,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_lifecycle_error(exc)
