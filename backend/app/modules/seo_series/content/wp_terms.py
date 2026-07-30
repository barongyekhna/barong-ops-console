"""SEO 的 WordPress 分类。

**为什么不复用 GEO 的谷歌类目树**:GEO 把它创建的每个谷歌类目 id 都推进
``barong_geo_category_ids``,让指南不出现在 ``/posts`` 博客归档里。如果 SEO 的
C 端文章也落在同一批谷歌类目下,它们会**跟着被排除**——博客里将永远空空如也。

所以两套分类各管一段:

- ``/factory/`` 的工艺/品牌/B 端文章 → **factory 分类**(自己的一小棵扁平树),
  并且**也推进排除名单**——它们同样不该出现在博客归档里。
- ``/posts/`` 的 C 端文章 → **博客分类**,**不进**排除名单。它们就是博客本身。

分类 id 缓存在 ``seo_wp_category_map``,避免每次发布都去 WP 查一遍。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import constants as C

logger = logging.getLogger(__name__)


class SeoCategoryError(RuntimeError):
    """文章无法归入分类——**宁可整单不发,也不发成"无类目"**(同 GEO 的死命令)。"""


# factory 区的分类。刻意扁平且少:三五个能让读者一眼看懂的抽屉,
# 胜过一棵没人点的树。
FACTORY_CATEGORIES = {
    C.ITEM_CRAFT_STORY: "Craft & Process",
    C.ITEM_MATERIAL_EXPLAINER: "Materials",
    C.ITEM_TESTING: "Testing",
    C.ITEM_BRAND_STORY: "Behind the Brand",
    C.ITEM_WHOLESALE_GUIDE: "Wholesale",
}

BLOG_CATEGORIES = {
    C.ITEM_BUYING_GUIDE: "Buying Guides",
}


def category_name_for(item_kind: str, destination: str) -> str:
    if destination == C.DESTINATION_FACTORY:
        name = FACTORY_CATEGORIES.get(item_kind)
    else:
        name = BLOG_CATEGORIES.get(item_kind)
    if not name:
        raise SeoCategoryError(f"体裁 {item_kind} 没有对应的分类。")
    return name


def _find_or_create_term(credentials: Any, name: str) -> int:
    """按名字找 post 分类,没有就建。**find 在前**——重复建会产生 name-2。"""
    from urllib.parse import urlencode

    from ....services import wp_bridge

    query = urlencode({"search": name, "per_page": 20, "_fields": "id,name"})
    found = wp_bridge._request_json(  # noqa: SLF001
        wp_bridge._api_url(credentials, f"categories?{query}"),
        credentials=credentials,
        authenticated=True,
    )
    if found.get("reachable"):
        for row in found.get("data") or []:
            if isinstance(row, dict) and str(row.get("name", "")).strip() == name:
                return int(row["id"])
    elif found.get("status") not in (404, None):
        # 查不通就**不要建**——WP 一超时就新建,等于每次超时多一个重复分类。
        raise SeoCategoryError(f"分类查询失败（{found.get('error')}），本次不新建。")

    created = wp_bridge._request_json(  # noqa: SLF001
        wp_bridge._api_url(credentials, "categories"),
        credentials=credentials,
        authenticated=True,
        method="POST",
        payload={"name": name},
    )
    if not created.get("reachable"):
        raise SeoCategoryError(f"分类创建失败（{name}）：{created.get('error')}")
    data = created.get("data") or {}
    term_id = data.get("id")
    if not isinstance(term_id, int) or term_id <= 0:
        raise SeoCategoryError(f"WordPress 没有返回有效的分类 id（{name}）。")
    return term_id


def ensure_category(db: Session, *, item_kind: str, destination: str) -> int:
    """分类 id。缓存命中就不出网。"""
    from .models_terms import SeoWpCategoryMap

    name = category_name_for(item_kind, destination)
    cached = db.scalar(
        select(SeoWpCategoryMap.wp_term_id).where(SeoWpCategoryMap.name == name)
    )
    if cached:
        return int(cached)

    from ....services import wp_bridge

    db.commit()  # 出网前放掉事务
    credentials = wp_bridge._resolve_credentials(db=db)  # noqa: SLF001
    if credentials is None:
        raise SeoCategoryError("WordPress 凭据不可用。")
    term_id = _find_or_create_term(credentials, name)

    db.add(
        SeoWpCategoryMap(name=name, destination=destination, wp_term_id=term_id)
    )
    db.commit()
    return term_id


def sync_factory_category_exclusions(db: Session) -> str | None:
    """把 factory 分类 id 一并推进 ``barong_geo_category_ids``。

    **插件零改动**:排除名单是数据不是代码,由控制台遥控。
    ``/posts`` 归档因此只剩真正的博文,而 factory 文章仍在自己的分类归档
    和站内搜索里——这正是 GEO 指南当初的做法。
    """
    from ...geo_series.content.wp_categories import (
        GEO_CATEGORY_IDS_OPTION,
    )
    from ...geo_series.content.models import GeoWpCategoryMap
    from .models_terms import SeoWpCategoryMap

    geo_ids = {
        int(r[0]) for r in db.execute(select(GeoWpCategoryMap.wp_term_id)).all() if r[0]
    }
    factory_ids = {
        int(r[0])
        for r in db.execute(
            select(SeoWpCategoryMap.wp_term_id).where(
                SeoWpCategoryMap.destination == C.DESTINATION_FACTORY
            )
        ).all()
        if r[0]
    }
    value = ",".join(str(i) for i in sorted(geo_ids | factory_ids))

    from ....services import wp_bridge

    db.commit()
    credentials = wp_bridge._resolve_credentials(db=db)  # noqa: SLF001
    if credentials is None:
        logger.warning("WP credentials unavailable; skipping exclusion sync")
        return None
    result = wp_bridge._request_json(  # noqa: SLF001
        wp_bridge._api_url(credentials, "settings"),
        credentials=credentials,
        authenticated=True,
        method="POST",
        payload={GEO_CATEGORY_IDS_OPTION: value},
    )
    if not result.get("reachable"):
        logger.warning("exclusion sync failed: %s", result.get("error"))
        return None
    return value


__all__ = [
    "BLOG_CATEGORIES",
    "FACTORY_CATEGORIES",
    "SeoCategoryError",
    "category_name_for",
    "ensure_category",
    "sync_factory_category_exclusions",
]
