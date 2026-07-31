"""Auto-create / attach a GEO topic cluster when P publishes a product.

Publishing a product should not require the operator to also remember to create a
topic cluster by hand. On a successful P upload this attaches the product to the
cluster for its category — creating that cluster on first use.

**One cluster per category** (the design ruling): products in the same category
share the same buyer questions, so they share one authoritative article set that
links all of them. Five near-identical stress balls must never become five
duplicate articles (self-competition + thin content). Genuinely differentiated
products inside a shared cluster get an opt-in ``product_spotlight`` article
instead of their own cluster.

Nothing is generated here — the cluster lands in ``draft`` waiting for the
operator to pick topics. Approved content of an existing cluster is never touched;
newly attached products are recorded in ``pending_product_ids_json`` so the UI can
surface a "new products" hint and the operator decides whether to refresh.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.category_resolver import google_category_path
from ...k_series.product_knowledge.models import KProductKnowledgeProduct
from ...k_series.product_knowledge.scope_shim import KScopeContext
from .models import GeoContentCluster

logger = logging.getLogger(__name__)


def _scope_for_product(product: KProductKnowledgeProduct) -> KScopeContext:
    return KScopeContext(
        workspace_key=product.workspace_key,
        business_context=product.business_context,
        scope_mode=product.scope_mode,
    )


def _as_id_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def ensure_geo_cluster_for_product(
    db: Session,
    *,
    k_product_id: UUID,
) -> GeoContentCluster | None:
    """Attach the product to its category's cluster, creating the cluster if needed.

    Returns the cluster, or None when the product cannot be resolved / has no
    category bound yet (GEO clusters are category-scoped by design).
    """
    product = db.get(KProductKnowledgeProduct, k_product_id)
    if product is None:
        return None
    google_id = getattr(product, "google_product_category", None)
    if not google_id:
        logger.info(
            "GEO cluster skipped: product %s has no google category bound",
            k_product_id,
        )
        return None
    google_id = str(google_id).strip()
    scope = _scope_for_product(product)
    product_key = str(product.id)

    # 精确匹配防不住谷歌类目树的**祖先-后代**重叠:父类目和子类目会各开一簇,
    # 写同一片话题、抢同一批词。守卫把三种关系分开处理(见 cluster_guard 文档)。
    from .cluster_guard import ClusterOverlapError, resolve_cluster_for_category

    relation, cluster = resolve_cluster_for_category(
        db, google_category_id=google_id, scope_context=scope
    )
    if relation == "ancestor" and cluster is not None:
        logger.info(
            "GEO: product %s (%s) attached to broader cluster %s — "
            "开一个更细的簇会和它抢同一批词",
            k_product_id,
            google_id,
            cluster.id,
        )
    if relation == "descendant":
        # 建父簇会和已有的子簇打架。不静默跳过、也不自动合并——两者都在替人
        # 做决定。留一条明确的日志,产品照常上架,簇的事等人来判。
        try:
            from .cluster_guard import assert_no_descendant_cluster

            assert_no_descendant_cluster(
                db, google_category_id=google_id, scope_context=scope
            )
        except ClusterOverlapError as exc:
            logger.warning("GEO cluster skipped for product %s: %s", k_product_id, exc)
        return None

    category_path = ""
    leaf_name = ""
    try:
        path = google_category_path(db, google_id)
        category_path = " > ".join(str(seg.get("name") or "") for seg in path)
        if path:
            leaf_name = str(path[-1].get("name") or "")
    except Exception:  # noqa: BLE001 - breadcrumb is a display nicety
        logger.exception("GEO cluster category path lookup failed for %s", google_id)

    if cluster is None:
        topic = (
            getattr(product, "primary_keyword", None)
            or leaf_name
            or getattr(product, "product_name_en", None)
            or "product"
        )
        cluster = GeoContentCluster(
            workspace_key=scope.workspace_key,
            business_context=scope.business_context,
            scope_mode=scope.scope_mode,
            google_category_id=google_id,
            category_path=category_path or None,
            topic=str(topic)[:512],
            title=f"{topic} — buyer guide"[:512],
            status="draft",
            seed_product_id=product.id,
            product_ids_json=[product_key],
            pending_product_ids_json=[],
        )
        db.add(cluster)
        db.flush()
        logger.info(
            "GEO cluster created for category %s from product %s",
            google_id,
            k_product_id,
        )
        return cluster

    # Existing cluster: attach without disturbing already-approved content.
    products = _as_id_list(cluster.product_ids_json)
    if product_key in products:
        return cluster
    cluster.product_ids_json = [*products, product_key]
    pending = _as_id_list(cluster.pending_product_ids_json)
    if product_key not in pending:
        cluster.pending_product_ids_json = [*pending, product_key]
    if not cluster.category_path and category_path:
        cluster.category_path = category_path
    db.flush()
    logger.info(
        "GEO cluster %s gained product %s (pending refresh)",
        cluster.id,
        k_product_id,
    )
    return cluster


def ensure_geo_cluster_for_product_safely(
    db: Session,
    *,
    k_product_id: UUID,
) -> None:
    """Wrapper for the P callback path: GEO must never break an upload report."""
    try:
        ensure_geo_cluster_for_product(db, k_product_id=k_product_id)
    except Exception:  # noqa: BLE001 - upload reporting wins; log and move on
        logger.exception(
            "GEO cluster auto-attach failed for K product %s", k_product_id
        )


__all__ = [
    "ensure_geo_cluster_for_product",
    "ensure_geo_cluster_for_product_safely",
]
