"""Service skeleton for the isolated K Product Knowledge module."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .errors import KConflictError, KInvalidStateError, KProductNotFoundError
from .models import (
    KProductKnowledgeAttribute,
    KProductKnowledgeKeyword,
    KProductKnowledgeProduct,
    KProductKnowledgeRiskTerm,
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
from .constants import TARGET_ORGANIZATION_NAME

PRODUCT_CREATE_FIELDS = frozenset(
    {
        "product_key",
        "raw_input_text",
        "raw_input_language",
        "source_system",
        "source_record_id",
        "sku",
        "product_status",
        "review_status",
        "canonical_language",
        "product_name_en",
        "brand_name",
        "manufacturer",
        "product_type",
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
        "sku",
        "product_status",
        "review_status",
        "canonical_language",
        "raw_input_text",
        "raw_input_language",
        "product_name_en",
        "brand_name",
        "manufacturer",
        "product_type",
        "short_description_en",
        "long_description_en",
        "primary_use_case_en",
        "target_customer_en",
        "manual_notes",
    }
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
                KProductKnowledgeProduct.product_name_en.ilike(term),
                KProductKnowledgeProduct.brand_name.ilike(term),
            )
        )
    query = query.order_by(KProductKnowledgeProduct.created_at.desc())
    return list(db.scalars(query.limit(limit).offset(offset)))


def create_product(
    db: Session,
    *,
    payload: ProductKnowledgeCreate,
    scope_context: KScopeContext,
) -> KProductKnowledgeProduct:
    context = normalize_scope_context(scope_context)
    product_data = _selected_model_dump(payload, PRODUCT_CREATE_FIELDS)
    product = KProductKnowledgeProduct(
        id=uuid4(),
        **product_data,
        workspace_key=context.workspace_key,
        business_context=context.business_context,
        scope_mode=context.scope_mode,
        organization_name=TARGET_ORGANIZATION_NAME,
    )
    db.add(product)

    for item in payload.attributes:
        db.add(
            KProductKnowledgeAttribute(
                product_id=product.id,
                **item.model_dump(),
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

    _commit(db)
    db.refresh(product)
    return product


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

    # No-op patches are accepted as idempotent in this skeleton.
    for field_name, value in _selected_model_dump(
        payload,
        PRODUCT_UPDATE_FIELDS,
        exclude_unset=True,
    ).items():
        setattr(product, field_name, value)

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
    for item in payload.items:
        data = item.model_dump()
        key = (item.attribute_key, item.attribute_group or "")
        attribute = existing.get(key)
        if attribute is None:
            db.add(
                KProductKnowledgeAttribute(
                    product_id=product.id,
                    **data,
                )
            )
            continue
        for field_name, value in data.items():
            setattr(attribute, field_name, value)
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


def _commit(db: Session) -> None:
    # K06B intentionally leaves operation_logs as a future optional hook.
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise KConflictError() from exc
