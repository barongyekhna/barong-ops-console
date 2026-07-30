"""Build the GuidePackage a publish run sends to WordPress.

Only approved pieces travel. Everything the publisher needs is resolved here, so
n8n stays a dumb, auditable pipe: real product URLs are already embedded, sibling
links are placeholder tokens it swaps once every post exists, and the category is
a term id it just attaches.

The gate is the caller's job (``publish_gate.publish_blockers``) — by the time
this runs, the package is publishable by construction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.models import KProductKnowledgeProduct
from ...k_series.product_knowledge.scope_shim import KScopeContext
from ..contract.publish_package import (
    GEO_PUBLISH_PACKAGE_VERSION,
    Article,
    ClusterRef,
    FaqItem,
    Gate,
    GuidePackage,
    Seo,
)
from .models import GeoContentCluster, GeoContentItem
from .product_links import product_label_map, product_link_map
from .publish_gate import publishable_items
from ...content_core.publish_html import link_token, plain_text, render_article_html


def _cluster_products(
    db: Session, cluster: GeoContentCluster, scope_context: KScopeContext
) -> list[KProductKnowledgeProduct]:
    raw = cluster.product_ids_json
    ids: list[str] = [str(x) for x in raw] if isinstance(raw, list) else []
    if not ids and cluster.seed_product_id:
        ids = [str(cluster.seed_product_id)]
    out: list[KProductKnowledgeProduct] = []
    for pid in ids:
        try:
            product = db.get(KProductKnowledgeProduct, UUID(pid))
        except (TypeError, ValueError):
            continue
        if product is not None:
            out.append(product)
    return out


def assemble_guide_package(
    db: Session,
    *,
    cluster: GeoContentCluster,
    items: list[GeoContentItem],
    scope_context: KScopeContext,
    job_id: str | None = None,
    wp_category_id: int | None = None,
) -> GuidePackage:
    ready = publishable_items(items)
    products = _cluster_products(db, cluster, scope_context)
    product_links, _unlinkable = product_link_map(db, products)
    product_labels = product_label_map(products)
    # Every product in the cluster, so a product added to this category later shows
    # up on the next publish without regenerating or re-approving anything.
    cluster_product_ids = [str(p.id) for p in products]

    articles: list[Article] = []
    for item in ready:
        siblings = [
            (str(other.title), str(other.id)) for other in ready if other.id != item.id
        ]
        html = render_article_html(
            item,
            product_links=product_links,
            product_labels=product_labels,
            cluster_product_ids=cluster_product_ids,
            sibling_links=siblings,
        )
        seo_raw = item.seo_json if isinstance(item.seo_json, dict) else {}
        body = item.body_json if isinstance(item.body_json, dict) else {}
        faq = [
            FaqItem(
                question=str(b.get("question") or "").strip(),
                answer=str(b.get("answer") or "").strip(),
            )
            for b in (body.get("answer_blocks") or [])
            if isinstance(b, dict)
            and str(b.get("question") or "").strip()
            and str(b.get("answer") or "").strip()
        ]
        articles.append(
            Article(
                item_id=item.id,
                item_type=item.item_type,
                title=str(item.title),
                html=html,
                text=plain_text(item),
                seo=Seo(
                    title=str(seo_raw.get("title") or "").strip() or None,
                    meta_description=(
                        str(seo_raw.get("meta_description") or "").strip() or None
                    ),
                    # 二道锁:已经发布过的 post 干脆不下发 slug,让 WordPress 保持
                    # 现有固定链接。即使库里的 slug 被改脏了,线上地址也动不了。
                    url_slug=(
                        None
                        if item.wp_post_id
                        else (str(seo_raw.get("url_slug") or "").strip() or None)
                    ),
                ),
                schema_type="FAQPage" if item.item_type == "qa" else "Article",
                faq=faq,
                wp_existing_post_id=item.wp_post_id,
                link_token=link_token(item.id),
            )
        )

    category_path = [
        segment.strip()
        for segment in str(cluster.category_path or "").split(">")
        if segment.strip()
    ]
    return GuidePackage(
        schema_version=GEO_PUBLISH_PACKAGE_VERSION,
        job_id=job_id,
        cluster_id=cluster.id,
        channel="wordpress",
        generated_at=datetime.now(UTC),
        gate=Gate(ready=True, blockers=[]),
        cluster=ClusterRef(
            title=str(cluster.title),
            topic=cluster.topic,
            category_path=category_path,
            google_category_id=cluster.google_category_id,
        ),
        wp_category_id=wp_category_id,
        articles=articles,
    )


def load_cluster_items(
    db: Session, *, cluster_id: UUID, scope_context: KScopeContext
) -> list[GeoContentItem]:
    from ...k_series.product_knowledge.scope_shim import apply_scope_filters

    query = apply_scope_filters(
        select(GeoContentItem)
        .where(GeoContentItem.cluster_id == cluster_id)
        .order_by(GeoContentItem.item_type, GeoContentItem.created_at),
        GeoContentItem,
        scope_context,
    )
    return list(db.execute(query).scalars().all())


def cluster_products(
    db: Session, *, cluster: GeoContentCluster, scope_context: KScopeContext
) -> list[Any]:
    return _cluster_products(db, cluster, scope_context)


__all__ = ["assemble_guide_package", "load_cluster_items", "cluster_products"]
