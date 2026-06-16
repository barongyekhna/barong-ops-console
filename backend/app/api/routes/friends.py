from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.messaging_permission import (
    FriendActionRequest,
    FriendRequest,
    FriendRequestCreateRequest,
)
from ...services.messaging_permission import (
    FriendRequestConflictError,
    FriendRequestDeniedError,
    FriendRequestNotFoundError,
    accept_friend_request,
    create_friend_request,
    list_friend_requests_for_actor,
    reject_friend_request,
)
from ..deps import get_audit_context, get_current_user

router = APIRouter(prefix="/friends", tags=["friends"])


def _raise_friend_error(exc: Exception) -> NoReturn:
    if isinstance(exc, FriendRequestNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Friend request not found.",
        ) from None
    if isinstance(exc, FriendRequestConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    if isinstance(exc, FriendRequestDeniedError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from None
    raise exc


@router.post(
    "/request",
    response_model=FriendRequest,
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "Friend request denied"},
        status.HTTP_409_CONFLICT: {"description": "Friend request conflict"},
    },
)
def request_friend(
    payload: FriendRequestCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> FriendRequest:
    try:
        return create_friend_request(
            db,
            payload=payload,
            actor=actor,
            audit=get_audit_context(request),
        )
    except Exception as exc:
        _raise_friend_error(exc)


@router.post(
    "/accept",
    response_model=FriendRequest,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Friend request not found"},
        status.HTTP_409_CONFLICT: {"description": "Friend request conflict"},
    },
)
def accept_friend(
    payload: FriendActionRequest,
    actor: User = Depends(get_current_user),
) -> FriendRequest:
    try:
        return accept_friend_request(payload=payload, actor=actor)
    except Exception as exc:
        _raise_friend_error(exc)


@router.post(
    "/reject",
    response_model=FriendRequest,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Friend request not found"},
        status.HTTP_409_CONFLICT: {"description": "Friend request conflict"},
    },
)
def reject_friend(
    payload: FriendActionRequest,
    actor: User = Depends(get_current_user),
) -> FriendRequest:
    try:
        return reject_friend_request(payload=payload, actor=actor)
    except Exception as exc:
        _raise_friend_error(exc)


@router.get("/list", response_model=list[FriendRequest])
def list_friends(actor: User = Depends(get_current_user)) -> list[FriendRequest]:
    try:
        return list_friend_requests_for_actor(actor=actor)
    except Exception as exc:
        _raise_friend_error(exc)
