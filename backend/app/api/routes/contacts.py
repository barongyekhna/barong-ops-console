from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.contact_identity import ContactIdentity, ContactIdentityUpdate
from ...schemas.global_contact import GlobalContactDirectory
from ...services.contact_identity_service import (
    ContactIdentityConflictError,
    ContactIdentityMembershipRequiredError,
    ContactIdentityNotFoundError,
    ContactIdentityOrganizationNotFoundError,
    ContactIdentityPermissionDeniedError,
    get_contact_identity_for_actor,
    update_contact_identity,
)
from ...services.global_contact_directory import (
    GlobalContactDirectoryAccessDeniedError,
    build_global_directory,
)
from ..deps import get_audit_context, get_current_user

router = APIRouter(prefix="/contacts", tags=["contacts"])
UserIdPath = Annotated[str, Path(min_length=1, max_length=255)]


def _raise_contact_identity_error(exc: Exception) -> NoReturn:
    if isinstance(
        exc,
        (
            ContactIdentityNotFoundError,
            ContactIdentityOrganizationNotFoundError,
            ContactIdentityMembershipRequiredError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    if isinstance(exc, ContactIdentityPermissionDeniedError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Contact identity permission denied.",
        ) from None
    if isinstance(exc, ContactIdentityConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    if isinstance(exc, GlobalContactDirectoryAccessDeniedError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global contact directory access denied.",
        ) from None
    raise exc


@router.get("/directory", response_model=GlobalContactDirectory)
def global_contact_directory(
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> GlobalContactDirectory:
    try:
        return GlobalContactDirectory(root=build_global_directory(db, actor=actor))
    except Exception as exc:
        _raise_contact_identity_error(exc)


@router.get("/{user_id}", response_model=ContactIdentity)
def contact_identity_detail(
    request: Request,
    user_id: UserIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ContactIdentity:
    try:
        return get_contact_identity_for_actor(
            db,
            user_id=user_id,
            actor=actor,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_contact_identity_error(exc)


@router.patch("/{user_id}", response_model=ContactIdentity)
def contact_identity_update(
    payload: ContactIdentityUpdate,
    request: Request,
    user_id: UserIdPath,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ContactIdentity:
    try:
        return update_contact_identity(
            db,
            user_id=user_id,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_contact_identity_error(exc)
