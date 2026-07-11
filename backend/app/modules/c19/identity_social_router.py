"""Authenticated C19 identity, directory, friendship, and block routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy.orm import Session

from ...api.deps import get_audit_context, get_current_user
from ...db.session import get_db
from ...models.user import User
from .identity_schemas import C19DirectoryPage, C19ProfileRead
from .identity_service import (
    C19ActorUnavailableError,
    C19IdentityError,
    C19ProfileNotFoundError,
    get_profile,
    list_directory,
)
from .social_schemas import (
    C19BlockPage,
    C19BlockRead,
    C19FriendPage,
    C19FriendRequestCreate,
    C19FriendRequestDirection,
    C19FriendRequestPage,
    C19FriendRequestRead,
    C19FriendRequestStatus,
    C19UserChangeRead,
)
from .social_service import (
    C19SocialConflictError,
    C19SocialError,
    C19SocialNotFoundError,
    C19SocialSelfTargetError,
    accept_friend_request,
    block_user,
    cancel_friend_request,
    create_friend_request,
    list_blocks,
    list_friend_requests,
    list_friends,
    reject_friend_request,
    remove_friend,
    unblock_user,
)


router = APIRouter(prefix="/c19", tags=["c19"])
FriendRequestIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        pattern=r"^c19frq_[0-9a-f]{32}$",
    ),
]


def _raise_c19_error(db: Session, exc: Exception) -> None:
    db.rollback()
    if isinstance(exc, C19ActorUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from None
    if isinstance(exc, (C19ProfileNotFoundError, C19SocialNotFoundError)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    if isinstance(exc, C19SocialSelfTargetError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    if isinstance(exc, C19SocialConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    if isinstance(exc, (C19IdentityError, C19SocialError)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    raise exc


@router.get("/directory", response_model=C19DirectoryPage)
def directory_endpoint(
    search: str | None = Query(default=None, max_length=255),
    affiliation_org_id: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19DirectoryPage:
    try:
        return list_directory(
            db,
            actor=actor,
            search=search,
            affiliation_org_id=affiliation_org_id,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        _raise_c19_error(db, exc)


@router.get("/profiles/{user_id}", response_model=C19ProfileRead)
def profile_endpoint(
    user_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19ProfileRead:
    try:
        return get_profile(db, actor=actor, user_id=user_id)
    except Exception as exc:
        _raise_c19_error(db, exc)


@router.get("/friend-requests", response_model=C19FriendRequestPage)
def friend_requests_endpoint(
    direction: C19FriendRequestDirection = Query(
        default=C19FriendRequestDirection.ALL
    ),
    request_status: C19FriendRequestStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19FriendRequestPage:
    try:
        return list_friend_requests(
            db,
            actor=actor,
            direction=direction,
            request_status=request_status,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        _raise_c19_error(db, exc)


@router.post(
    "/friend-requests",
    response_model=C19FriendRequestRead,
    status_code=status.HTTP_201_CREATED,
)
def friend_request_create_endpoint(
    payload: C19FriendRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19FriendRequestRead:
    try:
        return create_friend_request(
            db,
            actor=actor,
            payload=payload,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_c19_error(db, exc)


@router.post(
    "/friend-requests/{request_id}/accept",
    response_model=C19FriendRequestRead,
)
def friend_request_accept_endpoint(
    request_id: FriendRequestIdPath,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19FriendRequestRead:
    try:
        return accept_friend_request(
            db,
            actor=actor,
            request_id=request_id,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_c19_error(db, exc)


@router.post(
    "/friend-requests/{request_id}/reject",
    response_model=C19FriendRequestRead,
)
def friend_request_reject_endpoint(
    request_id: FriendRequestIdPath,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19FriendRequestRead:
    try:
        return reject_friend_request(
            db,
            actor=actor,
            request_id=request_id,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_c19_error(db, exc)


@router.post(
    "/friend-requests/{request_id}/cancel",
    response_model=C19FriendRequestRead,
)
def friend_request_cancel_endpoint(
    request_id: FriendRequestIdPath,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19FriendRequestRead:
    try:
        return cancel_friend_request(
            db,
            actor=actor,
            request_id=request_id,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_c19_error(db, exc)


@router.get("/friends", response_model=C19FriendPage)
def friends_endpoint(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19FriendPage:
    try:
        return list_friends(
            db,
            actor=actor,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        _raise_c19_error(db, exc)


@router.delete("/friends/{user_id}", response_model=C19UserChangeRead)
def friend_remove_endpoint(
    request: Request,
    user_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19UserChangeRead:
    try:
        return remove_friend(
            db,
            actor=actor,
            user_id=user_id,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_c19_error(db, exc)


@router.get("/blocks", response_model=C19BlockPage)
def blocks_endpoint(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19BlockPage:
    try:
        return list_blocks(
            db,
            actor=actor,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        _raise_c19_error(db, exc)


@router.post(
    "/blocks/{user_id}",
    response_model=C19BlockRead,
    status_code=status.HTTP_201_CREATED,
)
def block_create_endpoint(
    request: Request,
    user_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19BlockRead:
    try:
        return block_user(
            db,
            actor=actor,
            user_id=user_id,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_c19_error(db, exc)


@router.delete("/blocks/{user_id}", response_model=C19UserChangeRead)
def block_delete_endpoint(
    request: Request,
    user_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> C19UserChangeRead:
    try:
        return unblock_user(
            db,
            actor=actor,
            user_id=user_id,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_c19_error(db, exc)


__all__ = ["router"]
