"""Service skeleton for the isolated K Product Knowledge module."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .category_resolver import assign_manual_category
from .constants import TARGET_ORGANIZATION_NAME
from .errors import KConflictError, KInvalidStateError, KProductNotFoundError
from .models import (
    KProductKnowledgeAIEvent,
    KProductKnowledgeAttribute,
    KProductKnowledgeKeyword,
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeResearchRun,
    KProductKnowledgeReviewItem,
    KProductKnowledgeRiskTerm,
    KProductKnowledgeTranslation,
    KProductKnowledgeVariant,
    KProductKnowledgeVersion,
    KProductKnowledgeWorkflowExecution,
)
from .schemas import (
    ArchiveProductKnowledgeRequest,
    ProductKnowledgeAttributePatch,
    ProductKnowledgeCreate,
    ProductKnowledgeKeywordPatch,
    ProductKnowledgeRiskTermPatch,
    ProductKnowledgeUpdate,
)
from .scope_shim import KScopeContext, apply_scope_filters, normalize_scope_context
from .sku_allocator import ensure_product_sku
from .spec_templates import refresh_product_spec_completeness

PRODUCT_CREATE_FIELDS = frozenset(
    {
        "raw_input_text",
        "raw_input_language",
        "source_system",
        "source_record_id",
        "target_market",
        "product_status",
        "review_status",
        "canonical_language",
        "product_name_en",
        "brand_name",
        "manufacturer",
        "product_type",
        "regular_price",
        "price_currency",
        "dimensions_json",
        "weight_json",
        "structured_specs_json",
        "package_includes_json",
        "short_description_en",
        "long_description_en",
        "primary_use_case_en",
        "target_customer_en",
        "manual_notes",
    }
)

PRODUCT_UPDATE_FIELDS = frozenset(
    {
        "source_system",
        "source_record_id",
        "target_market",
        "product_status",
        "review_status",
        "canonical_language",
        "raw_input_text",
        "raw_input_language",
        "product_name_en",
        "brand_name",
        "manufacturer",
        "product_type",
        "regular_price",
        "price_currency",
        "dimensions_json",
        "weight_json",
        "structured_specs_json",
        "package_includes_json",
        "short_description_en",
        "long_description_en",
        "primary_use_case_en",
        "target_customer_en",
        "manual_notes",
    }
)

PRODUCT_CREATE_MAX_ATTEMPTS = 3
PRODUCT_CREATE_CONFLICT_MESSAGE = (
    "Product creation conflicted; retry or check SKU and variant data."
)


def list_products(
    db: Session,
    *,
    scope_context: KScopeContext,
    limit: int,
    offset: int,
    status_filter: str | None = None,
    review_status: str | None = None,
    q: str | None = None,
) -> list[KProductKnowledgeProduct]:
    query = apply_scope_filters(
        select(KProductKnowledgeProduct),
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
            or_(
                KProductKnowledgeProduct.product_key.ilike(term),
                KProductKnowledgeProduct.sku.ilike(term),
                KProductKnowledgeProduct.parent_sku.ilike(term),
                KProductKnowledgeProduct.source_record_id.ilike(term),
                KProductKnowledgeProduct.primary_keyword.ilike(term),
                KProductKnowledgeProduct.product_name_en.ilike(term),
                KProductKnowledgeProduct.brand_name.ilike(term),
            )
        )
    query = query.order_by(KProductKnowledgeProduct.created_at.desc())
    return list(db.scalars(query.limit(limit).offset(offset)))


def _apply_manual_category(
    db: Session,
    product: KProductKnowledgeProduct,
    category_id: str | None,
) -> None:
    """手动上传：用户为该 channel 选的类目直接落（下拉来自对应类目树，可信）。"""
    assign_manual_category(db, product, category_id)


def invalidate_evidence_outputs(product: KProductKnowledgeProduct) -> None:
    """Fail closed when a fact source changes beneath approved claims."""

    product.selling_points_candidates_json = None
    product.selling_points_approved_json = None
    product.faq_research_json = None
    product.marketing_copy_json = None
    product.marketing_copy_zh = None
    product.marketing_copy_skill_version = None
    product.image_instruction_json = None
    product.image_instruction_zh = None
    product.image_instruction_skill_version = None

    warnings = (
        product.ai_warnings_json
        if isinstance(product.ai_warnings_json, dict)
        else {}
    )
    product.ai_warnings_json = {
        key: value
        for key, value in warnings.items()
        if key not in {"selling_points", "selling_points_review"}
    }
    deepseek = (
        product.deepseek_structured_output_json
        if isinstance(product.deepseek_structured_output_json, dict)
        else {}
    )
    product.deepseek_structured_output_json = {
        key: value
        for key, value in deepseek.items()
        if key != "selling_points_generation"
    } or None


def create_product(
    db: Session,
    *,
    payload: ProductKnowledgeCreate,
    scope_context: KScopeContext,
) -> KProductKnowledgeProduct:
    context = normalize_scope_context(scope_context)
    product_data = _selected_model_dump(payload, PRODUCT_CREATE_FIELDS)
    target_locale = (
        payload.target_locale
        or payload.canonical_language
        or payload.raw_input_language
        or "en"
    )
    product_type = payload.product_type or "simple_product"

    for attempt in range(PRODUCT_CREATE_MAX_ATTEMPTS):
        product_key = _generate_unique_product_key(db)
        attempt_data = dict(product_data)
        attempt_data.update(
            {
                "canonical_language": target_locale,
                "primary_keyword": payload.main_keyword,
                "product_key": product_key,
                "product_type": product_type,
                "raw_input_language": target_locale,
                "target_market": payload.target_market,
                "variant_group_key": (
                    product_key if product_type == "variable_product" else None
                ),
            }
        )
        product = KProductKnowledgeProduct(
            id=uuid4(),
            **attempt_data,
            workspace_key=context.workspace_key,
            business_context=context.business_context,
            scope_mode=context.scope_mode,
            organization_name=TARGET_ORGANIZATION_NAME,
        )
        product.channel = (payload.channel or "dtc").strip().lower()
        # 节日风格进运营配置容器(ai_warnings_json 已是事实容器:keyword_review
        # 等都存这)。渲染时按此给场景图/描述图注入节日轻氛围;零迁移。
        if payload.festival_style:
            product.ai_warnings_json = {
                **(product.ai_warnings_json or {}),
                "festival_style": payload.festival_style,
            }
        _apply_manual_category(db, product, payload.category_id)
        # Missing category-template fields are diagnostic only: creation still
        # succeeds and the canonical P gate blocks only when an approved
        # template exists.
        refresh_product_spec_completeness(db, product)
        # User/source-provided SKU values are intentionally ignored.  K owns
        # the public identifier and issues it exactly once from the leaf.
        parent_sku = ensure_product_sku(db, product, force_allocate=True)
        variants = _variant_rows_for_payload(
            db=db,
            product=product,
            parent_sku=parent_sku,
            payload=payload,
        )

        db.add(product)
        for variant in variants:
            db.add(variant)

        try:
            db.flush()
            for item in payload.attributes:
                attribute_data = item.model_dump()
                attribute_data["source"] = attribute_data.get("source") or "operator"
                db.add(
                    KProductKnowledgeAttribute(
                        product_id=product.id,
                        **attribute_data,
                    )
                )
            for item in payload.keywords:
                db.add(
                    KProductKnowledgeKeyword(
                        product_id=product.id,
                        **item.model_dump(),
                    )
                )
            for item in payload.risk_terms:
                db.add(
                    KProductKnowledgeRiskTerm(
                        product_id=product.id,
                        **item.model_dump(),
                    )
                )
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if _sku_exists(db, scope_context=context, sku=parent_sku):
                raise KConflictError("SKU already exists for this workspace.") from exc
            if _variant_skus_exist(db, [variant.variant_sku for variant in variants]):
                raise KConflictError("Variant SKU already exists.") from exc
            if attempt + 1 >= PRODUCT_CREATE_MAX_ATTEMPTS:
                raise KConflictError(PRODUCT_CREATE_CONFLICT_MESSAGE) from exc
            continue

        db.refresh(product)
        return product

    raise KConflictError(PRODUCT_CREATE_CONFLICT_MESSAGE)


def get_product(
    db: Session,
    *,
    product_id: UUID,
    scope_context: KScopeContext,
) -> KProductKnowledgeProduct:
    return _require_scoped_product(db, product_id, scope_context)


def update_product(
    db: Session,
    *,
    product_id: UUID,
    payload: ProductKnowledgeUpdate,
    scope_context: KScopeContext,
) -> KProductKnowledgeProduct:
    product = _require_scoped_product(db, product_id, scope_context)
    if product.product_status == "archived":
        raise KInvalidStateError("Archived K products cannot be updated.")

    if payload.main_keyword is not None:
        product.primary_keyword = payload.main_keyword

    # No-op patches are accepted as idempotent. A changed fact snapshot,
    # however, invalidates every approval/output derived from the old facts.
    updates = _selected_model_dump(
        payload,
        PRODUCT_UPDATE_FIELDS,
        exclude_unset=True,
    )
    facts_changed = (
        "structured_specs_json" in updates
        and product.structured_specs_json != updates["structured_specs_json"]
    ) or (
        "package_includes_json" in updates
        and product.package_includes_json != updates["package_includes_json"]
    )
    if facts_changed:
        invalidate_evidence_outputs(product)
    for field_name, value in updates.items():
        setattr(product, field_name, value)
    if "structured_specs_json" in updates:
        refresh_product_spec_completeness(db, product)

    _commit(db)
    db.refresh(product)
    return product


def archive_product(
    db: Session,
    *,
    product_id: UUID,
    payload: ArchiveProductKnowledgeRequest,
    scope_context: KScopeContext,
) -> KProductKnowledgeProduct:
    del payload
    product = _require_scoped_product(db, product_id, scope_context)
    product.product_status = "archived"
    _commit(db)
    db.refresh(product)
    return product


def delete_product(
    db: Session,
    *,
    product_id: UUID,
    product_key: str,
    scope_context: KScopeContext,
) -> dict[str, int]:
    product = _require_scoped_product(db, product_id, scope_context)
    if product.product_key != product_key:
        raise KConflictError("Product key confirmation did not match.")

    product_ids = [product.id]
    counts = {
        "ai_events": _delete_for_products(db, KProductKnowledgeAIEvent, product_ids),
        "workflow_traces": _delete_for_products(
            db,
            KProductKnowledgeWorkflowExecution,
            product_ids,
        ),
        "media_references": _delete_for_products(
            db,
            KProductKnowledgeMediaAsset,
            product_ids,
        ),
        "review_items": _delete_for_products(
            db,
            KProductKnowledgeReviewItem,
            product_ids,
        ),
        "versions": _delete_for_products(db, KProductKnowledgeVersion, product_ids),
        "translations": _delete_for_products(
            db,
            KProductKnowledgeTranslation,
            product_ids,
        ),
        "attributes": _delete_for_products(
            db,
            KProductKnowledgeAttribute,
            product_ids,
        ),
        "keywords": _delete_for_products(db, KProductKnowledgeKeyword, product_ids),
        "risk_terms": _delete_for_products(
            db,
            KProductKnowledgeRiskTerm,
            product_ids,
        ),
        "research_runs": _delete_for_products(
            db,
            KProductKnowledgeResearchRun,
            product_ids,
        ),
        "variants": _delete_for_products(db, KProductKnowledgeVariant, product_ids),
    }

    db.delete(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise KConflictError("Product delete conflicted; retry later.") from exc

    counts["products"] = 1
    return counts


def get_attributes(
    db: Session,
    *,
    product_id: UUID,
    scope_context: KScopeContext,
    attribute_group: str | None = None,
    requires_review: bool | None = None,
) -> list[KProductKnowledgeAttribute]:
    product = _require_scoped_product(db, product_id, scope_context)
    query = select(KProductKnowledgeAttribute).where(
        KProductKnowledgeAttribute.product_id == product.id
    )
    if attribute_group is not None:
        query = query.where(KProductKnowledgeAttribute.attribute_group == attribute_group)
    if requires_review is not None:
        query = query.where(
            KProductKnowledgeAttribute.requires_review == requires_review
        )
    return list(db.scalars(query.order_by(KProductKnowledgeAttribute.created_at.desc())))


def patch_attributes(
    db: Session,
    *,
    product_id: UUID,
    payload: ProductKnowledgeAttributePatch,
    scope_context: KScopeContext,
) -> list[KProductKnowledgeAttribute]:
    product = _require_scoped_product(db, product_id, scope_context)
    existing = {
        (item.attribute_key, item.attribute_group or ""): item
        for item in db.scalars(
            select(KProductKnowledgeAttribute).where(
                KProductKnowledgeAttribute.product_id == product.id
            )
        )
    }
    evidence_changed = False
    for item in payload.items:
        data = item.model_dump()
        data["source"] = data.get("source") or "operator"
        key = (item.attribute_key, item.attribute_group or "")
        attribute = existing.get(key)
        if attribute is None:
            evidence_changed = True
            db.add(
                KProductKnowledgeAttribute(
                    product_id=product.id,
                    **data,
                )
            )
            continue
        for field_name, value in data.items():
            if getattr(attribute, field_name) != value:
                evidence_changed = True
            setattr(attribute, field_name, value)
    if evidence_changed:
        invalidate_evidence_outputs(product)
    _commit(db)
    return get_attributes(db, product_id=product.id, scope_context=scope_context)


def get_keywords(
    db: Session,
    *,
    product_id: UUID,
    scope_context: KScopeContext,
    keyword_type: str | None = None,
    status_filter: str | None = None,
    language_code: str | None = None,
    market: str | None = None,
) -> list[KProductKnowledgeKeyword]:
    product = _require_scoped_product(db, product_id, scope_context)
    query = select(KProductKnowledgeKeyword).where(
        KProductKnowledgeKeyword.product_id == product.id
    )
    if keyword_type is not None:
        query = query.where(KProductKnowledgeKeyword.keyword_type == keyword_type)
    if status_filter is not None:
        query = query.where(KProductKnowledgeKeyword.status == status_filter)
    if language_code is not None:
        query = query.where(KProductKnowledgeKeyword.language_code == language_code)
    if market is not None:
        query = query.where(KProductKnowledgeKeyword.market == market)
    return list(db.scalars(query.order_by(KProductKnowledgeKeyword.created_at.desc())))


def patch_keywords(
    db: Session,
    *,
    product_id: UUID,
    payload: ProductKnowledgeKeywordPatch,
    scope_context: KScopeContext,
) -> list[KProductKnowledgeKeyword]:
    product = _require_scoped_product(db, product_id, scope_context)
    existing = {
        (
            item.keyword_text.lower(),
            item.keyword_type,
            item.language_code,
            item.market or "",
        ): item
        for item in db.scalars(
            select(KProductKnowledgeKeyword).where(
                KProductKnowledgeKeyword.product_id == product.id
            )
        )
    }
    for item in payload.items:
        data = item.model_dump()
        key = (
            item.keyword_text.lower(),
            item.keyword_type,
            item.language_code,
            item.market or "",
        )
        keyword = existing.get(key)
        if keyword is None:
            db.add(
                KProductKnowledgeKeyword(
                    product_id=product.id,
                    **data,
                )
            )
            continue
        for field_name, value in data.items():
            setattr(keyword, field_name, value)
    _commit(db)
    return get_keywords(db, product_id=product.id, scope_context=scope_context)


def get_risk_terms(
    db: Session,
    *,
    product_id: UUID,
    scope_context: KScopeContext,
    risk_type: str | None = None,
    status_filter: str | None = None,
) -> list[KProductKnowledgeRiskTerm]:
    product = _require_scoped_product(db, product_id, scope_context)
    query = select(KProductKnowledgeRiskTerm).where(
        KProductKnowledgeRiskTerm.product_id == product.id
    )
    if risk_type is not None:
        query = query.where(KProductKnowledgeRiskTerm.risk_type == risk_type)
    if status_filter is not None:
        query = query.where(KProductKnowledgeRiskTerm.status == status_filter)
    return list(db.scalars(query.order_by(KProductKnowledgeRiskTerm.created_at.desc())))


def patch_risk_terms(
    db: Session,
    *,
    product_id: UUID,
    payload: ProductKnowledgeRiskTermPatch,
    scope_context: KScopeContext,
) -> list[KProductKnowledgeRiskTerm]:
    product = _require_scoped_product(db, product_id, scope_context)
    existing = {
        (item.term_en.lower(), item.risk_type): item
        for item in db.scalars(
            select(KProductKnowledgeRiskTerm).where(
                KProductKnowledgeRiskTerm.product_id == product.id
            )
        )
    }
    for item in payload.items:
        data = item.model_dump()
        key = (item.term_en.lower(), item.risk_type)
        risk_term = existing.get(key)
        if risk_term is None:
            db.add(
                KProductKnowledgeRiskTerm(
                    product_id=product.id,
                    **data,
                )
            )
            continue
        for field_name, value in data.items():
            setattr(risk_term, field_name, value)
    _commit(db)
    return get_risk_terms(db, product_id=product.id, scope_context=scope_context)


def _require_scoped_product(
    db: Session,
    product_id: UUID,
    scope_context: KScopeContext,
) -> KProductKnowledgeProduct:
    query = apply_scope_filters(
        select(KProductKnowledgeProduct).where(
            KProductKnowledgeProduct.id == product_id
        ),
        KProductKnowledgeProduct,
        scope_context,
    )
    product = db.scalar(query)
    if product is None:
        raise KProductNotFoundError(f"K product '{product_id}' was not found.")
    return product


def _selected_model_dump(
    payload: ProductKnowledgeCreate | ProductKnowledgeUpdate,
    allowed_fields: frozenset[str],
    *,
    exclude_unset: bool = False,
) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.model_dump(exclude_unset=exclude_unset).items()
        if key in allowed_fields
    }


def _generate_product_key() -> str:
    return str(uuid4())


def _generate_unique_product_key(db: Session) -> str:
    for _ in range(PRODUCT_CREATE_MAX_ATTEMPTS):
        product_key = _generate_product_key()
        exists = db.scalar(
            select(KProductKnowledgeProduct.id)
            .where(KProductKnowledgeProduct.product_key == product_key)
            .limit(1)
        )
        if exists is None:
            return product_key
    raise KConflictError(PRODUCT_CREATE_CONFLICT_MESSAGE)


def _sku_exists(
    db: Session,
    *,
    scope_context: KScopeContext,
    sku: str,
) -> bool:
    query = apply_scope_filters(
        select(KProductKnowledgeProduct.id).where(
            KProductKnowledgeProduct.sku == sku
        ),
        KProductKnowledgeProduct,
        scope_context,
    )
    return db.scalar(query.limit(1)) is not None


def _ensure_sku_available(
    db: Session,
    *,
    scope_context: KScopeContext,
    sku: str,
) -> None:
    if _sku_exists(db, scope_context=scope_context, sku=sku):
        raise KConflictError("SKU already exists for this workspace.")


def _variant_hash(seed: dict[str, object]) -> str:
    canonical = json.dumps(seed, sort_keys=True, separators=(",", ":"), default=str)
    value = 0x811C9DC5
    for byte in canonical.encode("utf-8"):
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return f"{value:08X}"


def _variant_image_folder(product_key: str, variant_sku: str) -> str:
    return f"images/{product_key}/{variant_sku}"


def _variant_skus_exist(db: Session, variant_skus: list[str]) -> bool:
    if not variant_skus:
        return False
    return (
        db.scalar(
            select(KProductKnowledgeVariant.id)
            .where(KProductKnowledgeVariant.variant_sku.in_(variant_skus))
            .limit(1)
        )
        is not None
    )


def _delete_for_products(
    db: Session,
    model: type,
    product_ids: list[UUID],
) -> int:
    if not product_ids:
        return 0
    result = db.execute(delete(model).where(model.product_id.in_(product_ids)))
    return int(result.rowcount or 0)


def _variant_identity(
    db: Session,
    *,
    parent_sku: str,
    seed: dict[str, object],
    used_variant_hashes: set[str],
    used_variant_skus: set[str],
) -> tuple[str, str]:
    for collision_index in range(PRODUCT_CREATE_MAX_ATTEMPTS * 4):
        candidate_seed = (
            seed
            if collision_index == 0
            else {**seed, "collision_index": collision_index}
        )
        variant_hash = _variant_hash(candidate_seed)
        variant_sku = f"{parent_sku}-{variant_hash}"
        if variant_hash in used_variant_hashes or variant_sku in used_variant_skus:
            continue
        if _variant_skus_exist(db, [variant_sku]):
            continue
        used_variant_hashes.add(variant_hash)
        used_variant_skus.add(variant_sku)
        return variant_hash, variant_sku
    raise KConflictError("Variant SKU already exists.")


def _variant_rows_for_payload(
    *,
    db: Session,
    product: KProductKnowledgeProduct,
    parent_sku: str,
    payload: ProductKnowledgeCreate,
) -> list[KProductKnowledgeVariant]:
    raw_variants = (
        payload.variants
        if payload.product_type == "variable_product"
        else [
            {
                "color": None,
                "size": None,
                "function": None,
                "quantity": None,
                "price_override": None,
                "attributes": {"default_variant": True},
            }
        ]
    )
    rows: list[KProductKnowledgeVariant] = []
    used_variant_hashes: set[str] = set()
    used_variant_skus: set[str] = set()
    for index, item in enumerate(raw_variants):
        if isinstance(item, dict):
            data = item
        else:
            data = item.model_dump()
        seed = {
            "attributes": data.get("attributes") or {},
            "color": data.get("color"),
            "function": data.get("function"),
            "index": index,
            "size": data.get("size"),
        }
        variant_hash, variant_sku = _variant_identity(
            db,
            parent_sku=parent_sku,
            seed=seed,
            used_variant_hashes=used_variant_hashes,
            used_variant_skus=used_variant_skus,
        )
        # 变体级物理规格(1 个装/2 个装尺寸重量不同)挂在 attributes_json.physical,
        # 结构与父体 dimensions_json/weight_json 同构;P 装配按变体读取。
        attributes_json = dict(data.get("attributes") or {})
        physical = {
            key: value
            for key, value in (
                ("dimensions", data.get("dimensions_json")),
                ("weight", data.get("weight_json")),
            )
            if value
        }
        if physical:
            attributes_json["physical"] = physical
        # 变体(颜色)专属参考图:先随行落库,建品路由的 fail-safe 钩子
        # 再统一下载进媒体库(下载失败不阻塞建品)。
        if data.get("reference_image_url"):
            attributes_json["reference_image_url"] = data["reference_image_url"]
        rows.append(
            KProductKnowledgeVariant(
                id=uuid4(),
                product_id=product.id,
                parent_sku=parent_sku,
                variant_sku=variant_sku,
                variant_hash=variant_hash,
                color=data.get("color"),
                size=data.get("size"),
                function=data.get("function"),
                quantity=data.get("quantity"),
                price_override=data.get("price_override"),
                attributes_json=attributes_json,
                image_folder=_variant_image_folder(product.product_key, variant_sku),
            )
        )
    return rows


def ensure_default_product_variant(
    db: Session,
    product: KProductKnowledgeProduct,
) -> KProductKnowledgeVariant:
    """Persist the canonical default variant for an imported simple product.

    F→K and R→K bypass ``create_product`` and therefore do not pass through
    ``_variant_rows_for_payload``.  Keep their default row identical to the
    regular K create path so image APIs can resolve the product by variant SKU.
    """

    existing = db.scalar(
        select(KProductKnowledgeVariant)
        .where(KProductKnowledgeVariant.product_id == product.id)
        .order_by(KProductKnowledgeVariant.created_at.asc())
        .limit(1)
    )
    if existing is not None:
        return existing

    parent_sku = ensure_product_sku(db, product)
    attributes: dict[str, object] = {"default_variant": True}
    seed = {
        "attributes": attributes,
        "color": None,
        "function": None,
        "index": 0,
        "size": None,
    }
    variant_hash, variant_sku = _variant_identity(
        db,
        parent_sku=parent_sku,
        seed=seed,
        used_variant_hashes=set(),
        used_variant_skus=set(),
    )
    variant = KProductKnowledgeVariant(
        id=uuid4(),
        product_id=product.id,
        parent_sku=parent_sku,
        variant_sku=variant_sku,
        variant_hash=variant_hash,
        attributes_json=attributes,
        image_folder=_variant_image_folder(product.product_key, variant_sku),
    )
    db.add(variant)
    db.flush()
    return variant


def _commit(db: Session) -> None:
    # K06B intentionally leaves operation_logs as a future optional hook.
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise KConflictError() from exc
