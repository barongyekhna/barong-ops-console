from __future__ import annotations

from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
from contextvars import copy_context
from dataclasses import dataclass
import logging
from collections.abc import Callable
from typing import TypeVar, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...db.session import get_db, managed_read_session
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
    APPROVAL_LIST_DEFAULT_LIMIT,
    APPROVAL_LIST_MAX_LIMIT,
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
    save_api_snapshot,
    stable_read_failure,
)
from ..deps import get_audit_context, get_current_user, require_rbac

router = APIRouter(prefix="/approval", tags=["approval"])
ResultT = TypeVar("ResultT")
logger = logging.getLogger(__name__)
APPROVAL_LIST_TIMEOUT_SECONDS = 2.0
APPROVAL_LIST_DB_STATEMENT_TIMEOUT_MS = 1800
_APPROVAL_LIST_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="approval-list",
)


@dataclass(frozen=True)
class _ApprovalListUser:
    id: int
    role: str


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


def _approval_list_degraded_response() -> JSONResponse:
    return JSONResponse(
        {
            "status": "degraded",
            "data": [],
            "message": "approvals temporarily unavailable",
        },
        status_code=status.HTTP_200_OK,
    )


def _apply_approval_list_statement_timeout(db: Session) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    db.execute(
        text(
            "SET LOCAL statement_timeout = "
            f"{APPROVAL_LIST_DB_STATEMENT_TIMEOUT_MS}"
        )
    )


def _approval_list_live_read(
    *,
    user: _ApprovalListUser,
    status_filter: ApprovalRequestStatus | None,
    category: ApprovalCategory | None,
    limit: int,
    offset: int,
    cursor: str | None,
) -> ListResponse[ApprovalListItem]:
    with managed_read_session() as db:
        _apply_approval_list_statement_timeout(db)
        service = ApprovalService(db)
        page = service.list_approval_page(
            user=cast(User, user),
            status=status_filter,
            category=category,
            limit=limit,
            offset=offset,
            cursor=cursor,
        )
        return ListResponse(
            items=page.items,
            count=len(page.items),
            limit=limit,
            offset=offset,
            cursor=cursor,
            next_cursor=page.next_cursor,
        )


def _log_timed_out_approval_list(
    future: Future[ListResponse[ApprovalListItem]],
) -> None:
    try:
        future.result()
    except Exception as exc:
        logger.warning(
            "Timed-out approval list worker finished with an error: %s",
            exc,
            exc_info=True,
        )


def _run_approval_list_with_timeout(
    operation: Callable[[], ListResponse[ApprovalListItem]],
) -> ListResponse[ApprovalListItem] | JSONResponse:
    context = copy_context()
    future = _APPROVAL_LIST_EXECUTOR.submit(context.run, operation)
    try:
        return future.result(timeout=APPROVAL_LIST_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        future.add_done_callback(_log_timed_out_approval_list)
        logger.warning(
            "Approval list exceeded %.1fs timeout; returning degraded response.",
            APPROVAL_LIST_TIMEOUT_SECONDS,
        )
        return _approval_list_degraded_response()


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
    limit: int = Query(
        default=APPROVAL_LIST_DEFAULT_LIMIT,
        ge=1,
        le=APPROVAL_LIST_MAX_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
    user: User = Depends(get_current_user),
) -> ListResponse[ApprovalListItem] | JSONResponse:
    list_user = _ApprovalListUser(id=user.id, role=user.role)
    cache_key = api_snapshot_key(
        "approval.list",
        user.id,
        user.role,
        getattr(request.state, "org_id", None),
        status_filter,
        category,
        limit,
        offset,
        cursor,
    )
    try:
        response = _run_approval_list_with_timeout(
            lambda: _approval_list_live_read(
                user=list_user,
                status_filter=status_filter,
                category=category,
                limit=limit,
                offset=offset,
                cursor=cursor,
            )
        )
        if isinstance(response, JSONResponse):
            return response
        save_api_snapshot(cache_key, response)
        return response
    except ApprovalServiceError as exc:
        raise _service_http_error(exc) from None
    except Exception as exc:
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
        return _approval_list_degraded_response()


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
