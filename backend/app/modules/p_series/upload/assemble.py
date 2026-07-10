"""K 产品 → UploadPackage（P 取数的核心）。

门禁没过就不组装（端点转 409 + blockers）；过了才构造完整包，此时 required
字段齐全。所有内容来自 K；description_html 由 layout skill 拼装；GMC 关键字段
（title/price/availability/image）与包同源，天然一致。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..contract.upload_package import (
    UPLOAD_PACKAGE_SCHEMA_VERSION,
    Category,
    Description,
    Gate,
    Keywords,
    Price,
    Product,
    Seo,
    Stock,
    UploadPackage,
    Variant,
)
from ...k_series.product_knowledge.category_resolver import category_is_bound
from .description_html import build_description_html, plain_text_from_copy

LAYOUT_SKILL_VERSION = "p-product-page-layout-v1"


def gate_blockers(db: Session, product: Any) -> list[str]:
    """进 P 的硬门禁（契约：关键词+卖点+文案+图片，加类目+价格+标题）。"""
    blockers: list[str] = []
    if not (getattr(product, "product_name_en", None) or "").strip():
        blockers.append("标题缺失（product_name_en）")
    if not getattr(product, "marketing_copy_json", None):
        blockers.append("文案未生成（含卖点/关键词）")
    if not _has_bound_image(db, product):
        blockers.append("未绑定图片")
    if not category_is_bound(product):
        blockers.append("未绑定类目")
    if getattr(product, "regular_price", None) is None:
        blockers.append("价格缺失")
    return blockers


def _has_bound_image(db: Session, product: Any) -> bool:
    if (getattr(product, "image_asset_status", None) or "") == "bound":
        return True
    if getattr(product, "selected_image_path", None):
        return True
    row = db.execute(
        text(
            "SELECT 1 FROM k_product_knowledge_media_assets "
            "WHERE product_id = :p AND status = 'bound' LIMIT 1"
        ),
        {"p": str(product.id)},
    ).first()
    return row is not None


def _availability(stock_status: str | None) -> str:
    s = (stock_status or "").lower()
    if "out" in s or s == "0":
        return "out_of_stock"
    if "pre" in s:
        return "preorder"
    return "in_stock"


def _images(db: Session, product: Any, base_url: str) -> list[str]:
    rows = db.execute(
        text(
            "SELECT id FROM k_product_knowledge_media_assets "
            "WHERE product_id = :p AND status = 'bound' "
            "ORDER BY updated_at DESC"
        ),
        {"p": str(product.id)},
    ).fetchall()
    base = base_url.rstrip("/")
    return [f"{base}/api/app/k/media/{r[0]}/file" for r in rows]


def _variants(db: Session, product: Any) -> list[Variant]:
    rows = db.execute(
        text(
            "SELECT variant_sku, color, size, function, price_override "
            "FROM k_product_knowledge_variants WHERE product_id = :p "
            "ORDER BY created_at ASC"
        ),
        {"p": str(product.id)},
    ).mappings().all()
    out: list[Variant] = []
    for r in rows:
        price = None
        if r["price_override"] is not None:
            price = Price(
                regular=Decimal(str(r["price_override"])),
                currency=(product.price_currency or "USD"),
            )
        out.append(
            Variant(
                sku=r["variant_sku"],
                color=r["color"],
                size=r["size"],
                function=r["function"],
                price=price,
            )
        )
    return out


def assemble_upload_package(
    db: Session,
    product: Any,
    *,
    channel: str = "woocommerce",
    base_url: str,
    job_id: str | None = None,
    workflow_trace_id: str | None = None,
) -> UploadPackage:
    """门禁必须已通过（调用方先查 gate_blockers）。"""
    mcj = product.marketing_copy_json or {}
    desc = build_description_html(mcj)
    bullets = [
        str(b).strip()
        for b in (
            ((mcj.get("product_page_copy") or {}).get("key_bullets") or [])
            if isinstance(mcj, dict)
            else []
        )
        if str(b).strip()
    ]
    currency = (product.price_currency or "USD")[:3]
    return UploadPackage(
        schema_version=UPLOAD_PACKAGE_SCHEMA_VERSION,
        job_id=job_id,
        product_id=product.id,
        workflow_trace_id=workflow_trace_id,
        channel="woocommerce",
        generated_at=datetime.now(UTC),
        gate=Gate(ready=True, blockers=[]),
        product=Product(
            sku=product.sku,
            title=(product.product_name_en or product.product_key),
            brand=product.brand_name,
            product_type=product.product_type,
            gtin=getattr(product, "gtin", None),
            mpn=getattr(product, "mpn", None),
            condition="new",
            description=Description(
                html=desc["html"],
                text=plain_text_from_copy(mcj),
                bullets=bullets,
                layout_skill_version=LAYOUT_SKILL_VERSION,
                category_block=desc["sections_emitted"][-1]
                if desc["sections_emitted"]
                else None,
            ),
            price=Price(
                regular=Decimal(str(product.regular_price)),
                sale=(
                    Decimal(str(product.sale_price))
                    if product.sale_price is not None
                    else None
                ),
                currency=currency,
            ),
            stock=Stock(
                status=_availability(product.stock_status),
                qty=product.inventory_quantity,
            ),
            category=Category(
                slug=getattr(product, "slug", None),
                google_product_category=product.google_product_category,
                merchant_product_type=product.merchant_product_type,
            ),
            images=_images(db, product, base_url),
            keywords=Keywords(
                primary=[product.primary_keyword] if product.primary_keyword else [],
            ),
            seo=Seo(
                title=getattr(product, "seo_title_en", None),
                description=getattr(product, "seo_description_en", None),
            ),
            variants=_variants(db, product),
            item_group_id=product.product_key,
        ),
    )
