from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from ...core.roles import is_owner_role
from ...db.session import get_db
from ...models.user import User
from ...repositories.operation_logs import list_operation_logs
from ...schemas.common import ListResponse
from ...schemas.operation_logs import OperationLogResponse
from ...schemas.user import UserResponse, is_user_manager_role
from ...services.approval_service import ApprovalService, ApprovalServiceError
from ...services.permission_decision_engine import PermissionDecisionEngine
from ...services.user_management_service import list_users
from ...services.unified_permission_engine import UnifiedPermissionRequest
from .health import lightweight_health_payload
from ..deps import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

DashboardEntry = dict[str, Any]


def _entry(*, ok: bool, status: int, data: Any = None, detail: Any = None) -> DashboardEntry:
    return {
        "data": jsonable_encoder(data) if ok else None,
        "detail": None if ok else detail,
        "ok": ok,
        "status": status,
    }


def _can_read(
    *,
    db: Session,
    request: Request,
    user: User,
    module_id: str,
    action: str,
) -> bool:
    decision = PermissionDecisionEngine(db, request=request).decide_platform_metadata(
        UnifiedPermissionRequest(
            user_id=user.id,
            org_id=getattr(request.state, "org_id", None),
            module_id=module_id,
            action=action,
            role=user.role,
            scope_type="global",
            scope_key="*",
            source="dashboard_batch",
        )
    )
    return decision.allowed


def _guarded_entry(
    *,
    db: Session,
    request: Request,
    user: User,
    module_id: str,
    action: str,
    loader: Callable[[], Any],
) -> DashboardEntry:
    if not _can_read(
        db=db,
        request=request,
        user=user,
        module_id=module_id,
        action=action,
    ):
        return _entry(ok=False, status=403, detail="Permission denied.")

    try:
        return _entry(ok=True, status=200, data=loader())
    except PermissionError:
        return _entry(ok=False, status=403, detail="Permission denied.")
    except Exception:
        return _entry(ok=False, status=500, detail="Dashboard resource failed.")


@router.get("/overview")
def dashboard_overview(
    request: Request,
    limit: int = Query(default=1, ge=1, le=10),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, DashboardEntry]:
    def users_payload() -> ListResponse[UserResponse]:
        if not is_user_manager_role(user.role):
            raise PermissionError("Owner or super admin role required.")

        effective_org = None
        if not is_owner_role(user.role):
            effective_org = user.organization_id
            if effective_org is None:
                return ListResponse(items=[], count=0, limit=limit, offset=offset)

        result = list_users(
            db,
            limit=limit,
            offset=offset,
            organization_id=effective_org,
        )
        return ListResponse(
            items=[UserResponse.model_validate(item) for item in result.items],
            count=result.count,
            limit=limit,
            offset=offset,
        )

    return {
        "health": _entry(ok=True, status=200, data=lightweight_health_payload()),
        "users": _guarded_entry(
            db=db,
            request=request,
            user=user,
            module_id="ADMIN",
            action="admin",
            loader=users_payload,
        ),
    }


@router.get("/activity")
def dashboard_activity(
    request: Request,
    approval_limit: int = Query(default=50, ge=1, le=100),
    approval_offset: int = Query(default=0, ge=0),
    log_limit: int = Query(default=8, ge=1, le=25),
    log_offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, DashboardEntry]:
    def logs_payload() -> ListResponse[OperationLogResponse]:
        items = list_operation_logs(
            db,
            limit=log_limit,
            offset=log_offset,
            cursor=None,
        )
        return ListResponse(
            items=[OperationLogResponse.model_validate(item) for item in items],
            count=len(items),
            limit=log_limit,
            offset=log_offset,
        )

    def approvals_payload() -> ListResponse[Any]:
        try:
            items = ApprovalService(db).list_approvals(
                user=user,
                status=None,
                category=None,
                limit=approval_limit,
                offset=approval_offset,
            )
        except ApprovalServiceError as exc:
            raise ValueError(str(exc)) from None
        return ListResponse(
            items=items,
            count=len(items),
            limit=approval_limit,
            offset=approval_offset,
        )

    return {
        "operation_logs": _guarded_entry(
            db=db,
            request=request,
            user=user,
            module_id="AUDIT",
            action="admin",
            loader=logs_payload,
        ),
        "approvals": _guarded_entry(
            db=db,
            request=request,
            user=user,
            module_id="GOVERNANCE",
            action="read",
            loader=approvals_payload,
        ),
    }
