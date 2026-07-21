"""SKU normalization and order enrichment for W-S purchasing sources."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .shipping.models import WProductSource


def normalize_sku(value: object) -> str:
    """Return the canonical key shared by order snapshots and source records."""

    if value is None:
        return ""
    return str(value).strip().upper()


def _normalized_skus_for_items(
    item_payloads: Iterable[list[dict[str, Any]] | None],
) -> set[str]:
    return {
        normalized
        for items in item_payloads
        if isinstance(items, list)
        for item in items
        if isinstance(item, dict)
        if (normalized := normalize_sku(item.get("sku")))
    }


def load_sources_for_items(
    db: Session,
    item_payloads: Iterable[list[dict[str, Any]] | None],
) -> dict[str, WProductSource]:
    """Load every source needed by an order page with at most one IN query."""

    normalized_skus = _normalized_skus_for_items(item_payloads)
    if not normalized_skus:
        return {}
    rows = db.scalars(
        select(WProductSource).where(
            WProductSource.sku.in_(sorted(normalized_skus))
        )
    ).all()
    return {normalize_sku(row.sku): row for row in rows}


def enrich_items(
    items: list[dict[str, Any]] | None,
    sources_by_sku: Mapping[str, WProductSource],
) -> list[dict[str, Any]] | None:
    """Copy an order's JSON items and attach source data without ORM mutation."""

    if items is None:
        return None

    enriched: list[dict[str, Any]] = []
    for original in items:
        item = dict(original)
        source = sources_by_sku.get(normalize_sku(item.get("sku")))
        if source is None:
            item.update(
                source_url=None,
                supplier_name=None,
                unit_cost=None,
                currency=None,
                moq=None,
                source_state="missing",
            )
        else:
            item.update(
                source_url=source.source_url,
                supplier_name=source.supplier_name,
                unit_cost=source.unit_cost,
                currency=source.currency,
                moq=source.moq,
                source_state="linked",
            )
        enriched.append(item)
    return enriched


__all__ = ["enrich_items", "load_sources_for_items", "normalize_sku"]


def fill_source_if_absent(
    db: Session,
    *,
    sku: object,
    source_url: object,
    supplier_name: object = None,
    unit_cost: object = None,
    currency: str = "CNY",
    moq: object = None,
    notes: str | None = None,
) -> bool:
    """自动灌入(F 系列等):只填空,绝不覆盖人工维护的货源记录。

    Returns True 当且仅当新建了一条记录。sku/source_url 缺失时静默跳过——
    调用方都是 fail-safe 场景(导入/上架主流程不能被货源联动打断)。
    """

    normalized = normalize_sku(sku)
    url = str(source_url or "").strip()
    if not normalized or not url.lower().startswith(("http://", "https://")):
        return False
    existing = db.scalar(
        select(WProductSource.id).where(WProductSource.sku == normalized)
    )
    if existing is not None:
        return False
    db.add(
        WProductSource(
            sku=normalized,
            source_url=url[:1000],
            supplier_name=(str(supplier_name).strip()[:200] or None)
            if supplier_name is not None and str(supplier_name).strip()
            else None,
            unit_cost=unit_cost,
            currency=(currency or "CNY")[:8],
            moq=int(moq) if isinstance(moq, int) or (isinstance(moq, str) and moq.isdigit()) else moq,
            notes=(notes or None),
        )
    )
    db.flush()
    return True
