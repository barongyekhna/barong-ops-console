"""产品名册:从交易一览(Order / Bestellung 行)把每店真实在卖的 SKU 立起来,落 ``amz_products``。

A 系列不碰 K 的档案(零交集),所以名册从自己的交易数据长出来:SKU、亚马逊上的标题、产品线(按标题关键字)、
卖了多少件、最近一次成交。A1 接上 SP-API 后由 listings 作业覆盖 asin / price;事实表落地后 product_line 以人填的为准。
不 commit。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AmzProduct, AmzTransaction
from .rules import product_line_of

ORDER_TYPES: tuple[str, ...] = ("Order", "Bestellung", "Commande", "Pedido", "Ordine")
MANUAL_LINE_MARK = "manual"


def sync_from_transactions(db: Session, *, store_code: str) -> dict[str, int]:
    """按 SKU 聚合订单行 → upsert。人手改过产品线(metadata.product_line_source=manual)的不覆盖。"""
    T = AmzTransaction
    rows = db.execute(
        select(
            T.sku,
            func.max(T.description),
            func.sum(T.quantity),
            func.count(func.distinct(T.order_id)),
            func.min(T.posted_at),
            func.max(T.posted_at),
        )
        .where(T.store_code == store_code, T.txn_type.in_(ORDER_TYPES), T.sku.is_not(None), T.sku != "")
        .group_by(T.sku)
    ).all()
    existing = {p.sku: p for p in db.scalars(select(AmzProduct).where(AmzProduct.store_code == store_code))}
    created = updated = 0
    for sku, description, units, orders, first_at, last_at in rows:
        title = (description or "").strip()[:512] or None
        line = product_line_of(f"{sku} {title or ''}")
        product = existing.get(sku)
        stats: dict[str, Any] = {
            "source": "transactions",
            "units_total": int(units or 0),
            "orders_total": int(orders or 0),
            "first_sold": first_at.date().isoformat() if first_at else None,
            "last_sold": last_at.date().isoformat() if last_at else None,
        }
        if product is None:
            db.add(
                AmzProduct(
                    store_code=store_code,
                    sku=sku,
                    product_line=line,
                    title=title,
                    metadata_json=stats,
                )
            )
            created += 1
        else:
            meta = dict(product.metadata_json or {})
            meta.update(stats)
            product.metadata_json = meta
            if not product.title:
                product.title = title
            if meta.get("product_line_source") != MANUAL_LINE_MARK:
                product.product_line = line
            db.add(product)
            updated += 1
    db.flush()
    return {"skus": len(rows), "created": created, "updated": updated}


def roster(db: Session, *, store_codes: list[str] | None, limit_per_store: int = 12) -> list[dict[str, Any]]:
    """给员工看的名册:每店按销量排,最多几条。"""
    query = select(AmzProduct).where(AmzProduct.status == "active")
    if store_codes is not None:
        if not store_codes:
            return []
        query = query.where(AmzProduct.store_code.in_(store_codes))
    products = list(db.scalars(query))
    products.sort(key=lambda p: (p.store_code, -int((p.metadata_json or {}).get("units_total") or 0)))
    out: list[dict[str, Any]] = []
    per_store: dict[str, int] = {}
    for p in products:
        n = per_store.get(p.store_code, 0)
        if n >= limit_per_store:
            continue
        per_store[p.store_code] = n + 1
        meta = p.metadata_json or {}
        out.append(
            {
                "店铺": p.store_code,
                "SKU": p.sku,
                "ASIN": p.asin,
                "产品线": p.product_line,
                "标题": (p.title or "")[:80],
                "累计件数": meta.get("units_total"),
                "最近成交": meta.get("last_sold"),
            }
        )
    return out


def as_of_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


__all__ = ["ORDER_TYPES", "roster", "sync_from_transactions"]
