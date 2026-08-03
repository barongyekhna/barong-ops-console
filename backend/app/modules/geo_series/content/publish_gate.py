"""What must be true before a cluster's guides may go live.

Same posture as the P upload gate: fail closed, return human-readable Chinese
blockers, and never let the caller publish around it. The rules encode decisions
made while building this module:

* only content the operator **approved** is publishable — machine-clean is not
  consent (M1 ruling);
* the machine audit must be clean (no third-party brand, no CJK, no ungrounded
  numbers) — a red audit never reaches the site;
* every piece needs its own slug, otherwise WordPress invents one and the
  K-authored permalink is lost;
* a product may only be linked when it has a real public product page. Linking a
  draft product hands the reader a 404 (found in live data: early upload rows
  carry the draft-era ``?post_type=product&p=…`` permalink);
* **every article must land in its Google-taxonomy category** (owner's ruling
  2026-07-29). Category placement used to be best-effort — a failed lookup simply
  published the post uncategorised, which silently drops it out of the site's
  structure. It is now a blocker: no resolvable category, no publish.
"""

from __future__ import annotations

import logging

from ...content_core.guards import audit_is_clean

logger = logging.getLogger(__name__)

from typing import Any

from sqlalchemy.orm import Session

from ...k_series.product_knowledge.scope_shim import KScopeContext
from .product_links import product_link_map


def category_blockers(db: Session, *, cluster: Any) -> list[str]:
    """Why this cluster cannot be filed under a Google-taxonomy category.

    Cheap and network-free: it only checks that the cluster names a Google
    category and that the id resolves to a real path. Actually creating the
    WordPress terms happens at package time, where a failure is a hard 409 rather
    than a silent uncategorised publish.
    """
    google_id = str(getattr(cluster, "google_category_id", "") or "").strip()
    if not google_id:
        return [
            "这个话题簇没有绑定谷歌类目——指南必须落在类目里。"
            "先在 K 里给簇里的产品选定谷歌类目，再来发布。"
        ]
    from ...k_series.product_knowledge.category_resolver import google_category_path

    try:
        path = google_category_path(db, google_id)
    except Exception:  # noqa: BLE001 - a lookup failure is still a blocker
        return [f"谷歌类目 {google_id} 解析失败——修好类目树再发布。"]
    if not path:
        return [
            f"谷歌类目 {google_id} 在类目树里找不到路径——"
            "指南必须落在类目里，不能无类目上线。"
        ]
    return []


def publishable_items(items: list[Any]) -> list[Any]:
    """The pieces a publish run would actually send."""
    return [
        item
        for item in items
        if item.review_status == "approved"
        and item.generation_status == "generated"
    ]


def _readable_product(db: Session, products: list[Any], ident: str) -> str:
    """把内容里引用的标识符翻译成人能认的名字:优先 SKU,其次产品名。

    ``ident`` 可能是 product_key、SKU,也可能是裸 UUID(生成时给模型的就是 UUID)。
    先在本簇的产品里找;找不到再去 K 里捞一次 —— 产品可能已经被移出这个簇,
    但文章里还引着它,那正是最需要说清楚是谁的时候。
    """
    text = str(ident or "").strip()
    for product in products:
        for alias in (product.id, getattr(product, "product_key", None), getattr(product, "sku", None)):
            if str(alias or "").strip() == text:
                sku = str(getattr(product, "sku", "") or "").strip()
                name = str(getattr(product, "product_name_en", "") or "").strip()
                if sku and name:
                    return f"{sku}（{name[:28]}）"
                return sku or name or text
    try:
        from ...k_series.product_knowledge.models import KProductKnowledgeProduct

        row = db.get(KProductKnowledgeProduct, text)
        if row is not None:
            sku = str(getattr(row, "sku", "") or "").strip()
            name = str(getattr(row, "product_name_en", "") or "").strip()
            if sku and name:
                return f"{sku}（{name[:28]}）"
            return sku or name or text
    except Exception:  # noqa: BLE001 - 捞不到就退回原文,总比崩了强
        logger.exception("product label lookup failed for %s", text)
    return text


def publish_blockers(
    db: Session,
    *,
    cluster: Any,
    items: list[Any],
    products: list[Any],
) -> list[str]:
    """Empty list = safe to publish."""
    blockers: list[str] = []

    ready = publishable_items(items)
    if not ready:
        blockers.append(
            "没有已批准的内容——先在内容区批准至少一篇（未批准的不会被发布）。"
        )
        return blockers

    blockers.extend(category_blockers(db, cluster=cluster))

    dirty = [i for i in ready if not audit_is_clean(i.brand_audit_json)]
    if dirty:
        titles = "、".join(str(i.title)[:24] for i in dirty[:3])
        blockers.append(f"有 {len(dirty)} 篇未通过自动审查：{titles}")

    missing_slug = [
        i for i in ready if not str((i.seo_json or {}).get("url_slug") or "").strip()
    ]
    if missing_slug:
        titles = "、".join(str(i.title)[:24] for i in missing_slug[:3])
        blockers.append(f"有 {len(missing_slug)} 篇缺少 URL slug：{titles}")

    # Only complain about products these pieces actually try to link.
    cited: set[str] = set()
    for item in ready:
        raw = item.source_product_ids_json
        if isinstance(raw, list):
            cited |= {str(r).strip() for r in raw if str(r or "").strip()}
    if cited:
        links, unlinkable = product_link_map(db, products)
        cited_unlinkable = [
            label
            for label in unlinkable
            if label in cited
            or any(label == str(getattr(p, "sku", "")) for p in products)
        ]
        # A cited identifier that resolves to nothing is equally a dead link.
        unresolved = sorted(c for c in cited if c not in links)
        if cited_unlinkable or unresolved:
            raw = sorted(set(cited_unlinkable) | set(unresolved))[:3]
            # **绝不把裸 UUID 摆给人看。** 2026-08-02 用户原话:「这里不能显示
            # uuid 因为我没办法分辨」。source_product_ids_json 里存的就是 UUID,
            # 直接拼进消息等于让人对着一串十六进制猜是哪个产品。
            names = "、".join(_readable_product(db, products, ident) for ident in raw)
            blockers.append(
                f"内容里引用的产品还没有公开的产品页（不能链到 404）：{names}。"
                "先把产品在 WooCommerce 后台发布（草稿不算），再来发布指南。"
            )

    return blockers


def cluster_publish_state(
    db: Session,
    *,
    cluster: Any,
    items: list[Any],
    products: list[Any],
    scope_context: KScopeContext | None = None,
) -> dict[str, Any]:
    """Everything the UI needs to explain what a publish click would do."""
    del scope_context
    ready = publishable_items(items)
    blockers = publish_blockers(
        db, cluster=cluster, items=items, products=products
    )
    return {
        "publishable_count": len(ready),
        "total_count": len(items),
        "ready": not blockers,
        "blockers": blockers,
    }


__all__ = [
    "category_blockers",
    "publishable_items",
    "publish_blockers",
    "cluster_publish_state",
]
