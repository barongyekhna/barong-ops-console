"""库存盘点：排期器和选图器眼里「现在有什么可以发」。

只读。源头准入按家规：
- K 产品要 approved，且有 **漂亮的** /product/ 公开链接（geo product_links 的坑）；
- GEO 指南要 wp_status == publish 且链接不是 ?p= 草稿形；
- 工艺事实要 approved；
- 工厂照片只认 asset_role == factory 的真照片。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..content_core.facts.models import CraftFact
from ..geo_series.content.models import GeoContentCluster, GeoContentItem
from ..geo_series.content.product_links import latest_public_url
from ..k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
)
from ..k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from .constants import (
    ASSET_ROLE_BRAND,
    ASSET_ROLE_DESCRIPTION,
    ASSET_ROLE_FACTORY,
    ASSET_ROLE_GALLERY,
    ASSET_ROLE_MAIN,
    PLATFORMS,
    SOURCE_CRAFT_FACT,
    SOURCE_GEO_ITEM,
    SOURCE_K_PRODUCT,
)
from .models import SmPost


@dataclass
class ProductSource:
    product_id: UUID
    sku: str
    name: str
    public_url: str
    stock_status: str | None
    approved_at: datetime | None
    brand_clean: bool
    asset_counts: dict[str, int] = field(default_factory=dict)
    last_posted: dict[str, datetime | None] = field(default_factory=dict)

    @property
    def in_stock(self) -> bool:
        return (self.stock_status or "instock").lower() not in {"outofstock", "out_of_stock", "0"}


@dataclass
class GuideSource:
    item_id: UUID
    cluster_id: UUID
    seed_product_id: UUID | None
    title: str
    item_type: str
    public_url: str
    section_count: int
    published_at: datetime | None
    last_posted: dict[str, datetime | None] = field(default_factory=dict)


@dataclass
class FactSource:
    fact_id: UUID
    topic: str
    claim: str
    product_ids: list[UUID]
    approved_at: datetime | None
    last_posted: dict[str, datetime | None] = field(default_factory=dict)


@dataclass
class InventorySnapshot:
    products: list[ProductSource]
    guides: list[GuideSource]
    facts: list[FactSource]
    factory_photo_count: int
    brand_asset_count: int

    def summary(self) -> dict[str, Any]:
        pins_reserve = sum(
            p.asset_counts.get(ASSET_ROLE_MAIN, 0)
            + p.asset_counts.get(ASSET_ROLE_GALLERY, 0)
            + p.asset_counts.get(ASSET_ROLE_DESCRIPTION, 0)
            for p in self.products
        ) + sum(min(6, max(1, g.section_count)) for g in self.guides)
        return {
            "products": len(self.products),
            "products_in_stock": sum(1 for p in self.products if p.in_stock),
            "guides": len(self.guides),
            "facts": len(self.facts),
            "factory_photos": self.factory_photo_count,
            "brand_assets": self.brand_asset_count,
            "pin_reserve_estimate": pins_reserve,
        }


def _brand_clean(product: KProductKnowledgeProduct) -> bool:
    audit = product.brand_audit_json if isinstance(product.brand_audit_json, dict) else {}
    override = audit.get("operator_override")
    if isinstance(override, dict) and override.get("enabled"):
        return True
    return bool(audit.get("clean"))


def _last_posted_map(
    db: Session, scope: KScopeContext, *, source_type: str
) -> dict[tuple[UUID, str], datetime]:
    rows = db.execute(
        apply_scope_filters(
            select(SmPost.source_id, SmPost.platform, func.max(SmPost.created_at)),
            SmPost,
            scope,
        )
        .where(SmPost.source_type == source_type, SmPost.source_id.is_not(None))
        .group_by(SmPost.source_id, SmPost.platform)
    ).all()
    return {(row[0], row[1]): row[2] for row in rows}


def _is_pretty_guide_url(url: str | None) -> bool:
    value = str(url or "").strip()
    return bool(value) and "?p=" not in value and "post_type=" not in value


def load_inventory(db: Session, scope: KScopeContext) -> InventorySnapshot:
    # -- 产品 ---------------------------------------------------------------
    products_rows = list(
        db.execute(
            apply_scope_filters(select(KProductKnowledgeProduct), KProductKnowledgeProduct, scope).where(
                KProductKnowledgeProduct.review_status == "approved",
                KProductKnowledgeProduct.product_status != "archived",
            )
        ).scalars()
    )
    urls = latest_public_url(db, [p.id for p in products_rows]) if products_rows else {}
    product_ids = [p.id for p in products_rows if str(p.id) in urls]
    asset_counts: dict[UUID, dict[str, int]] = {pid: {} for pid in product_ids}
    if product_ids:
        rows = db.execute(
            select(
                KProductKnowledgeMediaAsset.product_id,
                KProductKnowledgeMediaAsset.asset_role,
                func.count(),
            )
            .where(
                KProductKnowledgeMediaAsset.product_id.in_(product_ids),
                KProductKnowledgeMediaAsset.status == "available",
                KProductKnowledgeMediaAsset.asset_type == "image",
            )
            .group_by(KProductKnowledgeMediaAsset.product_id, KProductKnowledgeMediaAsset.asset_role)
        ).all()
        for pid, role, count in rows:
            asset_counts.setdefault(pid, {})[str(role)] = int(count)
    posted_products = _last_posted_map(db, scope, source_type=SOURCE_K_PRODUCT)
    products: list[ProductSource] = []
    for p in products_rows:
        url = urls.get(str(p.id))
        if not url:
            continue
        products.append(
            ProductSource(
                product_id=p.id,
                sku=str(p.sku or p.product_key or p.id),
                name=str(p.product_name_en or p.primary_keyword or p.sku or ""),
                public_url=url,
                stock_status=p.stock_status,
                approved_at=p.updated_at,
                brand_clean=_brand_clean(p),
                asset_counts=asset_counts.get(p.id, {}),
                last_posted={pl: posted_products.get((p.id, pl)) for pl in PLATFORMS},
            )
        )
    products.sort(key=lambda s: s.sku)

    # -- 指南 ---------------------------------------------------------------
    guide_rows = list(
        db.execute(
            apply_scope_filters(select(GeoContentItem), GeoContentItem, scope).where(
                GeoContentItem.review_status == "approved",
                GeoContentItem.wp_status == "publish",
                GeoContentItem.published_url.is_not(None),
            )
        ).scalars()
    )
    cluster_ids = {g.cluster_id for g in guide_rows}
    clusters = (
        {
            c.id: c
            for c in db.execute(
                select(GeoContentCluster).where(GeoContentCluster.id.in_(list(cluster_ids)))
            ).scalars()
        }
        if cluster_ids
        else {}
    )
    posted_guides = _last_posted_map(db, scope, source_type=SOURCE_GEO_ITEM)
    guides: list[GuideSource] = []
    for g in guide_rows:
        if not _is_pretty_guide_url(g.published_url):
            continue
        body = g.body_json if isinstance(g.body_json, dict) else {}
        sections = body.get("sections") if isinstance(body.get("sections"), list) else []
        cluster = clusters.get(g.cluster_id)
        guides.append(
            GuideSource(
                item_id=g.id,
                cluster_id=g.cluster_id,
                seed_product_id=getattr(cluster, "seed_product_id", None),
                title=str(g.title or ""),
                item_type=str(g.item_type or ""),
                public_url=str(g.published_url),
                section_count=len(sections),
                published_at=g.published_at,
                last_posted={pl: posted_guides.get((g.id, pl)) for pl in PLATFORMS},
            )
        )
    guides.sort(key=lambda s: s.title)

    # -- 工艺事实 -----------------------------------------------------------
    fact_rows = list(
        db.execute(
            apply_scope_filters(select(CraftFact), CraftFact, scope).where(CraftFact.status == "approved")
        ).scalars()
    )
    posted_facts = _last_posted_map(db, scope, source_type=SOURCE_CRAFT_FACT)
    facts: list[FactSource] = []
    for f in fact_rows:
        pids = f.product_ids_json if isinstance(f.product_ids_json, list) else []
        facts.append(
            FactSource(
                fact_id=f.id,
                topic=str(f.topic or ""),
                claim=str(f.claim or ""),
                product_ids=[UUID(str(x)) for x in pids if str(x)],
                approved_at=f.approved_at,
                last_posted={pl: posted_facts.get((f.id, pl)) for pl in PLATFORMS},
            )
        )

    # -- 真照片 / 品牌图 ---------------------------------------------------
    def _count_role(role: str) -> int:
        if not product_ids:
            return 0
        return int(
            db.scalar(
                select(func.count())
                .select_from(KProductKnowledgeMediaAsset)
                .where(
                    KProductKnowledgeMediaAsset.product_id.in_(product_ids),
                    KProductKnowledgeMediaAsset.asset_role == role,
                    KProductKnowledgeMediaAsset.status == "available",
                )
            )
            or 0
        )

    return InventorySnapshot(
        products=products,
        guides=guides,
        facts=facts,
        factory_photo_count=_count_role(ASSET_ROLE_FACTORY),
        brand_asset_count=_count_role(ASSET_ROLE_BRAND),
    )


__all__ = [
    "FactSource",
    "GuideSource",
    "InventorySnapshot",
    "ProductSource",
    "load_inventory",
]
