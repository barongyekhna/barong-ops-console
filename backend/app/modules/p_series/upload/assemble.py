"""K 产品 → UploadPackage（P 取数的核心）。

门禁没过就不组装（端点转 409 + blockers）；过了才构造完整包，此时 required
字段齐全。所有内容来自 K；description_html 由 layout skill 拼装；GMC 关键字段
（title/price/availability/image）与包同源，天然一致。
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..contract.upload_package import (
    UPLOAD_PACKAGE_SCHEMA_VERSION,
    Category,
    Description,
    FaqItem,
    Gate,
    ImageAsset,
    Keywords,
    Price,
    Product,
    Seo,
    Shipping,
    Stock,
    UploadPackage,
    Variant,
)
from ...k_series.product_knowledge.brand_guard import (
    SITE_BRAND,
    audit_gate_blockers,
)
from ...k_series.product_knowledge.buyer_display import (
    buyer_english_text,
    buyer_safe_tree,
    contains_cjk,
    imperialize_text,
    normalize_package_includes,
)
from ...k_series.product_knowledge.category_resolver import (
    category_is_bound,
    google_category_path,
    repair_legacy_google_category_path,
)
from ...k_series.product_knowledge.faq_research import faq_schema_is_eligible
from ...k_series.product_knowledge.evidence_guard import (
    canonical_package_includes,
    enforce_package_evidence_consistency,
)
from ...k_series.product_knowledge.models import KProductKnowledgeMediaAsset
from ...k_series.product_knowledge.sku_allocator import ensure_product_sku
from .description_html import (
    build_description_html,
    plain_text_from_copy,
)
from .product_schema import project_verified_product_specs
from .wc_categories import ensure_wc_category_path

LAYOUT_SKILL_VERSION = "p-product-page-layout-v1"
logger = logging.getLogger(__name__)
_SLUG_STOPWORDS = {"a", "an", "and", "for", "of", "or", "the", "to", "with"}


def _stable_hash(value: Any, *, compact: bool = False) -> str:
    kwargs: dict[str, Any] = {
        "sort_keys": True,
        "default": str,
    }
    if compact:
        kwargs.update({"ensure_ascii": False, "separators": (",", ":")})
    return hashlib.sha256(json.dumps(value, **kwargs).encode("utf-8")).hexdigest()


def _approved_evidence_points(product: Any) -> list[dict[str, Any]]:
    payload = getattr(product, "selling_points_approved_json", None)
    if not isinstance(payload, dict) or payload.get("review_status") != "approved":
        return []
    raw_bullets = payload.get("bullets")
    if not isinstance(raw_bullets, list):
        return []
    points: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_bullets, start=1):
        if not isinstance(raw, dict):
            return []
        point = dict(raw)
        point_id = str(point.get("id") or f"sp-{index}").strip()
        evidence = str(point.get("evidence") or "").strip()
        snapshot = point.get("evidence_snapshot")
        snapshot_digest = str(point.get("evidence_digest") or "").strip()
        if (
            not point_id
            or point_id in seen_ids
            or not str(point.get("text") or "").strip()
            or point.get("verification_status") != "verified"
            or not (
                evidence == "operator_fact"
                or evidence.startswith("spec:")
                or evidence.startswith("verified_feature:")
            )
            or not isinstance(snapshot, dict)
            or snapshot_digest != _stable_hash(snapshot, compact=True)
        ):
            return []
        seen_ids.add(point_id)
        point["id"] = point_id
        point["text"] = str(point["text"]).strip()
        points.append(point)
    return points


def _evidence_gate_blockers(product: Any) -> list[str]:
    points = _approved_evidence_points(product)
    if not points:
        return ["卖点未通过逐条证据审批"]
    copy = getattr(product, "marketing_copy_json", None)
    if not isinstance(copy, dict) or copy.get("evidence_contract") != "pdp-evidence-v1":
        return ["文案缺少证据契约，请从已审卖点重新生成"]
    evidence_payload = {
        "selling_points_approved": points,
        "structured_specs_json": getattr(product, "structured_specs_json", None),
    }
    package_includes = canonical_package_includes(
        getattr(product, "package_includes_json", None),
        getattr(product, "structured_specs_json", None),
    )
    if package_includes:
        evidence_payload["package_includes"] = package_includes
    expected = _stable_hash(evidence_payload)
    if str(copy.get("evidence_digest") or "") != expected:
        return ["卖点或规格已变化，文案证据快照过期"]
    return []


def _title_for_upload(marketing_copy_json: Any, product: Any) -> str:
    seo = (
        marketing_copy_json.get("seo")
        if isinstance(marketing_copy_json, dict)
        and isinstance(marketing_copy_json.get("seo"), dict)
        else {}
    )
    value = (
        _optional_text(seo.get("h1"))
        or _optional_text(seo.get("title"))
        or _optional_text(getattr(product, "product_name_en", None))
        or str(getattr(product, "product_key", "Product"))
    )
    safe = imperialize_text(" ".join(html.unescape(value).split()))
    return safe or "Product"


def _rollback_category_failure(db: Session) -> None:
    """Clear a failed category/cache transaction without breaking packaging."""
    try:
        db.rollback()
    except Exception:  # noqa: BLE001 - even rollback failure must stay fail-safe
        logger.exception(
            "Woo category transaction rollback failed; upload still continues"
        )


def gate_blockers(db: Session, product: Any) -> list[str]:
    """进 P 的硬门禁（契约：关键词+卖点+文案+图片，加类目+价格+标题）。"""
    blockers: list[str] = []
    if not (getattr(product, "product_name_en", None) or "").strip():
        blockers.append("标题缺失（product_name_en）")
    if not getattr(product, "marketing_copy_json", None):
        blockers.append("文案未生成（含卖点/关键词）")
    blockers.extend(_evidence_gate_blockers(product))
    if not _has_bound_image(db, product):
        blockers.append("未绑定图片")
    if not category_is_bound(product):
        blockers.append("未绑定类目")
    if getattr(product, "regular_price", None) is None:
        blockers.append("价格缺失")
    if (getattr(product, "channel", "") or "").strip().lower() == "dtc" and not (
        getattr(product, "shipping_class", None) or ""
    ).strip():
        blockers.append("运费模板未分配（去 W-S 物流网络中枢处理）")
    # 品牌硬门（fail-closed）：审查必须存在、通过、且内容未变
    blockers.extend(audit_gate_blockers(db, product))
    return blockers


def _has_bound_image(db: Session, product: Any) -> bool:
    if (getattr(product, "image_asset_status", None) or "") == "bound":
        return True
    if getattr(product, "selected_image_path", None):
        return True
    asset_id = db.scalar(
        select(KProductKnowledgeMediaAsset.id)
        .where(
            KProductKnowledgeMediaAsset.product_id == product.id,
            KProductKnowledgeMediaAsset.status == "bound",
        )
        .limit(1)
    )
    return asset_id is not None


def _availability(stock_status: str | None) -> str:
    s = (stock_status or "").lower()
    if "out" in s or s == "0":
        return "out_of_stock"
    if "pre" in s:
        return "preorder"
    return "in_stock"


def _optional_text(value: Any) -> str | None:
    """Return non-empty generated text without coercing malformed AI output."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _short_url_slug(value: Any) -> str | None:
    authored = _optional_text(value)
    if not authored:
        return None
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", html.unescape(authored).casefold())
        if word not in _SLUG_STOPWORDS
    ]
    if not words:
        return None
    # Never fall back to the long H1. If a provider violates the 3-5-word
    # contract, deterministically keep only its first five authored words.
    return "-".join(words[:5])


def _seo_for_upload(marketing_copy_json: Any, product: Any) -> Seo:
    """Project K's generated SEO copy into the P upload contract.

    The marketing-copy result is where the K generator writes ``seo.title`` and
    ``seo.meta_description``.  Older rows may instead have the dedicated K SEO
    columns populated, so those remain a compatibility fallback.  Description
    HTML is deliberately not consulted: Woo/Yoast must receive the authored
    meta description, never text produced by stripping markup.
    """
    generated_seo: dict[str, Any] = {}
    if isinstance(marketing_copy_json, dict):
        candidate = marketing_copy_json.get("seo")
        if isinstance(candidate, dict):
            generated_seo = candidate

    title = (
            _optional_text(generated_seo.get("title"))
            or _optional_text(getattr(product, "seo_title_en", None))
        )
    description = (
            _optional_text(generated_seo.get("meta_description"))
            or _optional_text(generated_seo.get("description"))
            or _optional_text(getattr(product, "seo_description_en", None))
        )
    return Seo(
        title=imperialize_text(title) if title else None,
        description=imperialize_text(description) if description else None,
        # Deliberately no product.slug / H1-derived fallback: a missing K slug
        # is safer than silently publishing the old 15-word permalink again.
        url_slug=_short_url_slug(generated_seo.get("url_slug")),
    )


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
            overlay = meta.get("overlay")
            overlay_role = (
                str(overlay.get("role") or "").strip().lower()
                if isinstance(overlay, dict)
                else ""
            )
            role_label = str(meta.get("role_label") or "").strip()
            is_dimension = role_label.lower() in {"dimension", "尺寸图"} or overlay_role == "dimension"
            placement = (
                "description"
                if (meta.get("placement") == "description" and not is_dimension)
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
                    role=imperialize_text(role_label) if role_label else None,
                    filename=buyer_english_text(
                        str(meta.get("filename") or ""), limit=255
                    ),
                    mime_type=r["mime_type"],
                    title=imperialize_text(str(meta.get("title") or "")),
                    alt=imperialize_text(str(meta.get("alt") or "")),
                    caption=imperialize_text(str(meta.get("caption") or "")),
                    description=imperialize_text(
                        str(meta.get("description") or "")
                    ),
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
                color=imperialize_text(r["color"]) if r["color"] else None,
                size=imperialize_text(r["size"]) if r["size"] else None,
                function=(
                    imperialize_text(r["function"]) if r["function"] else None
                ),
                price=price,
            )
        )
    return out


def _resolve_wc_category(
    db: Session,
    product: Any,
) -> tuple[list[str] | None, int | None]:
    """Resolve and ensure the buyer-facing Woo category without blocking upload."""
    raw_google_id = getattr(product, "google_product_category", None)
    google_id = str(raw_google_id).strip() if raw_google_id is not None else ""
    if not google_id:
        logger.warning(
            "Woo category skipped: google_product_category missing product_id=%s",
            getattr(product, "id", None),
        )
        return None, None

    try:
        if not google_id.isascii() or not google_id.isdecimal():
            if repair_legacy_google_category_path(db, product):
                google_id = str(product.google_product_category)
        resolved_path = google_category_path(db, google_id)
        category_path: list[str] = []
        for segment in resolved_path:
            name = str(segment["name"] or "").strip()
            if not name:
                raise ValueError("Google category path contains an empty name")
            category_path.append(name)
        if not category_path:
            raise ValueError("Google category path is empty")
    except Exception:  # noqa: BLE001 - category enrichment must never block upload
        logger.exception(
            "Google category path resolution failed product_id=%s google_id=%s; "
            "upload continues uncategorized",
            getattr(product, "id", None),
            google_id,
        )
        _rollback_category_failure(db)
        return None, None

    try:
        wc_category_id = ensure_wc_category_path(db, resolved_path)
        if (
            isinstance(wc_category_id, bool)
            or not isinstance(wc_category_id, int)
            or wc_category_id <= 0
        ):
            raise ValueError("Woo category id must be a positive integer")
    except Exception:  # noqa: BLE001 - category enrichment must never block upload
        logger.exception(
            "Woo category ensure failed product_id=%s google_id=%s; "
            "upload continues uncategorized",
            getattr(product, "id", None),
            google_id,
        )
        _rollback_category_failure(db)
        return category_path, None

    return category_path, wc_category_id


def _deterministic_specifications_table(attributes: list[Any]) -> str | None:
    """Build the public spec table only from the verified P projection."""

    rows: list[str] = []
    for item in attributes:
        name = buyer_english_text(getattr(item, "name", None), limit=120)
        value = imperialize_text(getattr(item, "value", None))
        unit = buyer_english_text(getattr(item, "unit", None), limit=40)
        if not name or not value or name.casefold() == "what's included":
            continue
        rendered = f"{value} {unit}" if unit else value
        rows.append(
            "<tr><th scope=\"row\">"
            + html.escape(name)
            + "</th><td>"
            + html.escape(rendered)
            + "</td></tr>"
        )
    if not rows:
        return None
    return "<table><tbody>" + "".join(rows) + "</tbody></table>"


def _project_buyer_copy(
    marketing_copy: dict[str, Any],
    *,
    attributes: list[Any],
) -> dict[str, Any]:
    """Strip CJK/metric leakage and replace the AI-authored spec table."""

    projected = buyer_safe_tree(marketing_copy, field_path="marketing_copy")
    output = projected if isinstance(projected, dict) else {}
    if contains_cjk(json.dumps(marketing_copy, ensure_ascii=False, default=str)):
        logger.warning("CJK buyer-facing copy was removed during P assembly")
    raw_ppc = output.get("product_page_copy")
    ppc = dict(raw_ppc) if isinstance(raw_ppc, dict) else {}
    table = _deterministic_specifications_table(attributes)
    if table:
        ppc["specifications_html_table"] = table
    else:
        ppc.pop("specifications_html_table", None)
    output["product_page_copy"] = ppc
    return output


def _append_package_includes_section(
    description_html: str,
    package_includes: list[str],
) -> str:
    if not package_includes:
        return description_html
    # K copy may already own this conversion section as a reviewed H2.  The P
    # template must not append a second, mechanically generated copy below it.
    headings = re.findall(
        r"<h[1-6]\b[^>]*>(.*?)</h[1-6]\s*>",
        description_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for heading_html in headings:
        heading = html.unescape(re.sub(r"<[^>]+>", " ", heading_html))
        heading = re.sub(r"\s+", " ", heading).strip().casefold()
        if re.search(r"\bwhat(?:'|’)?s\s+in\s+the\s+box\b", heading):
            return description_html
    items = "".join(
        f"<li>{html.escape(item)}</li>" for item in package_includes
    )
    section = (
        '<section class="kp-box"><h2>What\'s in the box</h2>'
        f"<ul>{items}</ul></section>"
    )
    closing = description_html.rfind("</div>")
    if closing < 0:
        return description_html + section
    return description_html[:closing] + section + description_html[closing:]


def assemble_upload_package(
    db: Session,
    product: Any,
    *,
    channel: str = "woocommerce",
    base_url: str,
    job_id: str | None = None,
    job_token: str | None = None,
    workflow_trace_id: str | None = None,
    woo_existing_product_id: str | None = None,
) -> UploadPackage:
    """门禁必须已通过（调用方先查 gate_blockers）。"""
    sku_before_allocation = str(getattr(product, "sku", None) or "").strip()
    raw_mcj = getattr(product, "marketing_copy_json", None)
    # Legacy/malformed copy must degrade to an empty schema verdict instead of
    # making publication fail. Normal K-generated copy is always a dictionary.
    raw_copy = raw_mcj if isinstance(raw_mcj, dict) else {}
    structured_specs = getattr(product, "structured_specs_json", None)
    raw_package_includes = canonical_package_includes(
        getattr(product, "package_includes_json", None),
        structured_specs,
    )
    projected_package = buyer_safe_tree(
        raw_package_includes,
        field_path="package_includes",
    )
    package_includes = normalize_package_includes(
        projected_package if isinstance(projected_package, list) else [],
        reject_cjk=False,
    )
    raw_copy = enforce_package_evidence_consistency(
        raw_copy,
        package_includes=package_includes,
        structured_specs=structured_specs,
    )
    attributes, product_schema = project_verified_product_specs(
        structured_specs,
        package_includes=package_includes,
        target_market=str(getattr(product, "target_market", None) or "US"),
    )
    mcj = _project_buyer_copy(raw_copy, attributes=attributes)
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
    desc["html"] = _append_package_includes_section(
        desc["html"], package_includes
    )
    raw_faq_items = mcj.get("page_faq")
    faq_items = [
        FaqItem(question=str(f.get("question")), answer=str(f.get("answer")))
        for f in (raw_faq_items if isinstance(raw_faq_items, list) else [])
        if isinstance(f, dict)
        and str(f.get("question") or "").strip()
        and str(f.get("answer") or "").strip()
    ]
    raw_ppc = mcj.get("product_page_copy")
    ppc = raw_ppc if isinstance(raw_ppc, dict) else {}
    raw_bullets = ppc.get("key_bullets")
    bullets = [
        str(b).strip()
        for b in (raw_bullets if isinstance(raw_bullets, list) else [])
        if str(b).strip()
    ]
    currency = (product.price_currency or "USD")[:3]
    upload_seo = _seo_for_upload(mcj, product)
    category_path, wc_category_id = _resolve_wc_category(db, product)
    # Category fail-safe handling above may roll back its transaction. Allocate
    # afterwards so a legacy ASIN replacement cannot be undone by that rollback.
    issued_sku = ensure_product_sku(db, product)
    # SKU migration rekeys legacy variants atomically; read them only after the
    # product identifier is final so the package cannot leak ASIN-derived SKUs.
    variants = _variants(db, product)
    return UploadPackage(
        schema_version=UPLOAD_PACKAGE_SCHEMA_VERSION,
        job_id=job_id,
        product_id=product.id,
        woo_existing_product_id=(
            str(woo_existing_product_id).strip()
            if woo_existing_product_id is not None
            and str(woo_existing_product_id).strip()
            else None
        ),
        woo_lookup_sku=sku_before_allocation or issued_sku,
        workflow_trace_id=workflow_trace_id,
        channel="woocommerce",
        generated_at=datetime.now(UTC),
        gate=Gate(ready=True, blockers=[]),
        product=Product(
            sku=product.sku,
            title=_title_for_upload(mcj, product),
            # 死命令：上架包/GMC feed 的品牌永远是站点自有品牌
            brand=SITE_BRAND,
            product_type=product.product_type,
            gtin=getattr(product, "gtin", None),
            mpn=getattr(product, "mpn", None),
            condition="new",
            description=Description(
                # NO <script> in html — WP strips the tag and leaks the JSON as
                # visible text. Schema is injected site-side (Woo filter + meta).
                html=desc["html"],
                text=plain_text_from_copy(mcj),
                bullets=bullets,
                faq=faq_items,
                faq_schema_eligible=faq_schema_is_eligible(mcj),
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
                # Retained in the legacy category slot for older package
                # readers; new consumers read product.seo.url_slug.
                slug=upload_seo.url_slug,
                google_product_category=product.google_product_category,
                merchant_product_type=buyer_english_text(
                    getattr(product, "merchant_product_type", None), limit=512
                ),
                path=[
                    safe
                    for segment in (category_path or [])
                    if (safe := buyer_english_text(segment, limit=255))
                ]
                or None,
                wc_category_id=wc_category_id,
            ),
            images=images,
            attributes=attributes,
            structured_data=product_schema,
            package_includes=package_includes,
            keywords=Keywords(
                primary=(
                    [safe_primary]
                    if (
                        safe_primary := buyer_english_text(
                            getattr(product, "primary_keyword", None), limit=512
                        )
                    )
                    else []
                ),
            ),
            seo=upload_seo,
            variants=variants,
            item_group_id=product.product_key,
        ),
        shipping=Shipping(shipping_class=product.shipping_class),
    )
