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
    ImageAsset,
    Keywords,
    Price,
    Product,
    Seo,
    Stock,
    UploadPackage,
    Variant,
)
from ...k_series.product_knowledge.brand_guard import (
    SITE_BRAND,
    audit_gate_blockers,
)
from ...k_series.product_knowledge.category_resolver import category_is_bound
from .description_html import (
    build_description_html,
    build_schema_jsonld,
    plain_text_from_copy,
)

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
    # 品牌硬门（fail-closed）：审查必须存在、通过、且内容未变
    blockers.extend(audit_gate_blockers(db, product))
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


def _media_fetch_url(
    base_url: str,
    *,
    job_id: str | None,
    job_token: str | None,
    asset_id: str,
) -> str:
    base = base_url.rstrip("/")
    if job_id and job_token:
        # n8n 抓图走 P 的裸路径 + 一单一钥（与取数/回报同一 token）
        return f"{base}/p/jobs/{job_id}/media/{asset_id}/file?token={job_token}"
    return f"{base}/api/app/k/media/{asset_id}/file"


def _image_assets(
    db: Session,
    product: Any,
    base_url: str,
    *,
    job_id: str | None,
    job_token: str | None,
) -> list[ImageAsset]:
    """一次性作图的成品图（带 placement/SEO 四字段）；没有渲染图的老产品
    回退到 bound 媒资（纯 gallery，无 SEO 字段）。"""
    rows = db.execute(
        text(
            "SELECT id, asset_role, mime_type, metadata_json "
            "FROM k_product_knowledge_media_assets "
            "WHERE product_id = :p AND status = 'available' "
            "  AND asset_type = 'image' "
            "  AND metadata_json->>'render_pipeline' = 'k_auto_render' "
            "ORDER BY (metadata_json->>'position')::int ASC"
        ),
        {"p": str(product.id)},
    ).mappings().all()

    out: list[ImageAsset] = []
    if rows:
        for r in rows:
            meta = r["metadata_json"] if isinstance(r["metadata_json"], dict) else {}
            placement = (
                "description"
                if (meta.get("placement") == "description")
                else "gallery"
            )
            position = int(meta.get("position") or 0)
            asset_id = str(r["id"])
            out.append(
                ImageAsset(
                    asset_id=asset_id,
                    url=_media_fetch_url(
                        base_url,
                        job_id=job_id,
                        job_token=job_token,
                        asset_id=asset_id,
                    ),
                    placement=placement,
                    position=position,
                    is_main=(r["asset_role"] == "main"),
                    role=str(meta.get("role_label") or "") or None,
                    filename=str(meta.get("filename") or "") or None,
                    mime_type=r["mime_type"],
                    title=str(meta.get("title") or "") or None,
                    alt=str(meta.get("alt") or "") or None,
                    caption=str(meta.get("caption") or "") or None,
                    description=str(meta.get("description") or "") or None,
                    embed_token=(
                        f"{{{{KP_IMG_{position}}}}}"
                        if placement == "description"
                        else None
                    ),
                )
            )
        # gallery 在前（main 最前），description 图跟在后面
        out.sort(
            key=lambda img: (
                img.placement != "gallery",
                not img.is_main,
                img.position,
            )
        )
        return out

    # 回退：老产品只有 bound 媒资
    legacy = db.execute(
        text(
            "SELECT id, mime_type FROM k_product_knowledge_media_assets "
            "WHERE product_id = :p AND status = 'bound' "
            "ORDER BY updated_at DESC"
        ),
        {"p": str(product.id)},
    ).mappings().all()
    for index, r in enumerate(legacy, start=1):
        asset_id = str(r["id"])
        out.append(
            ImageAsset(
                asset_id=asset_id,
                url=_media_fetch_url(
                    base_url,
                    job_id=job_id,
                    job_token=job_token,
                    asset_id=asset_id,
                ),
                placement="gallery",
                position=index,
                is_main=(index == 1),
                mime_type=r["mime_type"],
            )
        )
    return out


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
    job_token: str | None = None,
    workflow_trace_id: str | None = None,
) -> UploadPackage:
    """门禁必须已通过（调用方先查 gate_blockers）。"""
    mcj = product.marketing_copy_json or {}
    images = _image_assets(
        db, product, base_url, job_id=job_id, job_token=job_token
    )
    description_images = [
        {
            "position": img.position,
            "embed_token": img.embed_token,
            "alt": img.alt,
            "title": img.title,
            "caption": img.caption,
        }
        for img in images
        if img.placement == "description" and img.embed_token
    ]
    desc = build_description_html(mcj, description_images)
    schema_jsonld = build_schema_jsonld(
        mcj,
        price=product.regular_price,
        currency=(product.price_currency or "USD")[:3],
        availability=_availability(product.stock_status),
    )
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
            # 死命令：上架包/GMC feed 的品牌永远是站点自有品牌
            brand=SITE_BRAND,
            product_type=product.product_type,
            gtin=getattr(product, "gtin", None),
            mpn=getattr(product, "mpn", None),
            condition="new",
            description=Description(
                html=desc["html"] + schema_jsonld,
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
            images=images,
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
