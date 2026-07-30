"""Which published guides cover a given product — the product→guide direction.

GEO delivery has two rails. Rail 1 (guide → product) already existed: an answer
engine cites a guide and the reader can reach the product page. This module is the
return leg: a crawler, an answer engine, or a buyer that lands on the **product**
page must be able to discover the guides. Without it the topic cluster is only
half-linked, and every arrival on a PDP is a dead end for anyone still deciding.

Read-only and deliberately narrow: it returns live guide URLs, nothing else. The P
upload path calls it inside a fail-safe wrapper — a missing guide list must never
be able to break a product upload.

**"Live" means live.** It filters on ``wp_status == "publish"``, not merely on a
non-empty ``published_url``: the publisher creates posts as drafts on first push and
writes the URL right then, so the loose check would hand visitors a 404. Callers
that need freshness should run ``live_state.refresh_item_live_state_safely`` once —
in batch — before reading. This function itself never touches the network, because
the B2B caller loops over products and would otherwise fire one request each.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Enough to establish the cluster without turning the product page into a link
# farm; the PDP's job is still to sell.
MAX_GUIDES_ON_PRODUCT = 5

# The hub piece is the best single entry point, so it leads; the rest follow in a
# stable, meaningful reading order.
_ITEM_TYPE_ORDER = {
    "hub": 0,
    "how_it_works": 1,
    "comparison": 2,
    "scenario": 3,
    "qa": 4,
    "product_spotlight": 5,
}


def published_guides_for_product(
    db: Session, *, product_id: Any, product_key: str | None = None
) -> list[tuple[str, str]]:
    """[(title, url)] of live guides whose cluster contains this product."""
    from .models import GeoContentCluster, GeoContentItem

    identifiers = {str(product_id or "").strip(), str(product_key or "").strip()}
    identifiers.discard("")
    if not identifiers:
        return []

    clusters = db.execute(
        select(GeoContentCluster.id, GeoContentCluster.product_ids_json)
    ).all()
    cluster_ids: list[UUID] = []
    for cluster_id, product_ids in clusters:
        owned = product_ids if isinstance(product_ids, list) else []
        if any(str(x).strip() in identifiers for x in owned):
            cluster_ids.append(cluster_id)
    if not cluster_ids:
        return []

    rows = db.execute(
        select(
            GeoContentItem.title,
            GeoContentItem.published_url,
            GeoContentItem.item_type,
        ).where(
            GeoContentItem.cluster_id.in_(cluster_ids),
            GeoContentItem.published_url.is_not(None),
            GeoContentItem.review_status == "approved",
            # 死规矩(2026-07-29): published_url 非空 ≠ 访客看得到。n8n 首次建文
            # 落 draft,URL 那时就已写库;不查真实状态就会把草稿链到产品页 → 404。
            # 这一列由 live_state.refresh_item_live_state 批量刷新维护。
            GeoContentItem.wp_status == "publish",
        )
    ).all()

    ranked = sorted(
        (
            (str(title or "").strip(), str(url or "").strip(), str(item_type or ""))
            for title, url, item_type in rows
        ),
        key=lambda r: (_ITEM_TYPE_ORDER.get(r[2], 99), r[0]),
    )

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for title, url, _item_type in ranked:
        if not title or not url or url in seen:
            continue
        seen.add(url)
        out.append((title, url))
        if len(out) >= MAX_GUIDES_ON_PRODUCT:
            break
    return out


def published_guides_for_product_safely(
    db: Session, *, product_id: Any, product_key: str | None = None
) -> list[tuple[str, str]]:
    """Same, but a GEO-side problem can never break a product upload."""
    try:
        return published_guides_for_product(
            db, product_id=product_id, product_key=product_key
        )
    except Exception:  # noqa: BLE001 - the upload wins; guides are an enhancement
        logger.exception("related-guides lookup failed for product %s", product_id)
        return []


__all__ = [
    "MAX_GUIDES_ON_PRODUCT",
    "published_guides_for_product",
    "published_guides_for_product_safely",
]
