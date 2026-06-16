from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..models.user import User
from ..schemas.org_membership import (
    OrgMemberAddRequest,
    OrgMemberRemoveRequest,
    OrgMembership,
)
from ..schemas.organization import ORG_ID_PATTERN
from ..services.org_membership_service import (
    OrgMembershipConflictError,
    OrgMembershipNotFoundError,
    OrgMembershipOrganizationNotFoundError,
    OrgMembershipPermissionDeniedError,
    OrgMembershipUserNotFoundError,
    add_org_member,
    list_org_members,
    remove_org_member,
)
from .deps import get_audit_context, get_current_user

router = APIRouter(prefix="/org", tags=["organization-membership"])
OrgIdPath = Annotated[str, Path(pattern=ORG_ID_PATTERN.pattern)]


def _raise_membership_error(exc: Exception) -> NoReturn:
    if isinstance(
        exc,
        (
            OrgMembershipOrganizationNotFoundError,
            OrgMembershipUserNotFoundError,
            OrgMembershipNotFoundError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    if isinstance(exc, OrgMembershipPermissionDeniedError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization membership permission denied.",
        ) from None
    if isinstance(exc, OrgMembershipConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    raise exc


@router.post(
    "/{org_id}/members/add",
    response_model=OrgMembership,
    status_code=status.HTTP_201_CREATED,
)
def org_member_add(
    payload: OrgMemberAddRequest,
    request: Request,
    org_id: OrgIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> OrgMembership:
    try:
        return add_org_member(
            db,
            org_id=org_id,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_membership_error(exc)


@router.post("/{org_id}/members/remove", response_model=OrgMembership)
def org_member_remove(
    payload: OrgMemberRemoveRequest,
    request: Request,
    org_id: OrgIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> OrgMembership:
    try:
        return remove_org_member(
            db,
            org_id=org_id,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_membership_error(exc)


@router.get("/{org_id}/members", response_model=list[OrgMembership])
def org_members_list(
    request: Request,
    org_id: OrgIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[OrgMembership]:
    try:
        return list_org_members(
            db,
            org_id=org_id,
            actor=actor,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_membership_error(exc)
