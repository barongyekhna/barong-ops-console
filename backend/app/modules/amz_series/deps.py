"""A 系列的门。

- ``require_amz_access``:进模块的门。owner 直接过;其余必须至少有一条 ``amz_store_grants``。
  **没有 super_admin 直通**(SM 的 ``_require_sm_permission`` 放 super_admin,这里刻意不同):
  王维是制造公司的 super_admin,他必须 403。
- ``require_store(min_role)``:店铺级的门。按路径 ``store_code`` 查店 + 授权行,view < operate < grant。
- 路由**绝不**用 ``require_permission("amz.ops.*")``——决策引擎也会放 super_admin。
- 不把 ``/api/app/amz`` 加进 org 上下文豁免:A 表没有 org_id 列,隔离上下文对它无影响,
  王创鑫活跃组织是深圳时照样能查。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.roles import is_owner_role
from ...db.session import get_db
from ...models.user import User
from .constants import STORE_ROLE_GRANT, STORE_ROLE_RANK
from .models import AmzStore, AmzStoreGrant


@dataclass(frozen=True)
class StoreAccess:
    user: User
    store: AmzStore
    role: str


def granted_store_codes(db: Session, user: User) -> list[str] | None:
    """调用者能看的店铺集合;owner 返回 None 表示全部。"""
    if is_owner_role(user.role):
        return None
    return list(
        db.scalars(
            select(AmzStoreGrant.store_code)
            .where(AmzStoreGrant.user_id == int(user.id))
            .order_by(AmzStoreGrant.store_code)
        )
    )


def require_amz_access(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    if is_owner_role(user.role):
        return user
    has_grant = db.scalar(
        select(AmzStoreGrant.store_code).where(AmzStoreGrant.user_id == int(user.id)).limit(1)
    )
    if has_grant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No Amazon store grants.")
    return user


def require_store(min_role: str):
    if min_role not in STORE_ROLE_RANK:
        raise ValueError(f"unknown store role: {min_role}")

    def dependency(
        store_code: str,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> StoreAccess:
        code = (store_code or "").strip().lower()
        store = db.get(AmzStore, code)
        if store is None or store.status != "active":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Amazon store not found.")
        if is_owner_role(user.role):
            return StoreAccess(user=user, store=store, role=STORE_ROLE_GRANT)
        grant = db.get(AmzStoreGrant, (int(user.id), code))
        if grant is None or STORE_ROLE_RANK.get(grant.role, 0) < STORE_ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Store {code} requires role {min_role}.",
            )
        return StoreAccess(user=user, store=store, role=grant.role)

    return dependency


__all__ = ["StoreAccess", "granted_store_codes", "require_amz_access", "require_store"]
