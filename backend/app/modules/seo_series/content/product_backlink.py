"""产品页 → 工艺文的回链块（``kp-factory`` / "How we make it"）。

GEO 那条已经跑通了「产品页 → 指南」(``kp-guides``)。这条补的是另一半:
**产品页 → 我们是怎么做出来的**。

## 为什么它值一个独立的块

指南回答「这东西好不好、怎么选」,工艺文回答「你们凭什么做得出来」。买家在产品页
上的犹豫经常是后者——一个没听过的牌子从中国发货，凭什么信。把工艺文摆在产品页上,
是这个站上**唯一竞品抄不走**的信任材料。

## 为什么按类目**祖先**找，不是子树

工艺文讲的是"我们怎么做这一类东西"(防水密封、锂电组装),天然挂在**上层类目**;
产品在叶子。所以从产品的类目往上走,沿途任何一层有工艺文都算数。
这和 ``seo_series/content/links.py::_wholesale_links`` 判断店型的方向一致。

反过来(按子树找)会得到"这个大类底下所有细分品的工艺文",对一个具体产品来说全是噪音。

## 死规矩

只认 ``wp_status == "publish"``。``published_url`` 非空只代表"我们曾经写过"——
n8n 首推刻意落草稿，URL 那时就已写库，只看它会把 404 挂到产品页上。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...content_core.html_blocks import apply_block, build_link_block
from . import constants as C
from .models import SeoContentItem

logger = logging.getLogger(__name__)

BLOCK_CLASS = "kp-factory"
BLOCK_HEADING = "How we make it"

# 产品页不是链接农场。三条足够证明"我们真做这个",再多就挤掉购买动线。
MAX_FACTORY_LINKS_ON_PRODUCT = 3

# 体裁排序:先讲怎么做的,再讲材料,再讲怎么测的,最后才是我们是谁。
# 买家的疑问顺序就是这个顺序。
_KIND_ORDER = {
    C.ITEM_CRAFT_STORY: 0,
    C.ITEM_MATERIAL_EXPLAINER: 1,
    C.ITEM_TESTING: 2,
    C.ITEM_BRAND_STORY: 3,
}


def published_factory_articles_for_product(
    db: Session, *, product_id: Any, product_key: str | None = None
) -> list[tuple[str, str]]:
    """[(标题, URL)] —— 这个产品该挂的工艺文。

    本函数**不出网**。调用方若要新鲜的发布状态,先自己跑一次
    ``live_state.refresh_item_live_state_safely``(和 GEO 的 related_guides 同规:
    B2B 那种逐产品循环的调用方否则会一个产品一发请求)。
    """
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct

    from .models import SeoTopic

    product = db.get(KProductKnowledgeProduct, product_id)
    if product is None and product_key:
        product = db.scalar(
            select(KProductKnowledgeProduct).where(
                KProductKnowledgeProduct.product_key == str(product_key)
            )
        )
    if product is None:
        return []

    google_id = str(getattr(product, "google_product_category", "") or "").strip()
    if not google_id:
        return []

    from ...geo_series.content.cluster_guard import category_ancestors

    family = {google_id, *category_ancestors(db, google_id)}

    rows = db.execute(
        select(
            SeoContentItem.title,
            SeoContentItem.published_url,
            SeoContentItem.item_kind,
            SeoTopic.google_category_id,
        )
        .join(SeoTopic, SeoTopic.id == SeoContentItem.topic_id)
        .where(
            SeoContentItem.destination == C.DESTINATION_FACTORY,
            SeoContentItem.review_status == "approved",
            # 死规矩:published_url 非空 ≠ 线上可见。
            SeoContentItem.wp_status == "publish",
            SeoContentItem.published_url.is_not(None),
        )
    ).all()

    scored: list[tuple[int, str, str]] = []
    for title, url, item_kind, category in rows:
        category = str(category or "").strip()
        # 有类目就必须落在祖先链上;**没类目 = 通用工艺,对任何产品都算数**
        # (手输的工艺选题常常不绑类目——"我们怎么做防水"是全厂的事)。
        if category and category not in family:
            continue
        title = str(title or "").strip()
        url = str(url or "").strip()
        if not title or not url:
            continue
        scored.append((_KIND_ORDER.get(str(item_kind), 9), title, url))

    # 稳定排序:体裁优先级 → 标题。链接图要算指纹,顺序必须确定。
    scored.sort(key=lambda row: (row[0], row[1]))
    return [(t, u) for _o, t, u in scored[:MAX_FACTORY_LINKS_ON_PRODUCT]]


def published_factory_articles_safely(
    db: Session, *, product_id: Any, product_key: str | None = None
) -> list[tuple[str, str]]:
    """同上,但 SEO 侧的任何问题都不许弄坏一次产品上架。"""
    try:
        return published_factory_articles_for_product(
            db, product_id=product_id, product_key=product_key
        )
    except Exception:  # noqa: BLE001 - 上架优先,工艺链接是增益
        logger.exception("factory backlink lookup failed for product %s", product_id)
        return []


def build_factory_block(links: list[tuple[str, str]]) -> str:
    return build_link_block(
        block_class=BLOCK_CLASS, heading=BLOCK_HEADING, links=links
    )


def apply_factory_block(description_html: str, block: str) -> str:
    return apply_block(description_html, block, block_class=BLOCK_CLASS)


def factory_block_for_product(
    db: Session, *, product_id: Any, product_key: str | None = None
) -> str:
    """这个产品此刻**应当**携带的块（``""`` = 不该带，等于摘掉）。"""
    return build_factory_block(
        published_factory_articles_safely(
            db, product_id=product_id, product_key=product_key
        )
    )


__all__ = [
    "BLOCK_CLASS",
    "BLOCK_HEADING",
    "MAX_FACTORY_LINKS_ON_PRODUCT",
    "apply_factory_block",
    "build_factory_block",
    "factory_block_for_product",
    "published_factory_articles_for_product",
    "published_factory_articles_safely",
]
