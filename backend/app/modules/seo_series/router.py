"""SEO 内容引擎控制台 API——本期只有工艺事实库。

事实库本体在 ``content_core.facts``(共享给 GEO/B2B),这里是它的人工入口:
列表 / 新增 / 编辑 / 批准 / 停用 / 版本历史 / **需复核清单**。

权限与 P/F/GEO 同规:owner / super_admin 直通,否则要有对应 ``seo.content.*``;
execute / manage 蕴含 read。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.roles import is_super_admin_role
from ...db.session import get_db
from ...models.user import User
from ...services.permission_service import resolve_current_user_permission_info
from ..content_core.facts import service as facts
from ..content_core.facts.models import CraftFact, CraftFactRevision
from ..k_series.product_knowledge.constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_WORKSPACE_KEY,
)
from ..k_series.product_knowledge.scope_shim import KScopeContext

router = APIRouter(prefix="/seo", tags=["seo-content"])

_IMPLIED_BY = {
    "seo.content.read": ("seo.content.read", "seo.content.execute", "seo.content.manage"),
    "seo.content.execute": ("seo.content.execute", "seo.content.manage"),
    "seo.content.manage": ("seo.content.manage",),
}


def _require_seo_permission(permission_key: str):
    """owner / super_admin 直通;execute / manage 蕴含 read。"""

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(db, user, request=request)
        if (
            permissions.is_owner_full_access
            or is_super_admin_role(getattr(user, "role", None))
            or set(_IMPLIED_BY[permission_key]).intersection(
                permissions.permission_keys
            )
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"缺少权限 {permission_key}。",
        )

    return dependency


def _scope(request: Request | None) -> KScopeContext:
    """与 GEO 同一套 scope 推导,好让两边写出来的行落在同一个工作区。"""
    org_id = None
    if request is not None:
        org_id = getattr(request.state, "org_id", None)
        if org_id is None:
            org_context = getattr(request.state, "org_context", None)
            org_id = getattr(org_context, "org_id", None)
    return KScopeContext(
        workspace_key=str(org_id).strip() if org_id else DEFAULT_WORKSPACE_KEY,
        business_context=DEFAULT_BUSINESS_CONTEXT,
        scope_mode="production",
    )


class FactIn(BaseModel):
    topic: str = Field(min_length=1, max_length=64)
    claim: str = Field(min_length=1)
    detail: str | None = None
    value: str | None = None
    unit: str | None = None
    basis: str | None = None
    product_ids: list[str] | None = None


class FactPatch(BaseModel):
    topic: str | None = None
    claim: str | None = None
    detail: str | None = None
    value: str | None = None
    unit: str | None = None
    basis: str | None = None
    product_ids: list[str] | None = None
    change_reason: str | None = None


def _serialize(fact: CraftFact) -> dict[str, Any]:
    return {
        "id": str(fact.id),
        "topic": fact.topic,
        "claim": fact.claim,
        "detail": fact.detail,
        "value": fact.value,
        "unit": fact.unit,
        "basis": fact.basis,
        "status": fact.status,
        "version": fact.version,
        "product_ids": fact.product_ids_json or [],
        "approved_at": fact.approved_at.isoformat() if fact.approved_at else None,
        "updated_at": fact.updated_at.isoformat() if fact.updated_at else None,
    }


@router.get("/facts")
def list_facts(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.read")),
) -> dict[str, Any]:
    """全部事实 + 需复核清单。

    ``stale`` 是这套设计的意义所在:工艺一改,引用旧版的内容立刻在这里显形——
    **过期的真话和编造一样有害**,而且没有任何输出护栏会报警。
    """
    from sqlalchemy import select

    from ..k_series.product_knowledge.scope_shim import apply_scope_filters

    query = apply_scope_filters(select(CraftFact), CraftFact, _scope(request))
    rows = list(
        db.execute(query.order_by(CraftFact.topic, CraftFact.created_at)).scalars()
    )
    return {
        "facts": [_serialize(f) for f in rows],
        "topics": sorted({f.topic for f in rows}),
        "approved_count": sum(1 for f in rows if f.status == "approved"),
        "stale": facts.stale_content(db),
    }


@router.post("/facts", status_code=status.HTTP_201_CREATED)
def create_fact(
    request: Request,
    payload: FactIn,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    try:
        fact = facts.create_fact(
            db,
            topic=payload.topic,
            claim=payload.claim,
            detail=payload.detail,
            value=payload.value,
            unit=payload.unit,
            basis=payload.basis,
            product_ids=payload.product_ids,
            scope_context=_scope(request),
            user=user,
        )
    except facts.CraftFactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return _serialize(fact)


@router.patch("/facts/{fact_id}")
def update_fact(
    fact_id: UUID,
    payload: FactPatch,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_none=True)
    reason = changes.pop("change_reason", None)
    if "product_ids" in changes:
        changes["product_ids_json"] = changes.pop("product_ids")
    try:
        fact, bumped = facts.update_fact(
            db, fact_id=fact_id, changes=changes, change_reason=reason, user=user
        )
    except facts.CraftFactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return {
        **_serialize(fact),
        "version_bumped": bumped,
        # 实质修改会退回 draft,这句是给前端提示用户「改完要重新批准」。
        "note": (
            "实质内容已变更，版本升至 v%d 并退回待批准。"
            "引用旧版的内容已进入需复核清单。" % fact.version
        )
        if bumped
        else None,
    }


@router.post("/facts/{fact_id}/approve")
def approve_fact(
    fact_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    try:
        fact = facts.approve_fact(db, fact_id=fact_id, user=user)
    except facts.CraftFactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return _serialize(fact)


@router.post("/facts/{fact_id}/retire")
def retire_fact(
    fact_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.manage")),
) -> dict[str, Any]:
    """停用一条事实——不删除,因为已发布内容还引用着它,历史要查得到。"""
    fact = db.get(CraftFact, fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="这条工艺事实不存在。")
    fact.status = "retired"
    db.commit()
    return _serialize(fact)


@router.get("/facts/{fact_id}/revisions")
def fact_revisions(
    fact_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_seo_permission("seo.content.read")),
) -> dict[str, Any]:
    from sqlalchemy import select

    rows = list(
        db.execute(
            select(CraftFactRevision)
            .where(CraftFactRevision.fact_id == fact_id)
            .order_by(CraftFactRevision.version.desc())
        ).scalars()
    )
    return {
        "revisions": [
            {
                "version": r.version,
                "snapshot": r.snapshot_json or {},
                "change_reason": r.change_reason,
                "changed_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


__all__ = ["router"]
