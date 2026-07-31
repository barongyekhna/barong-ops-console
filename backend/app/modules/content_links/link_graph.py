"""链接图——「每篇文章该链到哪些产品、指南、工艺文」的完整答案。

## 这是整套自动化的核心

发布那一刻把链接算死写进正文,之后新产品上架、新指南发布,老文章不会知道。
改成:控制台算一张**全站链接图**推给 WordPress,插件在渲染每篇文章时现场查表。

于是"自动"是天然成立的,不是靠定时去改文章:
- 新产品上架 → 重算图 → 该类目所有文章的卡片里立刻多一张
- 新指南发布 → 重算图 → 相关文章的推荐里立刻多一条
- **一篇文章的 HTML 一个字节都没被碰过**

## 🔴 必须按 post id 建键,不能按 WP 分类 term id

B2B 那套 ``barong_b2b_guide_links`` 用 term id 做键,因为 GEO 指南的 WP 分类
**就是**谷歌类目。但 SEO 文章**故意不落谷歌类目**——落了会被
``barong-geo-archive`` 连坐排除出博客归档(见 ``seo_series/content/wp_terms.py``),
它们拿到的是**体裁分类**(Craft & Process / Materials / Testing …一共 6 个)。

照抄 term id 会让一个体裁下的所有文章拿到同一批产品卡片。按 post id 建键,
顺带比按类目更精确。

## 归一化,不是每篇一份完整卡片

产品卡片在 ``p`` 里只存一份,``posts`` 里放 id 引用。300 篇文章 ≈ 30–50 KB,
而不是几百 KB——这个 JSON 要塞进一个 WP option,大小直接决定站点快慢。

## 决定性是硬要求

指纹短路("内容没变就一个字节都不发")只在图**完全确定**时才有意义。
任何一处不稳定排序都会让指纹每次都变 → 每 15 分钟往 WP 写一次,护栏形同虚设。
所有产出列表显式排序,测试连跑两次断言字节相同。

## 红线

**图里任何地方都不出现价格。** GMC 因为"页面价 ≠ feed 价"封过两次,只剩一次
申诉机会;文章页上出现产品价格等于又开一个价格面。契约层就不放这个字段。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

LINK_MAP_VERSION = 1

# 一篇文章挂多少条。多了就是链接农场,读者一条都不会点。
MAX_PRODUCTS_PER_POST = 3
MAX_GUIDES_PER_POST = 3
MAX_FACTORY_PER_POST = 3


def _tokens(text: Any) -> set[str]:
    import re

    return {
        w
        for w in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(w) >= 4
    }


def _live_products(db: Session) -> dict[str, dict[str, Any]]:
    """{woo_id: 卡片数据}。只收**线上可见**的产品。

    图和真实链接来自 Woo(本地没有可用的公网图 URL,见 ``wc_sync`` 文档)。
    Woo 核不了(返回 None)时**退回只用本地数据**——宁可卡片没图,
    也不能因为一次抖动让全站卡片消失。
    """
    from ..k_series.product_knowledge.models import KProductKnowledgeProduct
    from ..p_series.upload.models import PUploadJob
    from ..content_core.wc_sync import fetch_product_states_safely

    rows = db.execute(
        select(
            PUploadJob.product_id,
            PUploadJob.external_product_id,
        ).where(
            PUploadJob.status == "success",
            PUploadJob.external_product_id.is_not(None),
        )
        .order_by(PUploadJob.finished_at.desc(), PUploadJob.created_at.desc())
    ).all()

    woo_by_product: dict[str, int] = {}
    for product_id, external in rows:
        text = str(external or "").strip()
        key = str(product_id)
        if text.isdigit() and key not in woo_by_product:
            woo_by_product[key] = int(text)
    if not woo_by_product:
        return {}

    products = {
        str(p.id): p
        for p in db.execute(select(KProductKnowledgeProduct)).scalars()
        if str(p.id) in woo_by_product
    }

    # 出网前放掉事务(idle-in-txn 死规矩)。
    db.commit()
    states = fetch_product_states_safely(db, list(woo_by_product.values()))

    out: dict[str, dict[str, Any]] = {}
    for product_key, woo_id in sorted(woo_by_product.items(), key=lambda kv: kv[1]):
        product = products.get(product_key)
        if product is None:
            continue
        state = (states or {}).get(woo_id) or {}
        if states is not None and state.get("status") not in ("publish", ""):
            continue  # Woo 说它不在线 —— 挂上去就是死链
        name = state.get("name") or str(
            getattr(product, "product_name_en", "") or ""
        ).strip()
        url = state.get("permalink") or ""
        if not url:
            from ..geo_series.content.product_links import latest_public_url

            url = latest_public_url(db, [product.id]).get(product_key, "")
        if not name or not url:
            continue
        out[str(woo_id)] = {
            "n": name[:160],
            "u": url,
            "i": state.get("image_id"),
            "s": state.get("image_src") or "",
            "c": str(getattr(product, "google_product_category", "") or ""),
            "k": product_key,
            # 绝不放价格(GMC 红线,见模块文档)。
        }
    return out


def _live_articles(db: Session) -> tuple[dict[str, dict], dict[str, dict]]:
    """({guides}, {factory articles})，键都是 WP post id。只收 ``wp_status=publish``。"""
    from ..geo_series.content.models import GeoContentCluster, GeoContentItem
    from ..seo_series.content import constants as SC
    from ..seo_series.content.models import SeoContentItem, SeoTopic

    cluster_category = {
        c.id: str(c.google_category_id or "")
        for c in db.execute(select(GeoContentCluster)).scalars()
    }
    guides: dict[str, dict] = {}
    for item in db.execute(
        select(GeoContentItem).where(
            GeoContentItem.review_status == "approved",
            GeoContentItem.wp_status == "publish",
            GeoContentItem.wp_post_id.is_not(None),
            GeoContentItem.published_url.is_not(None),
        )
    ).scalars():
        title = str(item.title or "").strip()
        url = str(item.published_url or "").strip()
        if not title or not url:
            continue
        guides[str(item.wp_post_id)] = {
            "t": title[:200],
            "u": url,
            "c": cluster_category.get(item.cluster_id, ""),
        }

    topic_category = {
        t.id: str(t.google_category_id or "")
        for t in db.execute(select(SeoTopic)).scalars()
    }
    factory: dict[str, dict] = {}
    for item in db.execute(
        select(SeoContentItem).where(
            SeoContentItem.review_status == "approved",
            SeoContentItem.wp_status == "publish",
            SeoContentItem.wp_post_id.is_not(None),
            SeoContentItem.published_url.is_not(None),
        )
    ).scalars():
        title = str(item.title or "").strip()
        url = str(item.published_url or "").strip()
        if not title or not url:
            continue
        entry = {
            "t": title[:200],
            "u": url,
            "c": topic_category.get(item.topic_id, ""),
            "d": item.destination,
        }
        if item.destination == SC.DESTINATION_FACTORY:
            factory[str(item.wp_post_id)] = entry
        else:
            # /posts/ 的 C 端博文也是文章,同样要拿到卡片和推荐。
            guides.setdefault(str(item.wp_post_id), entry)
    return guides, factory


def _pick_products(
    post: dict[str, Any],
    products: dict[str, dict[str, Any]],
    family: set[str],
) -> list[tuple[str, str]]:
    """[(woo_id, 匹配依据)]。类目命中优先,词面只是兜底。"""
    picked: list[tuple[int, str, str]] = []
    want = _tokens(post.get("t"))
    for woo_id, card in products.items():
        category = str(card.get("c") or "")
        if category and category in family:
            picked.append((0, woo_id, "category"))
            continue
        overlap = len(want & _tokens(card.get("n")))
        # 词面兜底至少要重合两个词。**一个通用词的重合不构成相关**——
        # 2026-07-30 「包子捏捏挂到户外店批发文」就是只重合了 "Portable"。
        if overlap >= 2:
            picked.append((10 - min(overlap, 9), woo_id, "tokens"))
    picked.sort(key=lambda row: (row[0], row[1]))
    return [(woo_id, by) for _rank, woo_id, by in picked[:MAX_PRODUCTS_PER_POST]]


def build_link_map(db: Session, *, scope_context: Any = None) -> dict[str, Any]:
    """全站链接图。**纯计算 + 一次 Woo 批量读,不写任何东西。**"""
    del scope_context  # 只有一个独立站;参数留着别把假设焊死在签名里

    from ..geo_series.content.cluster_guard import (
        category_ancestors,
        category_descendants,
    )

    products = _live_products(db)
    guides, factory = _live_articles(db)

    # 类目的亲缘关系一次算完,避免每篇文章都递归查一遍。
    families: dict[str, set[str]] = {}

    def family_of(category: str) -> set[str]:
        if not category:
            return set()
        if category not in families:
            families[category] = {
                category,
                *category_ancestors(db, category),
                *category_descendants(db, category),
            }
        return families[category]

    posts: dict[str, dict[str, Any]] = {}
    product_by: dict[str, str] = {}

    for post_id, post in sorted({**guides, **factory}.items()):
        family = family_of(str(post.get("c") or ""))

        chosen = _pick_products(post, products, family)
        for woo_id, by in chosen:
            # 同一个产品在不同文章里可能一处按类目、一处按词面命中。
            # 只要有一处是类目命中就算类目——词面标记是给人工复核用的。
            if product_by.get(woo_id) != "category":
                product_by[woo_id] = by

        related_guides = sorted(
            gid
            for gid, g in guides.items()
            if gid != post_id
            and str(g.get("c") or "")
            and str(g.get("c")) in family
        )[:MAX_GUIDES_PER_POST]
        related_factory = sorted(
            fid
            for fid, f in factory.items()
            if fid != post_id
            # 工艺文没绑类目 = 通用工艺,对任何文章都算数
            and (not str(f.get("c") or "") or str(f.get("c")) in family)
        )[:MAX_FACTORY_PER_POST]

        entry = {
            "p": [woo_id for woo_id, _by in chosen],
            "g": related_guides,
            "f": related_factory,
        }
        if any(entry.values()):
            posts[post_id] = entry

    # 只保留真被引用到的卡片,别把整个目录塞进 option。
    used_products = {w for e in posts.values() for w in e["p"]}
    used_guides = {g for e in posts.values() for g in e["g"]}
    used_factory = {f for e in posts.values() for f in e["f"]}

    return {
        "v": LINK_MAP_VERSION,
        "p": {
            w: {
                "n": products[w]["n"],
                "u": products[w]["u"],
                "i": products[w]["i"],
                "s": products[w]["s"],
                "by": product_by.get(w, "category"),
            }
            for w in sorted(used_products)
        },
        "g": {
            g: {"t": guides[g]["t"], "u": guides[g]["u"]} for g in sorted(used_guides)
        },
        "f": {
            f: {"t": factory[f]["t"], "u": factory[f]["u"]}
            for f in sorted(used_factory)
        },
        "posts": {k: posts[k] for k in sorted(posts)},
    }


def canonical_json(link_map: dict[str, Any]) -> str:
    """规范化 JSON。**内部绝不放时间戳**——放了指纹每次都变。"""
    return json.dumps(link_map, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fingerprint(link_map: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(link_map).encode("utf-8")).hexdigest()


def summarize(link_map: dict[str, Any]) -> dict[str, Any]:
    """给控制台看的一行摘要 + 需要人工核一眼的清单。"""
    by_tokens = sorted(
        w for w, card in (link_map.get("p") or {}).items()
        if card.get("by") == "tokens"
    )
    return {
        "posts": len(link_map.get("posts") or {}),
        "products": len(link_map.get("p") or {}),
        "guides": len(link_map.get("g") or {}),
        "factory": len(link_map.get("f") or {}),
        # 词面匹配的卡片单独列出来:它现在是一张带图大卡片,猜错的代价比
        # 一行小字大得多(2026-07-30 包子捏捏那次)。
        "token_matched": [
            (link_map.get("p") or {}).get(w, {}).get("n", w) for w in by_tokens
        ],
    }


__all__ = [
    "LINK_MAP_VERSION",
    "MAX_FACTORY_PER_POST",
    "MAX_GUIDES_PER_POST",
    "MAX_PRODUCTS_PER_POST",
    "build_link_map",
    "canonical_json",
    "fingerprint",
    "summarize",
]
