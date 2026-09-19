"""亚马逊组织主页的两张卡(A0):店铺总览、数字员工在岗。只 select;按调用者的店铺授权过滤。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.roles import is_owner_role
from ...models.user import User
from ...services.worker_heartbeat import list_heartbeats
from ..home.schemas import HomeCardItem, HomeCardRead
from . import service
from .constants import AGENTS_WORKER_NAME, EMPLOYEE_ROLE_LABELS, EMPLOYEE_USERNAMES, EMPLOYEES, MODULE_KEY
from .persona import display_name
from .models import AmzStoreGrant

CARD_STORES = "amz-stores"
CARD_AGENTS = "amz-agents"
AMZ_HREF = "/amz"
C19_HREF = "/c19"


def _granted(db: Session, user: User) -> list[str] | None:
    if is_owner_role(user.role):
        return None
    return list(db.scalars(select(AmzStoreGrant.store_code).where(AmzStoreGrant.user_id == int(user.id))))


def load_stores_card(db: Session, *, workspace_key: str, user: User, **_: Any) -> HomeCardRead | None:
    codes = _granted(db, user)
    stores = service.list_visible_stores(db, store_codes=codes)
    # 主页是「这个组织」的主页:只列本法人的店(owner 也一样),跨店合计去模块页看。
    stores = [store for store in stores if store.company_org_id == workspace_key]
    if not stores:
        return None
    summaries = service.store_summaries(db, stores=stores, user=user, is_owner=is_owner_role(user.role))
    items = []
    warn = 0
    for item in summaries:
        view = service.summary_view(item)
        acos = view["ads"]["acos_pct"]
        subtitle = (
            f"ACOS {acos}% · 花费 {view['ads']['spend']:.0f} · 单 {view['ads']['orders']}"
            if acos is not None
            else "尚无广告数据"
        )
        if acos is not None and acos >= 40:
            warn += 1
        items.append(HomeCardItem(id=item.store.store_code, title=view["display_name"], subtitle=subtitle, href=AMZ_HREF))
    return HomeCardRead(
        card_id=CARD_STORES,
        module_key=MODULE_KEY,
        count=len(stores),
        items=items[:5],
        freshness=datetime.now(UTC),
        actions=[],
        extra={"stores": [service.summary_view(item) for item in summaries]},
        severity="warn" if warn else "ok",
    )


def load_agents_card(db: Session, *, workspace_key: str, user: User, **_: Any) -> HomeCardRead:
    beats = {beat["worker_name"]: beat for beat in list_heartbeats(db)}
    items = []
    stale = 0
    for employee in EMPLOYEES:
        username = EMPLOYEE_USERNAMES[employee]
        beat = beats.get(f"{AGENTS_WORKER_NAME}:{username}")
        alive = bool(beat) and not bool(beat.get("stale"))
        if not alive:
            stale += 1
        items.append(
            HomeCardItem(
                id=username,
                title=display_name(employee),
                subtitle="在岗" if alive else "未上岗",
                at=beat.get("last_success_at") if beat else None,
                href=C19_HREF,
            )
        )
    return HomeCardRead(
        card_id=CARD_AGENTS,
        module_key=None,
        count=len(EMPLOYEES) - stale,
        items=items,
        freshness=datetime.now(UTC),
        actions=[],
        extra={"workspace_key": workspace_key, "stale": stale, "total": len(EMPLOYEES), "roles": [EMPLOYEE_ROLE_LABELS[e] for e in EMPLOYEES]},
        severity="ok" if stale == 0 else "warn",
    )


__all__ = ["CARD_AGENTS", "CARD_STORES", "load_agents_card", "load_stores_card"]
