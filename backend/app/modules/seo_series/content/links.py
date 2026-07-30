"""内链网:把 ``link_intents`` 解析成真实 URL。

**为什么是"意图"而不是模型自己写 URL**:目标页面可能还不存在(指南还没发、
产品还没上架),而且让模型写 URL 等于让它编 URL。所以模型只说"这里该链到一个
讲这个类目的指南",由服务端在发布时决定链到哪儿、或者干脆不链。

**为什么不做锚词字符串替换**:那会诱导为锚词批量造薄页(doorway page)——
先定锚词、再补一堆只为承接锚词的空页面,这是 Google 明确打击的模式。
意图驱动只会链到**本来就该存在**的页面。

四类枢纽(全站内链的骨架):

    /factory/ 工艺区(信任枢纽·一份三用)
      ╱          │           ╲
  产品页  ◄────► /guides/ ◄───► /wholesale/
    ▲                              │
    └──────── 店型子页 ◄───────────┘

产品页 ⇄ /guides/ 由 GEO 建;/guides/ ⇄ /wholesale/ 由 B2B 建;
**本模块补的是 /factory/ → 产品页 / /guides/ / /wholesale/ 这三条**。

连接键一律是**谷歌类目**——不是关键词模糊匹配。类目是产品、指南、批发页三边
共有的唯一硬标识,所以内链**不可能张冠李戴**(B2B 那边同样的结论)。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 一篇文章最多挂几条内链。多了就成链接农场,读者一条都不会点。
MAX_LINKS_PER_ARTICLE = 6


def _tokens(text: Any) -> set[str]:
    import re

    return {
        w
        for w in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(w) >= 4
    }


def _product_links(db: Session, *, category_id: str | None, hint: str) -> list[dict]:
    """产品页。有类目就按类目,没有就按词面——但**只在真的有上架页时**才给。"""
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct
    from ...p_series.upload.models import PUploadJob

    query = select(KProductKnowledgeProduct)
    if category_id:
        query = query.where(
            KProductKnowledgeProduct.google_product_category == category_id
        )
    want = _tokens(hint)
    out: list[dict] = []
    for product in db.execute(query.limit(20)).scalars():
        title = str(getattr(product, "product_name_en", "") or "").strip()
        if not title:
            continue
        if not category_id and want and not (want & _tokens(title)):
            continue
        woo_id = db.scalar(
            select(PUploadJob.external_product_id)
            .where(
                PUploadJob.product_id == product.id,
                PUploadJob.status == "success",
                PUploadJob.external_product_id.is_not(None),
            )
            .order_by(PUploadJob.finished_at.desc())
        )
        text = str(woo_id or "").strip()
        if not text.isdigit():
            continue  # 还没上架的产品不挂链——挂了就是 404
        out.append(
            {
                "kind": "product",
                "title": title,
                "url": f"https://barongyekhna.com/?p={text}",
                "woo_product_id": int(text),
            }
        )
    return out


def _guide_links(db: Session, *, category_id: str | None, hint: str) -> list[dict]:
    """已发布的 GEO 指南。**只认 wp_status == 'publish'**——
    published_url 非空 ≠ 线上可见(草稿期就已写库),这条踩过。"""
    from ...geo_series.content.models import GeoContentCluster, GeoContentItem

    cluster_ids: list[Any] = []
    want = _tokens(hint)
    for cluster in db.execute(select(GeoContentCluster)).scalars():
        if category_id and str(cluster.google_category_id or "") == str(category_id):
            cluster_ids.append(cluster.id)
        elif not category_id and want and (want & _tokens(cluster.category_path)):
            cluster_ids.append(cluster.id)
    if not cluster_ids:
        return []
    rows = db.execute(
        select(GeoContentItem.title, GeoContentItem.published_url).where(
            GeoContentItem.cluster_id.in_(cluster_ids),
            GeoContentItem.review_status == "approved",
            GeoContentItem.wp_status == "publish",
            GeoContentItem.published_url.is_not(None),
        )
    ).all()
    return [
        {"kind": "guide", "title": str(t).strip(), "url": str(u).strip()}
        for t, u in rows
        if str(t or "").strip() and str(u or "").strip()
    ]


def _wholesale_links(db: Session, *, category_id: str | None) -> list[dict]:
    """批发主页 + 对应店型子页。B2B 侧建的页面,这里只读它的 slug 约定。

    店型子页按**谷歌类目前缀**匹配:店型自己就是按类目前缀定义的,所以一篇讲
    某类目的文章能准确落到吃这个类目的店型上,而不是笼统地指向批发主页。
    """
    try:
        from ...b2b.store_types.models import B2BStoreType, B2BStoreTypeCategory
        from ...b2b.website.pages import WHOLESALE_SLUG, WHOLESALE_TITLE, store_type_slug
    except Exception:  # noqa: BLE001 - B2B 未就绪时静默跳过
        return []

    base = "https://barongyekhna.com"
    out = [
        {
            "kind": "wholesale",
            "title": WHOLESALE_TITLE,
            "url": f"{base}/{WHOLESALE_SLUG}/",
        }
    ]
    if not category_id:
        return out
    try:
        from ...k_series.product_knowledge.category_resolver import (
            google_category_path,
        )

        path = google_category_path(db, str(category_id))
        path_text = " > ".join(
            str(node.get("name") if isinstance(node, dict) else node) for node in path
        ).lower()
    except Exception:  # noqa: BLE001
        return out

    prefixes: dict[Any, list[str]] = {}
    for row in db.execute(select(B2BStoreTypeCategory)).scalars():
        prefixes.setdefault(row.store_type_id, []).append(str(row.category_key).lower())
    for store in db.execute(select(B2BStoreType)).scalars():
        if any(p and p in path_text for p in prefixes.get(store.id, [])):
            out.append(
                {
                    "kind": "wholesale",
                    "title": f"{store.label} — wholesale",
                    "url": f"{base}/{WHOLESALE_SLUG}/{store_type_slug(store.key)}/",
                }
            )
    return out


def resolve_link_intents(
    db: Session, *, intents: list[dict], category_id: str | None
) -> tuple[list[dict], list[str]]:
    """(可用内链, 没解析出来的意图说明)。

    解析不出来**不是错误**——目标页面还不存在是常态(新类目、指南还没写)。
    如实返回,让运营知道这篇文章暂时是内链孤岛,而不是假装挂上了。
    """
    resolved: list[dict] = []
    unresolved: list[str] = []
    seen: set[str] = set()

    for intent in intents or []:
        if not isinstance(intent, dict):
            continue
        kind = str(intent.get("kind") or "").strip()
        hint = str(intent.get("hint") or "").strip()
        try:
            if kind == "product":
                found = _product_links(db, category_id=category_id, hint=hint)
            elif kind == "guide":
                found = _guide_links(db, category_id=category_id, hint=hint)
            elif kind == "wholesale":
                found = _wholesale_links(db, category_id=category_id)
            else:
                unresolved.append(f"未知内链类型 {kind}")
                continue
        except Exception:  # noqa: BLE001 - 内链是增益,不该毁掉发布
            logger.exception("link intent resolution failed: %s", intent)
            unresolved.append(f"{kind}（{hint[:30]}）解析出错")
            continue

        if not found:
            unresolved.append(
                {
                    "product": f"没有已上架的产品页可链（{hint[:30]}）",
                    "guide": f"这个类目还没有已发布的指南（{hint[:30]}）",
                    "wholesale": "还没有已发布的批发页",
                }.get(kind, f"{kind} 无匹配")
            )
            continue
        for row in found:
            if row["url"] in seen:
                continue
            seen.add(row["url"])
            resolved.append(row)
            if len(resolved) >= MAX_LINKS_PER_ARTICLE:
                return resolved, unresolved
    return resolved, unresolved


def links_block_html(links: list[dict]) -> str:
    """文章末尾的内链区块。分组呈现——读者要的是"接下来看什么",不是一堆链接。"""
    if not links:
        return ""
    groups = {
        "product": ("Shop the products", []),
        "guide": ("Related buying guides", []),
        "wholesale": ("Buying for a store?", []),
    }
    for link in links:
        bucket = groups.get(link.get("kind"))
        if bucket:
            bucket[1].append(link)

    import html as _html

    parts: list[str] = []
    for _kind, (heading, rows) in groups.items():
        if not rows:
            continue
        items = "".join(
            f'<li><a href="{_html.escape(r["url"], quote=True)}">'
            f"{_html.escape(r['title'])}</a></li>"
            for r in rows
        )
        parts.append(f"<h3>{_html.escape(heading)}</h3><ul>{items}</ul>")
    return (
        '<div class="barong-seo-links">' + "".join(parts) + "</div>" if parts else ""
    )


__all__ = [
    "MAX_LINKS_PER_ARTICLE",
    "links_block_html",
    "resolve_link_intents",
]
