"""CRUD helpers for GEO clusters + items (all scope-filtered for tenant isolation)."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.category_resolver import google_category_path
from ...k_series.product_knowledge.models import KProductKnowledgeProduct
from ...k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from .models import GeoContentCluster, GeoContentItem


def list_clusters(
    db: Session, *, scope_context: KScopeContext
) -> list[GeoContentCluster]:
    query = apply_scope_filters(
        select(GeoContentCluster).order_by(GeoContentCluster.created_at.desc()),
        GeoContentCluster,
        scope_context,
    )
    return list(db.execute(query).scalars().all())


def cluster_item_counts(
    db: Session, *, cluster_ids: list[UUID]
) -> dict[str, int]:
    """content-item count per cluster (drives the list's progress badge)."""
    if not cluster_ids:
        return {}
    rows = db.execute(
        select(GeoContentItem.cluster_id, func.count(GeoContentItem.id))
        .where(GeoContentItem.cluster_id.in_(cluster_ids))
        .group_by(GeoContentItem.cluster_id)
    ).all()
    return {str(cluster_id): int(count) for cluster_id, count in rows}


def get_cluster(
    db: Session, *, cluster_id: UUID, scope_context: KScopeContext
) -> GeoContentCluster | None:
    query = apply_scope_filters(
        select(GeoContentCluster).where(GeoContentCluster.id == cluster_id),
        GeoContentCluster,
        scope_context,
    )
    return db.execute(query).scalar_one_or_none()


def list_items(
    db: Session, *, cluster_id: UUID, scope_context: KScopeContext
) -> list[GeoContentItem]:
    query = apply_scope_filters(
        select(GeoContentItem)
        .where(GeoContentItem.cluster_id == cluster_id)
        .order_by(GeoContentItem.item_type, GeoContentItem.created_at),
        GeoContentItem,
        scope_context,
    )
    return list(db.execute(query).scalars().all())


def get_item(
    db: Session, *, item_id: UUID, scope_context: KScopeContext
) -> GeoContentItem | None:
    query = apply_scope_filters(
        select(GeoContentItem).where(GeoContentItem.id == item_id),
        GeoContentItem,
        scope_context,
    )
    return db.execute(query).scalar_one_or_none()


def create_cluster(
    db: Session,
    *,
    scope_context: KScopeContext,
    title: str,
    topic: str | None = None,
    google_category_id: str | None = None,
    category_path: str | None = None,
    seed_product_id: UUID | None = None,
    user: Any | None = None,
) -> GeoContentCluster:
    # 同一片话题只能有一个簇——父簇和子簇并存会互相抢词(见 cluster_guard)。
    # **两个方向都拦**:手工建簇时,祖先和后代一样是自我竞争。
    if google_category_id:
        from .cluster_guard import assert_no_overlapping_cluster

        assert_no_overlapping_cluster(
            db, google_category_id=google_category_id, scope_context=scope_context
        )
    cluster = GeoContentCluster(
        workspace_key=scope_context.workspace_key,
        business_context=scope_context.business_context,
        scope_mode=scope_context.scope_mode,
        title=title.strip()[:512] or "Untitled cluster",
        topic=(topic or None),
        google_category_id=google_category_id,
        category_path=category_path,
        seed_product_id=seed_product_id,
        status="draft",
        created_by_user_id=getattr(user, "id", None),
    )
    db.add(cluster)
    db.flush()
    return cluster


def create_cluster_from_product(
    db: Session,
    *,
    product_id: UUID,
    scope_context: KScopeContext,
    user: Any | None = None,
) -> GeoContentCluster:
    """Seed a topic cluster from a K product (the pilot/test path).

    Derives topic + category + breadcrumb from the product; the product becomes
    the cluster's seed so generation draws on its verified facts.
    """
    query = apply_scope_filters(
        select(KProductKnowledgeProduct).where(
            KProductKnowledgeProduct.id == product_id
        ),
        KProductKnowledgeProduct,
        scope_context,
    )
    product = db.execute(query).scalar_one_or_none()
    if product is None:
        raise ValueError("product_not_found")

    google_id = getattr(product, "google_product_category", None)
    category_path = ""
    leaf_name = ""
    if google_id:
        try:
            path = google_category_path(db, str(google_id))
            category_path = " > ".join(str(seg.get("name") or "") for seg in path)
            if path:
                leaf_name = str(path[-1].get("name") or "")
        except Exception:  # noqa: BLE001 - breadcrumb is best-effort
            category_path = ""

    topic = (
        getattr(product, "primary_keyword", None)
        or leaf_name
        or getattr(product, "product_name_en", None)
        or "product"
    )
    title = f"{topic} — buyer guide".strip()
    return create_cluster(
        db,
        scope_context=scope_context,
        title=title,
        topic=str(topic),
        google_category_id=str(google_id) if google_id else None,
        category_path=category_path or None,
        seed_product_id=product.id,
        user=user,
    )


def set_item_review(
    db: Session,
    *,
    item_id: UUID,
    scope_context: KScopeContext,
    review_status: str,
    user: Any | None = None,
) -> GeoContentItem | None:
    item = get_item(db, item_id=item_id, scope_context=scope_context)
    if item is None:
        return None
    if review_status not in ("pending", "approved", "rejected"):
        raise ValueError("invalid_review_status")
    item.review_status = review_status
    item.reviewed_by_user_id = getattr(user, "id", None)
    from datetime import UTC, datetime

    item.reviewed_at = datetime.now(UTC)
    db.flush()
    return item


def _selling_point_set(product: KProductKnowledgeProduct) -> set[str]:
    """Coarse fingerprint of a product's pitch, for sibling comparison.

    Words from the product's own name are excluded: every product's copy repeats
    its own theme noun ("cheese", "butter", "cat"), which says nothing about
    whether the products actually differ.
    """
    payload = getattr(product, "selling_points_approved_json", None)
    words: set[str] = set()
    bullets = payload.get("bullets") if isinstance(payload, dict) else None
    for bullet in bullets or []:
        if isinstance(bullet, dict):
            text = str(bullet.get("text") or "").lower()
            words |= {w for w in re.findall(r"[a-z]{4,}", text)}
    own_name = str(getattr(product, "product_name_en", "") or "").lower()
    return words - set(re.findall(r"[a-z]{4,}", own_name))


def _spec_label_set(product: KProductKnowledgeProduct) -> set[str]:
    """The product's functional attribute names (factual, not copywriting style)."""
    specs = getattr(product, "structured_specs_json", None)
    if not isinstance(specs, dict):
        return set()
    labels: set[str] = set()
    for item in specs.get("additional_specs") or []:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("label_en") or "").strip().lower()
            if label:
                labels.add(label)
    return labels


def cluster_products(
    db: Session, *, cluster: GeoContentCluster
) -> list[dict[str, Any]]:
    """The cluster's products, each flagged when it looks materially different.

    The machine cannot judge "this one deserves its own article" — five stress
    balls that differ only in shape must NOT each get one. So it only surfaces the
    evidence (how much this product's pitch diverges from its siblings) and the
    operator decides whether to add a product_spotlight article.
    """
    raw_ids = cluster.product_ids_json
    ids: list[str] = [str(x) for x in raw_ids] if isinstance(raw_ids, list) else []
    if not ids and cluster.seed_product_id:
        ids = [str(cluster.seed_product_id)]
    pending_raw = cluster.pending_product_ids_json
    pending = {str(x) for x in pending_raw} if isinstance(pending_raw, list) else set()

    loaded: list[tuple[str, KProductKnowledgeProduct]] = []
    for pid in ids:
        try:
            product = db.get(KProductKnowledgeProduct, UUID(pid))
        except (TypeError, ValueError):
            continue
        if product is not None:
            loaded.append((pid, product))

    fingerprints = {pid: _selling_point_set(p) for pid, p in loaded}
    spec_labels = {pid: _spec_label_set(p) for pid, p in loaded}
    out: list[dict[str, Any]] = []
    for pid, product in loaded:
        mine = fingerprints[pid]
        siblings: set[str] = set()
        sibling_specs: set[str] = set()
        for other_id, words in fingerprints.items():
            if other_id != pid:
                siblings |= words
                sibling_specs |= spec_labels[other_id]
        unique = mine - siblings
        unique_specs = spec_labels[pid] - sibling_specs
        # DELIBERATELY conservative. Copywriting always varies between products, so
        # word novelty alone flags everything (five stress balls that differ only in
        # shape must stay quiet). Require FUNCTIONAL novelty — attributes the
        # siblings simply do not have — plus a majority-unique pitch. Whether a
        # product deserves its own article is ultimately the operator's call; this
        # is only a nudge, never a verdict.
        unique_ratio = (len(unique) / len(mine)) if mine else 0.0
        differentiated = (
            bool(siblings) and len(unique_specs) >= 2 and unique_ratio > 0.5
        )
        out.append(
            {
                "product_id": pid,
                "sku": getattr(product, "sku", None),
                "name": getattr(product, "product_name_en", None),
                "is_seed": str(cluster.seed_product_id) == pid,
                "is_pending": pid in pending,
                "differentiated": differentiated,
                "unique_points": sorted(unique)[:8],
                "unique_specs": sorted(unique_specs)[:6],
            }
        )
    return out


def save_picked_questions(
    db: Session,
    *,
    cluster_id: UUID,
    scope_context: KScopeContext,
    questions: list[Any],
    user: Any | None = None,
) -> GeoContentCluster | None:
    """Store the operator's picked buyer questions as the cluster's required set."""
    del user
    cluster = get_cluster(db, cluster_id=cluster_id, scope_context=scope_context)
    if cluster is None:
        return None
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in questions or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or "").strip()
        key = text.lower().rstrip("?").strip()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(
            {
                "question": text[:512],
                "intent": str(item.get("intent") or "").strip()[:64],
            }
        )
    cluster.picked_questions_json = cleaned
    db.flush()
    return cluster


def serialize_cluster(cluster: GeoContentCluster) -> dict[str, Any]:
    return {
        "id": str(cluster.id),
        "title": cluster.title,
        "topic": cluster.topic,
        "google_category_id": cluster.google_category_id,
        "category_path": cluster.category_path,
        "seed_product_id": str(cluster.seed_product_id)
        if cluster.seed_product_id
        else None,
        "status": cluster.status,
        "picked_questions": cluster.picked_questions_json or [],
        "product_ids": cluster.product_ids_json or [],
        "pending_product_ids": cluster.pending_product_ids_json or [],
        "created_at": cluster.created_at.isoformat() if cluster.created_at else None,
        "updated_at": cluster.updated_at.isoformat() if cluster.updated_at else None,
    }


def product_label_map(
    db: Session, *, cluster: GeoContentCluster
) -> dict[str, str]:
    """Map the identifiers content can reference (product id / product_key / sku)
    to a human SKU. Generated copy cites whatever identifier it was given, and a
    raw UUID means nothing to the operator."""
    raw_ids = cluster.product_ids_json
    ids: list[str] = [str(x) for x in raw_ids] if isinstance(raw_ids, list) else []
    if not ids and cluster.seed_product_id:
        ids = [str(cluster.seed_product_id)]
    labels: dict[str, str] = {}
    for pid in ids:
        try:
            product = db.get(KProductKnowledgeProduct, UUID(pid))
        except (TypeError, ValueError):
            continue
        if product is None:
            continue
        sku = str(getattr(product, "sku", "") or "").strip()
        if not sku:
            continue
        labels[str(product.id)] = sku
        product_key = str(getattr(product, "product_key", "") or "").strip()
        if product_key:
            labels[product_key] = sku
        labels[sku] = sku
    return labels


def serialize_item(
    item: GeoContentItem, *, product_labels: dict[str, str] | None = None
) -> dict[str, Any]:
    raw_sources = item.source_product_ids_json
    sources = [str(s) for s in raw_sources] if isinstance(raw_sources, list) else []
    labels = product_labels or {}
    return {
        "id": str(item.id),
        "cluster_id": str(item.cluster_id),
        "item_type": item.item_type,
        "title": item.title,
        "body": item.body_json,
        "seo": item.seo_json,
        "source_products": item.source_product_ids_json,
        # SKU where we can resolve it, raw identifier otherwise.
        "source_product_labels": [labels.get(s, s) for s in sources],
        "analysis": item.analysis_json,
        "revision": item.revision_json,
        "schema_type": item.schema_type,
        "brand_audit": item.brand_audit_json,
        "review_status": item.review_status,
        "generation_status": item.generation_status,
        "skill_version": item.skill_version,
        "provider": item.provider,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


__all__ = [
    "list_clusters",
    "get_cluster",
    "list_items",
    "get_item",
    "create_cluster",
    "create_cluster_from_product",
    "set_item_review",
    "save_picked_questions",
    "cluster_products",
    "cluster_item_counts",
    "product_label_map",
    "serialize_cluster",
    "serialize_item",
]
