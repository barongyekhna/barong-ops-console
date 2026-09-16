"""A 系列人用端点。全部挂 ``/api/app/amz``(只挂一次,A0 没有机器端点)。

门:整个 router 先过 ``require_amz_access``(owner 或至少一条店铺授权;super_admin 不直通),
店铺级端点再过 ``require_store(min_role)``。新加端点要同步登记前端代理白名单 ``isAllowedAmzPath``。
"""

from __future__ import annotations

from typing import Any

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.roles import is_owner_role
from ...db.session import get_db
from ...models.user import User
from ...repositories.operation_logs import create_operation_log
from . import service, suggestions
from .constants import MODULE_KEY, STORE_ROLE_GRANT, STORE_ROLE_VIEW, STORE_ROLES
from .deps import StoreAccess, granted_store_codes, require_amz_access, require_store

router = APIRouter(prefix="/amz", tags=["amz-ops"], dependencies=[Depends(require_amz_access)])


def _raise(exc: service.AmzServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return str(value) if value else None


# ---------------------------------------------------------------- 店铺


@router.get("/stores")
def stores_list(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    codes = granted_store_codes(db, user)
    stores = service.list_visible_stores(db, store_codes=codes)
    summaries = service.store_summaries(db, stores=stores, user=user, is_owner=is_owner_role(user.role))
    return {
        "module_key": MODULE_KEY,
        "is_owner": is_owner_role(user.role),
        "items": [service.summary_view(item) for item in summaries],
    }


@router.get("/stores/{store_code}")
def store_detail(
    access: StoreAccess = Depends(require_store(STORE_ROLE_VIEW)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    summaries = service.store_summaries(
        db, stores=[access.store], user=access.user, is_owner=is_owner_role(access.user.role)
    )
    payload = service.summary_view(summaries[0])
    payload["seed_imports"] = [
        _seed_view(item) for item in service.list_seed_imports(db, store_codes=[access.store.store_code])
    ]
    return payload


# ---------------------------------------------------------------- 授权


class GrantUpsert(BaseModel):
    user_id: int = Field(ge=1)
    role: str = Field(pattern="^(" + "|".join(STORE_ROLES) + ")$")


def _grant_view(grant: Any) -> dict[str, Any]:
    return {
        "user_id": int(grant.user_id),
        "store_code": grant.store_code,
        "role": grant.role,
        "granted_by_user_id": grant.granted_by_user_id,
        "created_at": grant.created_at.isoformat() if grant.created_at else None,
    }


@router.get("/stores/{store_code}/grants")
def grants_list(
    access: StoreAccess = Depends(require_store(STORE_ROLE_GRANT)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"items": [_grant_view(item) for item in service.list_grants(db, store_code=access.store.store_code)]}


@router.post("/stores/{store_code}/grants")
def grants_upsert(
    payload: GrantUpsert,
    request: Request,
    access: StoreAccess = Depends(require_store(STORE_ROLE_GRANT)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        grant = service.upsert_grant(
            db,
            store_code=access.store.store_code,
            user_id=payload.user_id,
            role=payload.role,
            granted_by=access.user,
        )
    except service.AmzServiceError as exc:
        _raise(exc)
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(access.user.id),
        action="amz.grant.upsert",
        target_type="amz_store",
        target_id=access.store.store_code,
        result="success",
        request_id=_request_id(request),
        details={"user_id": payload.user_id, "role": payload.role},
    )
    db.commit()
    return _grant_view(grant)


@router.delete("/stores/{store_code}/grants/{user_id}")
def grants_delete(
    user_id: int,
    request: Request,
    access: StoreAccess = Depends(require_store(STORE_ROLE_GRANT)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    removed = service.delete_grant(db, store_code=access.store.store_code, user_id=user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="grant not found")
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(access.user.id),
        action="amz.grant.delete",
        target_type="amz_store",
        target_id=access.store.store_code,
        result="success",
        request_id=_request_id(request),
        details={"user_id": user_id},
    )
    db.commit()
    return {"removed": True}


# ---------------------------------------------------------------- 种子 / 员工


def _seed_view(item: Any) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "file_name": item.file_name,
        "store_code": item.store_code,
        "kind": item.kind,
        "rows": item.rows,
        "checksum": item.checksum,
        "details": item.details_json or {},
        "imported_at": item.imported_at.isoformat() if item.imported_at else None,
    }


@router.get("/seed-imports")
def seed_imports_list(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    codes = granted_store_codes(db, user)
    return {"items": [_seed_view(item) for item in service.list_seed_imports(db, store_codes=codes)]}


@router.get("/employees")
def employees_list(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """员工面板:每人未读数、紧急数、最新一条消息(按调用者能看的店铺)。"""
    codes = granted_store_codes(db, user)
    return suggestions.employee_panel(db, store_codes=codes)


# ---------------------------------------------------------------- 建议(员工消息)


@router.get("/suggestions")
def suggestions_list(
    employee: str | None = Query(default=None, pattern="^[A-Da-d]$"),
    store: str | None = Query(default=None, pattern="^0\\d(?:us|de)$"),
    status: str = Query(default="open", pattern="^(open|approved|rejected|later|expired|executed|all)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    codes = granted_store_codes(db, user)
    if store:
        if codes is not None and store not in codes:
            raise HTTPException(status_code=403, detail=f"no access to store {store}")
        codes = [store]
    rows = suggestions.list_suggestions(db, store_codes=codes, employee=employee, status=status)
    return {"items": [suggestions.suggestion_view(row) for row in rows], "shadow": True}


class DecidePayload(BaseModel):
    decision: str = Field(pattern="^(approve|reject|later)$")
    reason: str | None = Field(default=None, max_length=2000)


@router.post("/suggestions/{suggestion_id}/decide")
def suggestions_decide(
    suggestion_id: UUID,
    payload: DecidePayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """影子期:只记录你的判断(和驳回原因),不碰亚马逊。"""
    codes = granted_store_codes(db, user)
    try:
        row = suggestions.decide_suggestion(
            db,
            suggestion_id=suggestion_id,
            decision=payload.decision,
            reason=payload.reason,
            actor=user,
            allowed_store_codes=codes,
            request_id=_request_id(request),
        )
    except service.AmzServiceError as exc:
        _raise(exc)
    db.commit()
    return suggestions.suggestion_view(row)


@router.get("/overview/series")
def overview_series(
    store: str | None = Query(default=None, pattern="^0\\d(?:us|de)$"),
    days: int = Query(default=30, ge=7, le=120),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    codes = granted_store_codes(db, user)
    if store:
        if codes is not None and store not in codes:
            raise HTTPException(status_code=403, detail=f"no access to store {store}")
        codes = [store]
    return suggestions.daily_series(db, store_codes=codes, days=days)


__all__ = ["router"]
