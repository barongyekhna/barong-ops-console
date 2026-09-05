"""SM 给主页的那张卡：待审帖子 / 7 天内到期的真照片缺口 / 排不出来的格子。

只 select，不 commit（home/registry 的规矩：3 秒一轮 × 打开的标签页数）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..home.schemas import HomeCardItem, HomeCardRead
from .constants import LANE_PHOTO, MODULE_KEY, PILLAR_LABELS
from .models import SmCalendarSlot, SmImageRequest, SmPost

CARD_ID = "sm-todo"


def load_home_card(
    db: Session,
    *,
    workspace_key: str,
    user: Any,
    permission_keys: frozenset[str],
    is_full_access: bool,
    **_: Any,
) -> HomeCardRead:
    del user, permission_keys, is_full_access
    today = date.today()
    horizon = today + timedelta(days=7)

    pending = int(
        db.scalar(
            select(func.count())
            .select_from(SmPost)
            .where(
                SmPost.workspace_key == workspace_key,
                SmPost.review_status == "pending",
                SmPost.generation_status == "generated",
            )
        )
        or 0
    )
    photo_gaps = int(
        db.scalar(
            select(func.count())
            .select_from(SmImageRequest)
            .where(
                SmImageRequest.workspace_key == workspace_key,
                SmImageRequest.status == "open",
                SmImageRequest.lane == LANE_PHOTO,
                SmImageRequest.due_day <= horizon,
            )
        )
        or 0
    )
    blocked = int(
        db.scalar(
            select(func.count())
            .select_from(SmCalendarSlot)
            .where(
                SmCalendarSlot.workspace_key == workspace_key,
                SmCalendarSlot.status == "blocked",
                SmCalendarSlot.day >= today,
                SmCalendarSlot.day <= horizon,
            )
        )
        or 0
    )

    rows = db.scalars(
        select(SmPost)
        .where(
            SmPost.workspace_key == workspace_key,
            SmPost.review_status == "pending",
            SmPost.generation_status == "generated",
        )
        .order_by(SmPost.updated_at.desc())
        .limit(5)
    ).all()
    items = [
        HomeCardItem(
            id=str(row.id),
            title=row.title or row.first_line or "（无标题）",
            subtitle=f"待审 · {row.platform} · {PILLAR_LABELS.get(row.pillar, row.pillar)}",
            at=row.updated_at,
            href=f"/sm?tab=posts&post={row.id}",
        )
        for row in rows
    ]
    if len(items) < 5 and photo_gaps:
        gap_rows = db.scalars(
            select(SmImageRequest)
            .where(
                SmImageRequest.workspace_key == workspace_key,
                SmImageRequest.status == "open",
                SmImageRequest.lane == LANE_PHOTO,
                SmImageRequest.due_day <= horizon,
            )
            .order_by(SmImageRequest.due_day.asc())
            .limit(5 - len(items))
        ).all()
        items += [
            HomeCardItem(
                id=str(row.id),
                title=(row.brief_text or "缺真照片")[:80],
                subtitle=f"真照片缺口 · 截止 {row.due_day.isoformat()}",
                at=row.created_at,
                href="/sm?tab=gaps",
            )
            for row in gap_rows
        ]

    severity = "warn" if (photo_gaps or blocked) else "ok"
    return HomeCardRead(
        card_id=CARD_ID,
        module_key=MODULE_KEY,
        count=pending + photo_gaps + blocked,
        items=items,
        freshness=datetime.now(UTC),
        actions=[],
        extra={"pending_review": pending, "photo_gaps_due": photo_gaps, "blocked_slots": blocked},
        severity=severity,
    )


__all__ = ["CARD_ID", "load_home_card"]
