"""B2B 给主页的那张卡：待人工审核的开发信草稿 + 退信率是否逼近红线。

浮窗里只有「看」和「驳回」。发送永远不在主页发生——actions 里没有 send，
前端也不会为这张卡渲染任何发送控件。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..home.schemas import HomeCardItem, HomeCardRead
from .outreach.models import B2BEmailDraft
from .outreach.suppression import B2BSuppression
from .prospects.models import B2BProspect

CARD_ID = "b2b-drafts"
MODULE_KEY = "b2b.wholesale"
# 家规红线 3%；2.5% 起提前亮黄。
BOUNCE_WARN_RATE = 0.025
BOUNCE_RED_LINE = 0.03


def load_home_card(
    db: Session,
    *,
    workspace_key: str,
    user: Any,
    permission_keys: frozenset[str],
    is_full_access: bool,
    **_: Any,
) -> HomeCardRead:
    drafts = int(
        db.scalar(
            select(func.count()).select_from(B2BEmailDraft).where(B2BEmailDraft.status == "draft")
        )
        or 0
    )
    sent = int(
        db.scalar(
            select(func.count()).select_from(B2BEmailDraft).where(B2BEmailDraft.status == "sent")
        )
        or 0
    )
    bounces = int(
        db.scalar(
            select(func.count()).select_from(B2BSuppression).where(B2BSuppression.source == "bounce")
        )
        or 0
    )
    bounce_rate = (bounces / sent) if sent else None
    rows = db.execute(
        select(B2BEmailDraft, B2BProspect.store_name)
        .outerjoin(B2BProspect, B2BProspect.id == B2BEmailDraft.prospect_id)
        .where(B2BEmailDraft.status == "draft")
        .order_by(B2BEmailDraft.created_at.desc())
        .limit(5)
    ).all()
    items = [
        HomeCardItem(
            id=str(draft.id),
            title=draft.subject,
            subtitle=" · ".join(part for part in (store_name or "", draft.kind, draft.language) if part),
            at=draft.created_at,
            href=f"/b2b-wholesale?draft={draft.id}",
        )
        for draft, store_name in rows
    ]
    severity = "ok"
    if bounce_rate is not None and bounce_rate >= BOUNCE_RED_LINE:
        severity = "error"
    elif bounce_rate is not None and bounce_rate >= BOUNCE_WARN_RATE:
        severity = "warn"
    return HomeCardRead(
        card_id=CARD_ID,
        module_key=MODULE_KEY,
        count=drafts,
        items=items,
        freshness=datetime.now(UTC),
        actions=["skip"],
        extra={
            "sent": sent,
            "bounces": bounces,
            "bounce_rate": bounce_rate,
            "bounce_warn": bounce_rate is not None and bounce_rate >= BOUNCE_WARN_RATE,
            "bounce_red_line": BOUNCE_RED_LINE,
        },
        severity=severity,
    )
