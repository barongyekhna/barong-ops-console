"""给批发页收集「相关指南」。

用户的核心顾虑(2026-07-29):"怎么确保你的批发页面和指南页面正确连接?而不是
花洒连接到了捏捏的指南里面去?"

**串不了,因为连接键是谷歌类目,而且两边都从 K 的 `google_product_category`
派生**——不是我在两处各写一份然后祈祷它们一样:

    5 个捏捏球 → Toys & Games > Toys > Executive Toys → 簇 3074   → stress ball
    露营花洒   → Sporting Goods > … > Portable Showers → 簇 502994 → camping shower

`3074 ≠ 502994`,不存在能让它们连起来的路径。再加上「一个类目一个簇」那条
死规矩,类目→簇是一对一,连"该选哪个簇"的模糊空间都没有。

具体做法上有两个必须守住的点:

1. **按「这一页上实际有的产品」连,不按「店型配置的类目前缀」连。**
   五金店的前缀是整个 `Hardware` 根(底下 522 个类目)。哪天 GEO 给水管写了
   指南而你不卖水管,按前缀连就会把水管指南推到五金页上——推销你没有的货。
2. **`published_url` 非空 ≠ 线上可见。** n8n 首次建文落 `draft` 等人工发布,
   而草稿没有固定链接(`published_url` 可能是 `?p=4218`)。直接拿它当链接
   会链到草稿,访客看到 404。所以生成页面时要向 WP **批量核一次状态**。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 每个类目段落挂几篇。产品才是主角,指南多了会把货压下去。
MAX_GUIDES_PER_CATEGORY = 3


def guides_for_products(
    db: Session,
    k_product_ids: list[Any],
) -> list[dict[str, str]]:
    """这批产品(= 一个类目段落里的货)对应的已批准指南。

    复用 `geo_series/content/related_guides.py` 的连接逻辑——那边已经做了
    「簇含此产品 + published_url 非空 + review_status=approved + hub 优先
    + 去重」,不重新推导一遍。
    """
    from ...geo_series.content.related_guides import (
        published_guides_for_product_safely,
    )

    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for product_id in k_product_ids:
        if not product_id:
            continue
        for title, url in published_guides_for_product_safely(
            db, product_id=product_id
        ):
            if not title or not url or url in seen:
                continue
            seen.add(url)
            out.append({"title": title, "url": url})
    return out


def filter_live(
    credentials: Any,
    guides: list[dict[str, str]],
    *,
    post_ids: list[int] | None = None,
) -> list[dict[str, str]]:
    """只留 WordPress 上**真的已发布**的那些,并用 WP 返回的固定链接覆盖。

    一次 API 调用核全部——不是每篇打一次。

    为什么必须核:`published_url` 非空只代表"写进过 WP"。首次建文是草稿,
    等人工在 WP 里点发布;草稿期写下的 URL 是 `?p=<id>` 形式。链到草稿的
    结果是访客 404,而这种错**不会报错**,只能靠肉眼在线上发现。
    """
    if not guides:
        return []
    if not post_ids:
        # 没给 id 就没法核；宁可少链也不链到草稿。
        logger.info("B2B guide links: no post ids to verify, skipping guides")
        return []

    from ....services import wp_bridge

    ids = ",".join(str(int(i)) for i in post_ids if i)
    result = wp_bridge._request_json(  # noqa: SLF001 - 站内共享口径
        wp_bridge._api_url(
            credentials,
            f"posts?include={ids}&status=any&per_page=100"
            "&_fields=id,status,link",
        ),
        credentials=credentials,
        authenticated=True,
    )
    data = result.get("data")
    if not isinstance(data, list):
        logger.warning(
            "B2B guide links: could not verify post status (%s); linking none",
            result.get("error"),
        )
        return []

    live_links = {
        str(row.get("link") or "").strip()
        for row in data
        if isinstance(row, dict) and row.get("status") == "publish"
    }
    live_links.discard("")
    # WP 返回的 link 是当前固定链接;存的可能还是 ?p= 形式,所以按 post id 对。
    by_id = {
        int(row["id"]): str(row.get("link") or "").strip()
        for row in data
        if isinstance(row, dict)
        and row.get("status") == "publish"
        and row.get("id")
    }

    out: list[dict[str, str]] = []
    for guide in guides:
        url = guide.get("url") or ""
        resolved = url if url in live_links else _resolve_by_id(url, by_id)
        if not resolved:
            continue
        out.append({"title": guide["title"], "url": resolved})
        if len(out) >= MAX_GUIDES_PER_CATEGORY:
            break
    return out


def _resolve_by_id(url: str, by_id: dict[int, str]) -> str:
    """`?p=4218` 形式的旧 URL → 用 WP 当前的固定链接换掉。"""
    import re

    match = re.search(r"[?&]p=(\d+)", url)
    if match:
        return by_id.get(int(match.group(1)), "")
    # 固定链接但不在 live 名单里 = 那篇还是草稿或已删
    return ""


def post_ids_for_products(db: Session, k_product_ids: list[Any]) -> list[int]:
    """这批产品的指南对应的 WP post id,用来批量核状态。"""
    from sqlalchemy import select

    from ...geo_series.content.models import GeoContentCluster, GeoContentItem

    identifiers = {str(x).strip() for x in k_product_ids if x}
    identifiers.discard("")
    if not identifiers:
        return []

    cluster_ids = [
        cluster_id
        for cluster_id, product_ids in db.execute(
            select(GeoContentCluster.id, GeoContentCluster.product_ids_json)
        ).all()
        if any(
            str(x).strip() in identifiers
            for x in (product_ids if isinstance(product_ids, list) else [])
        )
    ]
    if not cluster_ids:
        return []
    rows = db.execute(
        select(GeoContentItem.wp_post_id).where(
            GeoContentItem.cluster_id.in_(cluster_ids),
            GeoContentItem.wp_post_id.is_not(None),
            GeoContentItem.review_status == "approved",
        )
    ).all()
    return [int(r[0]) for r in rows if r[0]]


def guide_link_map(db: Session, groups: list[dict[str, Any]]) -> dict[str, dict]:
    """反向那条:WP 类目 term id → 该去哪个批发页。

    **只映射有货的类目**——映射了没货的类目,买家点过去是空页。

    指南文章只挂**叶子类目**(实测 `categories: [1501]`,不带祖先),所以这里
    的键就是叶子 term id,插件那边拿文章实际的 term 列表来查,不做层级推断。
    """
    from sqlalchemy import select

    from ...geo_series.content.models import GeoContentCluster, GeoWpCategoryMap

    # 谷歌类目 → WP term id
    term_by_google = {
        str(row[0]): int(row[1])
        for row in db.execute(
            select(GeoWpCategoryMap.google_id, GeoWpCategoryMap.wp_term_id)
        ).all()
        if row[1]
    }
    if not term_by_google:
        return {}

    # 类目路径 → 谷歌类目 id（簇两边都存了，用路径对得上批发产品）
    google_by_path = {
        str(row[1] or "").strip(): str(row[0] or "").strip()
        for row in db.execute(
            select(
                GeoContentCluster.google_category_id,
                GeoContentCluster.category_path,
            )
        ).all()
        if row[0] and row[1]
    }

    out: dict[str, dict] = {}
    for group in groups:
        for category in group.get("categories") or []:
            path = str(category.get("path") or "").strip()
            google_id = google_by_path.get(path)
            if not google_id:
                continue
            term_id = term_by_google.get(google_id)
            if not term_id:
                continue
            # 同一个类目可能落进多个店型（花洒既进户外店也进房车店）。
            # 取第一个（groups 已按 sort_order 排序），保证稳定不抖。
            out.setdefault(
                str(term_id),
                {"label": group["label"], "url": group["url"]},
            )
    return out
