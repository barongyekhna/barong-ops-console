import logging
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
from ..services.api_stability import (
    api_snapshot_key,
    get_api_snapshot,
    raise_structured_api_error,
    save_api_snapshot,
    stable_read_failure,
)
from .deps import get_audit_context, get_current_user

router = APIRouter(prefix="/org", tags=["organization-membership"])
OrgIdPath = Annotated[str, Path(pattern=ORG_ID_PATTERN.pattern)]
logger = logging.getLogger(__name__)


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
    cache_key = api_snapshot_key("org.members", org_id, actor.id)
    try:
        members = list_org_members(
            db,
            org_id=org_id,
            actor=actor,
            audit=get_audit_context(request),
        )
        save_api_snapshot(cache_key, members)
        return members
    except Exception as exc:
        if isinstance(
            exc,
            (
                OrgMembershipOrganizationNotFoundError,
                OrgMembershipUserNotFoundError,
                OrgMembershipNotFoundError,
                OrgMembershipPermissionDeniedError,
                OrgMembershipConflictError,
            ),
        ):
            _raise_membership_error(exc)
        db.rollback()
        stable_read_failure(
            logger=logger,
            route="/org/{org_id}/members",
            exc=exc,
            request=request,
            code="org_members_failed",
        )
        snapshot = get_api_snapshot(cache_key)
        if snapshot is not None:
            return snapshot
        raise_structured_api_error(
            code="org_members_failed",
            message="Organization members are temporarily unavailable.",
            request=request,
            retryable=True,
        )
