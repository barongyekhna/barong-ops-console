from __future__ import annotations

import logging
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
from ...services.api_stability import (
    api_snapshot_key,
    degraded_snapshot,
    get_api_snapshot,
    raise_structured_api_error,
    save_api_snapshot,
    stable_read_failure,
)
from ..deps import get_audit_context, get_current_user, require_rbac

router = APIRouter(prefix="/approval", tags=["approval"])
ResultT = TypeVar("ResultT")
logger = logging.getLogger(__name__)


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
    request: Request,
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
    cache_key = api_snapshot_key(
        "approval.list",
        user.id,
        user.role,
        getattr(request.state, "org_id", None),
        status_filter,
        category,
        limit,
        offset,
    )
    try:
        items = service.list_approvals(
            user=user,
            status=status_filter,
            category=category,
            limit=limit,
            offset=offset,
        )
        response = ListResponse(
            items=items,
            count=len(items),
            limit=limit,
            offset=offset,
        )
        save_api_snapshot(cache_key, response)
        return response
    except ApprovalServiceError as exc:
        raise _service_http_error(exc) from None
    except Exception as exc:
        db.rollback()
        stable_read_failure(
            logger=logger,
            route="/approval/list",
            exc=exc,
            request=request,
            code="approval_list_failed",
        )
        snapshot = get_api_snapshot(cache_key)
        if snapshot is not None:
            return degraded_snapshot(
                snapshot,
                code="approval_list_failed",
                message="Approval list is using the last successful snapshot because the live read failed.",
                request=request,
            )
        raise_structured_api_error(
            code="approval_list_failed",
            message="Approval list is temporarily unavailable.",
            request=request,
            retryable=True,
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
