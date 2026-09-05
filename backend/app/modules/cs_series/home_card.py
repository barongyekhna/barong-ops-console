"""客服模块给主页的那张卡：新消息。只 select，不写。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..home.schemas import HomeCardItem, HomeCardRead
from .models import CSMessage

CARD_ID = "cs-inbox"
MODULE_KEY = "cs.customer_service"
CHANNEL_LABEL = {"retail": "零售", "wholesale": "批发"}


def load_home_card(
    db: Session,
    *,
    workspace_key: str,
    user: Any,
    permission_keys: frozenset[str],
    is_full_access: bool,
    **_: Any,
) -> HomeCardRead:
    base = (
        CSMessage.org_id == workspace_key,
        CSMessage.workspace_key == workspace_key,
        CSMessage.status == "new",
    )
    per_channel = db.execute(
        select(CSMessage.channel, func.count())
        .where(*base)
        .group_by(CSMessage.channel)
    ).all()
    counts = {str(channel): int(count) for channel, count in per_channel}
    rows = db.scalars(
        select(CSMessage)
        .where(*base)
        .order_by(CSMessage.created_at.desc(), CSMessage.id.desc())
        .limit(5)
    ).all()
    items = [
        HomeCardItem(
            id=str(row.id),
            title=f"{row.name} · {CHANNEL_LABEL.get(row.channel, row.channel)}",
            subtitle=(row.message or "")[:80],
            at=row.created_at,
            href=f"/cs?channel={row.channel}&message={row.id}",
        )
        for row in rows
    ]
    return HomeCardRead(
        card_id=CARD_ID,
        module_key=MODULE_KEY,
        count=sum(counts.values()),
        items=items,
        freshness=datetime.now(UTC),
        actions=["reply", "resolve"],
        extra={"retail": counts.get("retail", 0), "wholesale": counts.get("wholesale", 0)},
    )
