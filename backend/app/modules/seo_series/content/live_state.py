"""把 SEO 文章的**线上真实状态**同步回库。

与 GEO 同源的教训:``published_url`` 非空只代表"我们曾经写过它",不代表访客
看得到——首推刻意落草稿,URL 那一刻就已写库。运营后来在 WP 点了发布,控制台
永远不知道。

所以每个要读"已发布文章"的地方(枢纽页、内链解析、批发页交叉链)先跑一次这个
批量刷新,再读列。一次批量 API,不是每篇一发。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import SeoContentItem

logger = logging.getLogger(__name__)


def refresh_item_live_state(db: Session) -> int:
    from ...content_core.wp_sync import fetch_post_states
    from ....services import wp_bridge

    post_ids = [
        int(pid)
        for (pid,) in db.execute(
            select(SeoContentItem.wp_post_id).where(
                SeoContentItem.wp_post_id.is_not(None)
            )
        ).all()
        if pid
    ]
    if not post_ids:
        return 0
    db.commit()  # 出网前放掉事务

    credentials = wp_bridge._resolve_credentials(db=db)  # noqa: SLF001
    if credentials is None:
        return 0
    states = fetch_post_states(credentials, post_ids)
    if not states:
        # WP 不可达时**什么都不改**:把状态清空会让线上文章从枢纽页凭空消失。
        return 0

    touched = 0
    for item in db.execute(
        select(SeoContentItem).where(SeoContentItem.wp_post_id.in_(list(states)))
    ).scalars():
        state = states.get(int(item.wp_post_id or 0))
        if not state:
            continue
        item.wp_status = state.get("status") or item.wp_status
        link = str(state.get("link") or "").strip()
        if link:
            item.published_url = link[:2048]
        touched += 1
    db.commit()
    return touched


def refresh_item_live_state_safely(db: Session) -> int:
    try:
        return refresh_item_live_state(db)
    except Exception:  # noqa: BLE001 - 刷新失败不该毁掉调用方
        logger.exception("SEO live-state refresh failed")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0


__all__ = ["refresh_item_live_state", "refresh_item_live_state_safely"]
