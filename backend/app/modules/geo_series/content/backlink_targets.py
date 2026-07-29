"""Which live products need their "Learn more" block refreshed, and to what.

The console decides everything here so the workflow stays a dumb pipe: it resolves
the Woo product id from the successful upload, builds the finished block, and drops
products that would be a no-op — a run that rewrites nothing still costs API calls
and shows up as churn in the store's revision history.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.models import KProductKnowledgeProduct
from ...p_series.upload.models import PUploadJob
from .backlink import guides_block_for_product
from .models import GeoContentCluster

logger = logging.getLogger(__name__)


def _woo_id_for(db: Session, product_id: Any) -> int | None:
    """The live Woo product id, from the newest successful upload of this product."""
    rows = db.execute(
        select(PUploadJob.external_product_id)
        .where(
            PUploadJob.product_id == product_id,
            PUploadJob.status == "success",
            PUploadJob.external_product_id.is_not(None),
        )
        .order_by(PUploadJob.finished_at.desc(), PUploadJob.created_at.desc())
    ).all()
    for (external_id,) in rows:
        text = str(external_id or "").strip()
        if text.isdigit() and int(text) > 0:
            return int(text)
    return None


def _cluster_product_ids(db: Session) -> list[str]:
    """Every product attached to any cluster — those are the only candidates."""
    ids: list[str] = []
    seen: set[str] = set()
    for (product_ids,) in db.execute(
        select(GeoContentCluster.product_ids_json)
    ).all():
        for raw in product_ids if isinstance(product_ids, list) else []:
            text = str(raw or "").strip()
            if text and text not in seen:
                seen.add(text)
                ids.append(text)
    return ids


def collect_backlink_targets(db: Session) -> tuple[list[dict[str, Any]], list[str]]:
    """(targets, skipped) — targets are ready to ship, skipped explains the rest.

    A product is skipped when it has no live Woo page yet, or when it has no
    published guides to link (nothing to add, nothing stale to remove).
    """
    targets: list[dict[str, Any]] = []
    skipped: list[str] = []

    for raw_id in _cluster_product_ids(db):
        product = None
        for column in (KProductKnowledgeProduct.id, KProductKnowledgeProduct.product_key):
            try:
                product = db.scalar(
                    select(KProductKnowledgeProduct).where(column == raw_id)
                )
            except Exception:  # noqa: BLE001 - a UUID column rejects a non-UUID string
                db.rollback()
                product = None
            if product is not None:
                break
        if product is None:
            skipped.append(f"{raw_id}：K 里找不到这个产品")
            continue

        label = str(getattr(product, "sku", "") or product.id)
        woo_id = _woo_id_for(db, product.id)
        if woo_id is None:
            skipped.append(f"{label}：还没有成功上架的 Woo 产品页")
            continue

        block = guides_block_for_product(
            db, product_id=product.id, product_key=product.product_key
        )
        if not block:
            skipped.append(f"{label}：还没有已发布的指南可挂")
            continue

        targets.append(
            {
                "product_id": str(product.id),
                "sku": getattr(product, "sku", None),
                "woo_product_id": woo_id,
                "block_html": block,
                "guide_count": block.count("<li>"),
            }
        )

    return targets, skipped


__all__ = ["collect_backlink_targets"]
