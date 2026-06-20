from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.approval import (
    ApprovalCategory,
    ApprovalDecisionAction,
    ApprovalDetailResponse,
    ApprovalListItem,
    ApprovalRequestCreate,
    ApprovalRequestStatus,
)
from ...schemas.common import ListResponse
from ...services.approval_service import (
    ApprovalConflictError,
    ApprovalInvalidRequestError,
    ApprovalInvalidStateError,
    ApprovalNotFoundError,
    ApprovalPermissionDeniedError,
    ApprovalService,
    ApprovalServiceError,
)
from ..deps import get_audit_context, get_current_user, require_rbac

router = APIRouter(prefix="/approval", tags=["approval"])
ResultT = TypeVar("ResultT")


def _service_http_error(exc: ApprovalServiceError) -> HTTPException:
    if isinstance(exc, ApprovalPermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    if isinstance(exc, ApprovalNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    if isinstance(exc, ApprovalConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    if isinstance(exc, ApprovalInvalidStateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    if isinstance(exc, ApprovalInvalidRequestError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=str(exc),
    )


def _run_read(operation: Callable[[], ResultT]) -> ResultT:
    try:
        return operation()
    except ApprovalServiceError as exc:
        raise _service_http_error(exc) from None


def _run_write(db: Session, operation: Callable[[], ResultT]) -> ResultT:
    try:
        result = operation()
        db.commit()
        return result
    except ApprovalServiceError as exc:
        db.rollback()
        raise _service_http_error(exc) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval persistence conflict.",
        ) from None


@router.post(
    "/request",
    response_model=ApprovalDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def approval_request_create(
    payload: ApprovalRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "write")),
) -> ApprovalDetailResponse:
    service = ApprovalService(db)
    return _run_write(
        db,
        lambda: service.request_approval(payload, user=user),
    )


@router.get("/list", response_model=ListResponse[ApprovalListItem])
def approval_list(
    status_filter: ApprovalRequestStatus | None = Query(
        default=None,
        alias="status",
    ),
    category: ApprovalCategory | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListResponse[ApprovalListItem]:
    service = ApprovalService(db)
    items = _run_read(
        lambda: service.list_approvals(
            user=user,
            status=status_filter,
            category=category,
            limit=limit,
            offset=offset,
        )
    )
    return ListResponse(
        items=items,
        count=len(items),
        limit=limit,
        offset=offset,
    )


@router.get("/{approval_id}", response_model=ApprovalDetailResponse)
def approval_detail(
    approval_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApprovalDetailResponse:
    service = ApprovalService(db)
    return _run_read(lambda: service.get_approval(approval_id, user=user))


@router.post("/{approval_id}/approve", response_model=ApprovalDetailResponse)
def approval_approve(
    request: Request,
    approval_id: str,
    payload: ApprovalDecisionAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "admin")),
) -> ApprovalDetailResponse:
    service = ApprovalService(db)
    return _run_write(
        db,
        lambda: service.approve(
            approval_id,
            payload,
            user=user,
            audit=get_audit_context(request),
        ),
    )


@router.post("/{approval_id}/reject", response_model=ApprovalDetailResponse)
def approval_reject(
    request: Request,
    approval_id: str,
    payload: ApprovalDecisionAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "admin")),
) -> ApprovalDetailResponse:
    service = ApprovalService(db)
    return _run_write(
        db,
        lambda: service.reject(
            approval_id,
            payload,
            user=user,
            audit=get_audit_context(request),
        ),
    )
