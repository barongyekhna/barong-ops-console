"""W 系列给主页的那张卡：待处理订单。

`w_orders` 没有 org 列，隔离靠注册表的 `needs_target_org` 门。这里绝不调
`logistics.list_orders`（它会回收过期同步任务并 commit）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..home.schemas import HomeCardItem, HomeCardRead
from .shipping.models import WOrder

CARD_ID = "w-orders"
MODULE_KEY = "w.site_ops"
PENDING_WOO_STATUSES = ("processing", "on-hold")


def load_home_card(
    db: Session,
    *,
    workspace_key: str,
    user: Any,
    permission_keys: frozenset[str],
    is_full_access: bool,
    **_: Any,
) -> HomeCardRead:
    pending = (
        WOrder.woo_status.in_(PENDING_WOO_STATUSES),
        WOrder.tracking_status == "none",
    )
    count = int(db.scalar(select(func.count()).select_from(WOrder).where(*pending)) or 0)
    exceptions = int(
        db.scalar(
            select(func.count())
            .select_from(WOrder)
            .where(WOrder.tracking_status == "exception")
        )
        or 0
    )
    rows = db.scalars(
        select(WOrder)
        .where(*pending)
        .order_by(WOrder.placed_at.desc().nulls_last(), WOrder.created_at.desc())
        .limit(5)
    ).all()
    items = [
        HomeCardItem(
            id=str(row.id),
            title=f"#{row.order_number}",
            subtitle=" · ".join(
                part
                for part in (
                    row.customer_name or "",
                    row.country or "",
                    f"{row.total} {row.currency or ''}".strip() if row.total is not None else "",
                )
                if part
            ),
            at=row.placed_at or row.created_at,
            href=f"/w-s?order={row.id}",
        )
        for row in rows
    ]
    return HomeCardRead(
        card_id=CARD_ID,
        module_key=MODULE_KEY,
        count=count,
        items=items,
        freshness=datetime.now(UTC),
        actions=["copy_tracking"],
        extra={"exceptions": exceptions},
        severity="warn" if exceptions else "ok",
    )
