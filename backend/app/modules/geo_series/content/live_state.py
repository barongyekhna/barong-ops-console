"""把 WordPress 上的真实状态同步回 GEO 的内容行。

纯 WP 批量查询在 `content_core.wp_sync.fetch_post_states`;这里只剩**绑着
GeoContentItem 这张表的适配器**——按下沉判据,与内容种类无关的才共享。

**为什么需要它**:`published_url` 非空只说明"写进过 WP",不等于访客看得到。
n8n 首次建文刻意落 draft 等人工发布,URL 在那一刻就已写库;用户之后在 WP 点
发布,控制台无从得知。于是产品页反链、批发页挂的指南都可能指向草稿 → 404。

一次批量刷新,所有消费方只读 `wp_status`,不必各自查网(逐产品调用会变成 N 次
请求——B2B 侧正是逐产品循环)。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def refresh_item_live_state(db: Any, *, item_ids: list[Any] | None = None) -> int:
    """同步 wp_status / published_url。返回更新了几行。

    Fail-open:WP 挂了就保留旧状态,**绝不清空**——清空会让所有产品页上的指南
    链接同时消失。
    """
    from sqlalchemy import select, update

    from ....services import wp_bridge
    from ...content_core.wp_sync import fetch_post_states
    from .models import GeoContentItem

    query = select(GeoContentItem.id, GeoContentItem.wp_post_id).where(
        GeoContentItem.wp_post_id.is_not(None)
    )
    if item_ids:
        query = query.where(GeoContentItem.id.in_(list(item_ids)))
    rows = db.execute(query).all()
    if not rows:
        return 0
    by_post = {int(post_id): item_id for item_id, post_id in rows if post_id}

    # 死规矩:出网前先释放事务。
    db.commit()

    credentials = wp_bridge._resolve_credentials(db=db)  # noqa: SLF001
    if credentials is None:
        logger.warning("WP 状态刷新跳过:没有凭据")
        return 0

    states = fetch_post_states(credentials, list(by_post))
    if not states:
        return 0

    updated = 0
    for post_id, state in states.items():
        item_id = by_post.get(post_id)
        if item_id is None:
            continue
        values: dict[str, Any] = {"wp_status": state["status"] or None}
        # WP 返回的 link 是权威的,顺带修掉草稿期遗留的 `?p=<id>` 形式。
        if state["link"]:
            values["published_url"] = state["link"]
        db.execute(
            update(GeoContentItem).where(GeoContentItem.id == item_id).values(**values)
        )
        updated += 1
    db.commit()
    return updated


def refresh_item_live_state_safely(
    db: Any, *, item_ids: list[Any] | None = None
) -> int:
    """同上,但刷新失败绝不打断调用方的正事。"""
    try:
        return refresh_item_live_state(db, item_ids=item_ids)
    except Exception:  # noqa: BLE001 - 数据陈旧可以忍,崩溃不行
        logger.exception("WP 状态刷新崩溃")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("WP 状态刷新回滚失败")
        return 0


__all__ = ["refresh_item_live_state", "refresh_item_live_state_safely"]
