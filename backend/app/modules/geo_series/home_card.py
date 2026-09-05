"""GEO 给主页的那张卡：待批评 / 已批未发 / 发布任务卡住。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..home.schemas import HomeCardItem, HomeCardRead
from .content.models import GeoContentItem, GeoPublishJob

CARD_ID = "geo-todo"
MODULE_KEY = "geo.content"


def load_home_card(
    db: Session,
    *,
    workspace_key: str,
    user: Any,
    permission_keys: frozenset[str],
    is_full_access: bool,
    **_: Any,
) -> HomeCardRead:
    scope = GeoContentItem.workspace_key == workspace_key
    pending_filter = (
        scope,
        GeoContentItem.review_status == "pending",
        GeoContentItem.generation_status == "generated",
    )
    pending = int(
        db.scalar(select(func.count()).select_from(GeoContentItem).where(*pending_filter)) or 0
    )
    unpublished = int(
        db.scalar(
            select(func.count())
            .select_from(GeoContentItem)
            .where(
                scope,
                GeoContentItem.review_status == "approved",
                GeoContentItem.generation_status == "generated",
                or_(GeoContentItem.wp_status.is_(None), GeoContentItem.wp_status != "publish"),
            )
        )
        or 0
    )
    stuck_jobs = int(
        db.scalar(
            select(func.count())
            .select_from(GeoPublishJob)
            .where(
                GeoPublishJob.workspace_key == workspace_key,
                GeoPublishJob.status.in_(("queued", "failed")),
            )
        )
        or 0
    )
    rows = db.scalars(
        select(GeoContentItem)
        .where(*pending_filter)
        .order_by(GeoContentItem.updated_at.desc())
        .limit(5)
    ).all()
    items = [
        HomeCardItem(
            id=str(row.id),
            title=row.title,
            subtitle=f"待批评 · {row.item_type}",
            at=row.updated_at,
            href=f"/geo?cluster={row.cluster_id}&item={row.id}",
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
