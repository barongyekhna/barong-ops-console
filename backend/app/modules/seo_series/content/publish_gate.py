"""SEO 发布门禁。

从 ``seo_series/router.py`` 里那段内联循环抽出来的 —— 内容台也要用同一套判据,
抄第二份必然分叉(GEO 那边 ``geo_series/content/publish_gate.py`` 就是先例)。

**刻意不和 GEO 的 publish_blockers 合并成一个函数。** 两边查的东西根本不同:
GEO 还要查谷歌类目、``seo_json.url_slug``、引用的产品有没有公开页;SEO 一样都
不查。硬合并会把 GEO 的三道闸悄悄加到 SEO 上,或者反过来把 GEO 的闸拆掉。
共享的是**判据的写法**,不是判据本身。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ...content_core.guards import audit_is_clean


def publish_blockers(db: Session, *, item_ids: list[UUID]) -> list[str]:
    """为什么这几篇发不出去。空列表 = 可以发。

    一篇最多产出一条(``elif`` 链)——列全了也没用,改完第一条自然会看到第二条。
    """
    from .models import SeoContentItem

    blockers: list[str] = []
    for item_id in item_ids:
        item = db.get(SeoContentItem, item_id)
        if item is None:
            blockers.append(f"{item_id}：不存在")
        elif item.review_status != "approved":
            blockers.append(f"《{str(item.title)[:30]}》：还没批准")
        elif not audit_is_clean(item.brand_audit_json):
            # 缺审查记录也算没过(fail-closed)。这里原来是 `.get("clean", True)`,
            # 一篇从没审过的文章可以直接发出去。
            blockers.append(f"《{str(item.title)[:30]}》：没过品牌/接地审查")
    return blockers


def publishable_items(db: Session, *, item_ids: list[UUID]) -> list[Any]:
    """这批里真能发的那些。"""
    from .models import SeoContentItem

    out = []
    for item_id in item_ids:
        item = db.get(SeoContentItem, item_id)
        if (
            item is not None
            and item.review_status == "approved"
            and audit_is_clean(item.brand_audit_json)
        ):
            out.append(item)
    return out


__all__ = ["publish_blockers", "publishable_items"]
