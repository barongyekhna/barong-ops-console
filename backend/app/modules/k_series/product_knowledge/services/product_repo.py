"""产品仓储：按引用取产品、读取投影、建品幂等、就绪度判定。

从 router 剥出来的第 5 桶（2026-09-03）。

⚠️ 建品幂等那几支（`_claim/_complete/_discard/_cleanup_product_create_idempotency`
配 `_product_create_fingerprint`）依赖模块级的 `Lock` 和 dict —— **搬家后必须
仍然是单例**。它们挡的是「用户连点两下建品按钮」，进程内共享一份状态才有意义。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

import hashlib
import json

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from threading import Lock
from time import monotonic
from typing import Any
from uuid import UUID, uuid4
from ..constants import MODULE_KEY, TARGET_ORGANIZATION_NAME
from ..errors import KConflictError, KProductKnowledgeError, KProductNotFoundError
from ..models import (
    KProductKnowledgeAttribute,
    KProductKnowledgeKeyword,
    KProductKnowledgeProduct,
    KProductKnowledgeRiskTerm,
    KProductKnowledgeVariant,
)
from ..schemas import ProductKnowledgeRead, ProductKnowledgeVariantRead
from ..scope_shim import apply_scope_filters
from ..service import get_product
from ..services.api_support import _structured_execution_error_detail
from ..services.common import _product_ai_warnings, _stable_payload_digest
from ..services.media_service import _active_media_snapshot
from ..services.selling_points_service import _selling_points_snapshot
from ..sku_allocator import ensure_product_sku

# ---------------------------------------------------------------------------
# 建品幂等的进程内状态
# ---------------------------------------------------------------------------
#
# ⚠️ **必须是单例。** 这把锁和这张表挡的是「用户连点两下建品按钮」——
# 进程内共享一份状态才有意义。2026-09-03 从 router 搬过来时原样保留；
# 如果哪天这个模块被 import 成两份（比如出现同名的第二个模块路径），
# 这道闸会静默失效：两次点击各拿各的锁，双双通过。
PRODUCT_CREATE_IDEMPOTENCY_TTL_SECONDS = 20.0


@dataclass
class ProductCreateIdempotencyRecord:
    fingerprint: str
    lock: Lock
    expires_at: float
    product_id: UUID | None = None


_product_create_idempotency_lock = Lock()
_product_create_idempotency_records: dict[
    str,
    ProductCreateIdempotencyRecord,
] = {}

class ProductSectionState(BaseModel):
    submitted: bool
    dirty: bool = False
    status: Literal["submitted", "pending", "dirty", "blocked"] = "pending"
    reason: str | None = None
    current_digest: str | None = None
    submitted_digest: str | None = None
    count: int = 0
    submitted_at: str | None = None


class ProductReadinessResponse(BaseModel):
    ready: bool
    keywords: ProductSectionState
    images: ProductSectionState
    selling_points: ProductSectionState


def _canonical_payload(value: Any) -> str:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _product_create_fingerprint(
    payload: ProductKnowledgeCreate,
    scope_context: KScopeContext,
) -> str:
    body = {
        "business_context": scope_context.business_context,
        "payload": payload.model_dump(mode="json"),
        "scope_mode": scope_context.scope_mode,
        "workspace_key": scope_context.workspace_key,
    }
    return hashlib.sha256(_canonical_payload(body).encode("utf-8")).hexdigest()


def _cleanup_product_create_idempotency(now: float) -> None:
    expired_keys = [
        key
        for key, record in _product_create_idempotency_records.items()
        if record.expires_at <= now and not record.lock.locked()
    ]
    for key in expired_keys:
        _product_create_idempotency_records.pop(key, None)


def _claim_product_create_idempotency(
    *,
    cache_key: str,
    fingerprint: str,
) -> ProductCreateIdempotencyRecord:
    now = monotonic()
    with _product_create_idempotency_lock:
        _cleanup_product_create_idempotency(now)
        record = _product_create_idempotency_records.get(cache_key)
        if record is None:
            record = ProductCreateIdempotencyRecord(
                fingerprint=fingerprint,
                lock=Lock(),
                expires_at=now + PRODUCT_CREATE_IDEMPOTENCY_TTL_SECONDS,
            )
            record.lock.acquire()
            _product_create_idempotency_records[cache_key] = record
            return record
        if record.fingerprint != fingerprint:
            raise KConflictError(
                "Idempotency key was reused for a different product payload."
            )

    record.lock.acquire()
    return record


def _complete_product_create_idempotency(
    *,
    cache_key: str,
    record: ProductCreateIdempotencyRecord,
    product_id: UUID,
) -> None:
    with _product_create_idempotency_lock:
        record.product_id = product_id
        record.expires_at = monotonic() + PRODUCT_CREATE_IDEMPOTENCY_TTL_SECONDS
        _product_create_idempotency_records[cache_key] = record


def _discard_product_create_idempotency(
    *,
    cache_key: str,
    record: ProductCreateIdempotencyRecord,
) -> None:
    with _product_create_idempotency_lock:
        if _product_create_idempotency_records.get(cache_key) is record:
            _product_create_idempotency_records.pop(cache_key, None)


def _product_variants(
    db: Session,
    product: KProductKnowledgeProduct,
) -> list[KProductKnowledgeVariant]:
    return list(
        db.scalars(
            select(KProductKnowledgeVariant)
            .where(KProductKnowledgeVariant.product_id == product.id)
            .order_by(KProductKnowledgeVariant.created_at.asc())
        )
    )


def _product_read(
    db: Session,
    product: KProductKnowledgeProduct,
) -> ProductKnowledgeRead:
    variants = _product_variants(db, product)
    return ProductKnowledgeRead.model_validate(product).model_copy(
        update={
            "main_keyword": product.primary_keyword,
            "shipping_class": product.shipping_class,
            "shipping_review_needed": product.shipping_review_needed,
            "shipping_assignment": (
                product.shipping_assignment_json
                if isinstance(product.shipping_assignment_json, dict)
                else None
            ),
            "contains_battery": product.contains_battery,
            "variant_count": len(variants),
            "variants": [
                ProductKnowledgeVariantRead.model_validate(variant)
                for variant in variants
            ],
        }
    )


def _count_products(
    db: Session,
    *,
    scope_context: KScopeContext,
    status_filter: str | None,
    review_status: str | None,
    q: str | None,
) -> int:
    query = apply_scope_filters(
        select(func.count()).select_from(KProductKnowledgeProduct),
        KProductKnowledgeProduct,
        scope_context,
    )
    if status_filter is not None:
        query = query.where(KProductKnowledgeProduct.product_status == status_filter)
    if review_status is not None:
        query = query.where(KProductKnowledgeProduct.review_status == review_status)
    if q is not None and q.strip():
        term = f"%{q.strip()}%"
        query = query.where(
            KProductKnowledgeProduct.product_key.ilike(term)
            | KProductKnowledgeProduct.sku.ilike(term)
            | KProductKnowledgeProduct.parent_sku.ilike(term)
            | KProductKnowledgeProduct.source_record_id.ilike(term)
            | KProductKnowledgeProduct.primary_keyword.ilike(term)
            | KProductKnowledgeProduct.product_name_en.ilike(term)
            | KProductKnowledgeProduct.brand_name.ilike(term)
        )
    return int(db.scalar(query) or 0)


def _product_by_ref(
    db: Session,
    *,
    product_ref: str,
    scope_context: KScopeContext,
    create_shell: bool = False,
) -> KProductKnowledgeProduct:
    normalized = product_ref.strip()
    if not normalized:
        raise KProductNotFoundError("K product reference is required.")
    try:
        return get_product(
            db,
            product_id=UUID(normalized),
            scope_context=scope_context,
        )
    except (ValueError, KProductKnowledgeError):
        pass

    query = apply_scope_filters(
        select(KProductKnowledgeProduct).where(
            (KProductKnowledgeProduct.product_key == normalized)
            | (KProductKnowledgeProduct.parent_sku == normalized)
            | (KProductKnowledgeProduct.sku == normalized)
            | (KProductKnowledgeProduct.source_record_id == normalized),
        ),
        KProductKnowledgeProduct,
        scope_context,
    )
    product = db.scalar(query)
    if product is not None:
        return product
    if not create_shell:
        raise KProductNotFoundError(f"K product '{normalized}' was not found.")

    product_key = _router_unique_product_key(db)
    product = KProductKnowledgeProduct(
        id=uuid4(),
        workspace_key=scope_context.workspace_key,
        business_context=scope_context.business_context,
        scope_mode=scope_context.scope_mode,
        organization_name=TARGET_ORGANIZATION_NAME,
        product_key=product_key,
        source_record_id=normalized,
        product_status="draft",
        product_type="simple_product",
        review_status="draft",
        canonical_language="en",
        raw_input_text=f"Runtime shell for {normalized}",
        raw_input_language="en",
        source_system="k_adapter",
    )
    db.add(product)
    issued_sku = ensure_product_sku(db, product, force_allocate=True)
    default_variant_sku = f"{issued_sku}-SHELL"
    db.add(
        KProductKnowledgeVariant(
            id=uuid4(),
            product_id=product.id,
            parent_sku=issued_sku,
            variant_sku=default_variant_sku,
            variant_hash="SHELL",
            attributes_json={"default_variant": True, "shell_product": True},
            image_folder=f"images/{product.product_key}/{default_variant_sku}",
        )
    )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise KConflictError() from exc
    return product


def _router_unique_product_key(db: Session) -> str:
    for _ in range(3):
        product_key = str(uuid4())
        exists = db.scalar(
            select(KProductKnowledgeProduct.id)
            .where(KProductKnowledgeProduct.product_key == product_key)
            .limit(1)
        )
        if exists is None:
            return product_key
    raise KConflictError("Product creation conflicted; retry or check SKU data.")


def _variant_by_sku(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    variant_sku: str | None,
) -> KProductKnowledgeVariant:
    normalized = (variant_sku or product.parent_sku or product.sku or "").strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="variant_sku is required for image operations.",
        )
    variant = db.scalar(
        select(KProductKnowledgeVariant)
        .where(
            KProductKnowledgeVariant.product_id == product.id,
            KProductKnowledgeVariant.variant_sku == normalized,
        )
        .limit(1)
    )
    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant SKU was not found for this product.",
        )
    return variant


def _product_full_ai_payload(
    db: Session,
    product: KProductKnowledgeProduct,
) -> dict[str, Any]:
    variants = [
        ProductKnowledgeVariantRead.model_validate(variant).model_dump(mode="json")
        for variant in _product_variants(db, product)
    ]
    # 多变体产品的物理规格藏在 attributes_json.physical(2026-07-22 变体改造):
    # 提到每个变体第一层,文案/卖点 AI 才看得见;否则自检误报"缺尺寸重量"。
    for entry in variants:
        raw_attrs = entry.get("attributes_json")
        physical = raw_attrs.get("physical") if isinstance(raw_attrs, dict) else None
        if isinstance(physical, dict):
            if entry.get("dimensions") is None:
                entry["dimensions"] = physical.get("dimensions")
            if entry.get("weight") is None:
                entry["weight"] = physical.get("weight")
    variant_dimensions = [
        {"variant_sku": entry.get("variant_sku"), **entry["dimensions"]}
        for entry in variants
        if isinstance(entry.get("dimensions"), dict)
    ]
    variant_weights = [
        {"variant_sku": entry.get("variant_sku"), **entry["weight"]}
        for entry in variants
        if isinstance(entry.get("weight"), dict)
    ]
    attributes = [
        {
            "id": str(row.id),
            "attribute_key": row.attribute_key,
            "attribute_value_text": row.attribute_value_text,
            "attribute_value_json": row.attribute_value_json,
            "attribute_unit": row.attribute_unit,
            "attribute_group": row.attribute_group,
            "source": row.source,
            "requires_review": row.requires_review,
            "reviewed_by_user_id": (
                str(row.reviewed_by_user_id) if row.reviewed_by_user_id else None
            ),
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        }
        for row in db.scalars(
            select(KProductKnowledgeAttribute)
            .where(KProductKnowledgeAttribute.product_id == product.id)
            .order_by(KProductKnowledgeAttribute.created_at.asc())
        )
    ]
    keywords = [
        {
            "keyword": row.keyword_text,
            "keyword_type": row.keyword_type,
            "status": row.status,
            "market": row.market,
            "source": row.source,
        }
        for row in db.scalars(
            select(KProductKnowledgeKeyword)
            .where(KProductKnowledgeKeyword.product_id == product.id)
            .order_by(KProductKnowledgeKeyword.created_at.asc())
        )
    ]
    risk_terms = [
        {
            "term": row.term_en,
            "status": row.status,
            "risk_type": row.risk_type,
            "risk_reason": row.risk_reason,
        }
        for row in db.scalars(
            select(KProductKnowledgeRiskTerm)
            .where(KProductKnowledgeRiskTerm.product_id == product.id)
            .order_by(KProductKnowledgeRiskTerm.created_at.asc())
        )
    ]
    return {
        "product_id": str(product.id),
        "product_key": product.product_key,
        "sku": product.sku,
        "parent_sku": product.parent_sku,
        "name": product.product_name_en,
        "title": product.product_name_en,
        "brand_name": product.brand_name,
        "manufacturer": product.manufacturer,
        "product_type": product.product_type,
        "market": product.target_market,
        "target_market": product.target_market,
        "target_language": product.canonical_language,
        "main_keyword": product.primary_keyword,
        "description": product.long_description_en or product.short_description_en,
        "short_description": product.short_description_en,
        "long_description": product.long_description_en,
        "structured_specs_json": product.structured_specs_json,
        "package_includes": product.package_includes_json,
        "attributes": attributes,
        "variants": variants,
        "keywords": keywords,
        "risk_terms": risk_terms,
        "dimensions": (
            product.dimensions_json
            if product.dimensions_json is not None
            else (
                {"per_variant": variant_dimensions} if variant_dimensions else None
            )
        ),
        "weight": (
            product.weight_json
            if product.weight_json is not None
            else ({"per_variant": variant_weights} if variant_weights else None)
        ),
        "price": {
            "regular_price": str(product.regular_price)
            if product.regular_price is not None
            else None,
            "currency": product.price_currency,
            # 多变体产品价格在变体上;逐变体给出,AI 不再报"价格缺失"
            "variant_prices": [
                {
                    "variant_sku": entry.get("variant_sku"),
                    "price": entry.get("price_override"),
                }
                for entry in variants
                if entry.get("price_override") is not None
            ],
        },
    }


def _active_keyword_snapshot(
    db: Session,
    product: KProductKnowledgeProduct,
) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(KProductKnowledgeKeyword)
            .where(
                KProductKnowledgeKeyword.product_id == product.id,
                ~KProductKnowledgeKeyword.status.in_(("removed", "rejected")),
            )
            .order_by(
                KProductKnowledgeKeyword.keyword_text.asc(),
                KProductKnowledgeKeyword.keyword_type.asc(),
                KProductKnowledgeKeyword.source.asc(),
            )
        )
    )
    items = [
        {
            "keyword": row.keyword_text.strip().lower(),
            "keyword_type": row.keyword_type,
            "language_code": row.language_code,
            "market": row.market,
            "source": row.source,
            "status": row.status,
        }
        for row in rows
        if row.keyword_text and row.keyword_text.strip()
    ]
    payload = {"count": len(items), "items": items}
    return {**payload, "digest": _stable_payload_digest(payload)}


def _section_state_from_marker(
    marker: Any,
    snapshot: dict[str, Any],
    *,
    digest_key: str,
    min_count: int,
    missing_reason: str,
    count_reason: str,
    submitted_statuses: set[str],
) -> ProductSectionState:
    current_digest = str(snapshot.get("digest") or "")
    count = int(snapshot.get("count") or 0)
    if count < min_count:
        return ProductSectionState(
            submitted=False,
            dirty=False,
            status="blocked",
            reason=count_reason,
            current_digest=current_digest,
            count=count,
        )

    if not isinstance(marker, dict):
        return ProductSectionState(
            submitted=False,
            dirty=False,
            status="pending",
            reason=missing_reason,
            current_digest=current_digest,
            count=count,
        )

    submitted_digest = str(marker.get(digest_key) or marker.get("digest") or "")
    marker_status = str(marker.get("status") or "")
    submitted_at = (
        str(marker.get("submitted_at") or marker.get("approved_at"))
        if marker.get("submitted_at") or marker.get("approved_at")
        else None
    )
    if marker_status not in submitted_statuses or not submitted_digest:
        return ProductSectionState(
            submitted=False,
            dirty=False,
            status="pending",
            reason=missing_reason,
            current_digest=current_digest,
            submitted_digest=submitted_digest or None,
            count=count,
            submitted_at=submitted_at,
        )
    if submitted_digest != current_digest:
        return ProductSectionState(
            submitted=False,
            dirty=True,
            status="dirty",
            reason="板块内容已修改，需要重新提交。",
            current_digest=current_digest,
            submitted_digest=submitted_digest,
            count=count,
            submitted_at=submitted_at,
        )

    return ProductSectionState(
        submitted=True,
        dirty=False,
        status="submitted",
        current_digest=current_digest,
        submitted_digest=submitted_digest,
        count=count,
        submitted_at=submitted_at,
    )


def _product_readiness(
    db: Session,
    product: KProductKnowledgeProduct,
) -> ProductReadinessResponse:
    warnings = _product_ai_warnings(product)
    keywords = _section_state_from_marker(
        warnings.get("keyword_review"),
        _active_keyword_snapshot(db, product),
        digest_key="keyword_digest",
        min_count=1,
        missing_reason="关键词尚未提交。",
        count_reason="请至少保留一个非风险关键词。",
        submitted_statuses={"submitted", "approved"},
    )
    images = _section_state_from_marker(
        warnings.get("image_review"),
        _active_media_snapshot(db, product),
        digest_key="media_digest",
        min_count=5,
        missing_reason="图片尚未提交。",
        count_reason="请至少提交 5 张图片。",
        submitted_statuses={"submitted", "approved"},
    )
    selling_points = _section_state_from_marker(
        warnings.get("selling_points_review"),
        _selling_points_snapshot(product),
        digest_key="selling_points_digest",
        min_count=1,
        missing_reason="卖点尚未提交。",
        count_reason="请先生成并提交卖点。",
        submitted_statuses={"submitted", "approved"},
    )
    return ProductReadinessResponse(
        ready=keywords.submitted and images.submitted and selling_points.submitted,
        keywords=keywords,
        images=images,
        selling_points=selling_points,
    )


def _ensure_product_ready_for_approval(
    db: Session,
    product: KProductKnowledgeProduct,
) -> None:
    readiness = _product_readiness(db, product)
    if readiness.ready:
        return
    blockers = {
        "keywords": readiness.keywords.model_dump(mode="json"),
        "images": readiness.images.model_dump(mode="json"),
        "selling_points": readiness.selling_points.model_dump(mode="json"),
    }
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_structured_execution_error_detail(
            reason="invalid_state",
            code="PRODUCT_SECTIONS_NOT_SUBMITTED",
            message=(
                "Product info can only be saved after keywords, images, and "
                "selling points are submitted without later modifications."
            ),
            module_id=MODULE_KEY,
            extra={"sections": blockers},
        ),
    )
