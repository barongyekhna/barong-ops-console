"""SEO 给主页的那张卡：待批评 / 已批未发 / 发布任务卡住。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..home.schemas import HomeCardItem, HomeCardRead
from .content.models import SeoContentItem, SeoPublishJob

CARD_ID = "seo-todo"
MODULE_KEY = "seo.content"


def load_home_card(
    db: Session,
    *,
    workspace_key: str,
    user: Any,
    permission_keys: frozenset[str],
    is_full_access: bool,
    **_: Any,
) -> HomeCardRead:
    scope = SeoContentItem.workspace_key == workspace_key
    pending_filter = (
        scope,
        SeoContentItem.review_status == "pending",
        SeoContentItem.generation_status == "generated",
    )
    pending = int(
        db.scalar(select(func.count()).select_from(SeoContentItem).where(*pending_filter)) or 0
    )
    unpublished = int(
        db.scalar(
            select(func.count())
            .select_from(SeoContentItem)
            .where(
                scope,
                SeoContentItem.review_status == "approved",
                SeoContentItem.generation_status == "generated",
                or_(SeoContentItem.wp_status.is_(None), SeoContentItem.wp_status != "publish"),
            )
        )
        or 0
    )
    stuck_jobs = int(
        db.scalar(
            select(func.count())
            .select_from(SeoPublishJob)
            .where(
                SeoPublishJob.workspace_key == workspace_key,
                SeoPublishJob.status.in_(("queued", "failed")),
            )
        )
        or 0
    )
    rows = db.scalars(
        select(SeoContentItem)
        .where(*pending_filter)
        .order_by(SeoContentItem.updated_at.desc())
        .limit(5)
    ).all()
    items = [
        HomeCardItem(
            id=str(row.id),
            title=row.title,
            subtitle="待批评",
            at=row.updated_at,
            href=f"/seo?item={row.id}",
        )
        for row in rows
    ]
    return HomeCardRead(
        card_id=CARD_ID,
        module_key=MODULE_KEY,
        count=pending + unpublished + stuck_jobs,
        items=items,
        freshness=datetime.now(UTC),
        actions=["approve"],
        extra={
            "pending_review": pending,
            "unpublished": unpublished,
            "publish_jobs": stuck_jobs,
        },
    )
