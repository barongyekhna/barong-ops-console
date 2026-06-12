"""Unregistered FastAPI router skeleton for K Product Knowledge."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.orm import Session

from ....api.deps import get_current_user
from ....db.session import get_db
from ....models.user import User
from .access import require_k_product_knowledge_access
from .constants import API_PREFIX
from .errors import KProductKnowledgeError
from .schemas import (
    ArchiveProductKnowledgeRequest,
    ProductKnowledgeAttributeListResponse,
    ProductKnowledgeAttributePatch,
    ProductKnowledgeCreate,
    ProductKnowledgeKeywordListResponse,
    ProductKnowledgeKeywordPatch,
    ProductKnowledgeListResponse,
    ProductKnowledgeRead,
    ProductKnowledgeRiskTermListResponse,
    ProductKnowledgeRiskTermPatch,
    ProductKnowledgeUpdate,
)
from .scope_shim import default_scope_context
from .service import (
    archive_product,
    create_product,
    get_attributes,
    get_keywords,
    get_product,
    get_risk_terms,
    list_products,
    patch_attributes,
    patch_keywords,
    patch_risk_terms,
    update_product,
)

router = APIRouter(prefix=API_PREFIX, tags=["k-product-knowledge"])


@router.get("/", response_model=ProductKnowledgeListResponse)
def product_knowledge_list(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    product_status: str | None = Query(default=None, alias="status"),
    review_status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProductKnowledgeListResponse:
    require_k_product_knowledge_access(user, "read")
    items = list_products(
        db,
        scope_context=default_scope_context(),
        limit=limit,
        offset=offset,
        status_filter=product_status,
        review_status=review_status,
        q=q,
    )
    return ProductKnowledgeListResponse(
        items=items,
        count=len(items),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/",
    response_model=ProductKnowledgeRead,
    status_code=status.HTTP_201_CREATED,
)
def product_knowledge_create(
    payload: ProductKnowledgeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProductKnowledgeRead:
    require_k_product_knowledge_access(user, "create")
    try:
        product = create_product(
            db,
            payload=payload,
            scope_context=default_scope_context(),
        )
    except KProductKnowledgeError as exc:
        raise exc.to_http_exception() from None
    return ProductKnowledgeRead.model_validate(product)


@router.get("/{product_id}", response_model=ProductKnowledgeRead)
def product_knowledge_detail(
    product_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProductKnowledgeRead:
    require_k_product_knowledge_access(user, "read")
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=default_scope_context(),
        )
    except KProductKnowledgeError as exc:
        raise exc.to_http_exception() from None
    return ProductKnowledgeRead.model_validate(product)


@router.patch("/{product_id}", response_model=ProductKnowledgeRead)
def product_knowledge_update(
    product_id: UUID,
    payload: ProductKnowledgeUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProductKnowledgeRead:
    require_k_product_knowledge_access(user, "update")
    try:
        product = update_product(
            db,
            product_id=product_id,
            payload=payload,
            scope_context=default_scope_context(),
        )
    except KProductKnowledgeError as exc:
        raise exc.to_http_exception() from None
    return ProductKnowledgeRead.model_validate(product)


@router.post("/{product_id}/archive", response_model=ProductKnowledgeRead)
def product_knowledge_archive(
    product_id: UUID,
    payload: ArchiveProductKnowledgeRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProductKnowledgeRead:
    require_k_product_knowledge_access(user, "archive")
    try:
        product = archive_product(
            db,
            product_id=product_id,
            payload=payload or ArchiveProductKnowledgeRequest(),
            scope_context=default_scope_context(),
        )
    except KProductKnowledgeError as exc:
        raise exc.to_http_exception() from None
    return ProductKnowledgeRead.model_validate(product)


@router.get(
    "/{product_id}/attributes",
    response_model=ProductKnowledgeAttributeListResponse,
)
def product_knowledge_attributes(
    product_id: UUID,
    attribute_group: str | None = Query(default=None, max_length=128),
    requires_review: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProductKnowledgeAttributeListResponse:
    require_k_product_knowledge_access(user, "read")
    try:
        items = get_attributes(
            db,
            product_id=product_id,
            scope_context=default_scope_context(),
            attribute_group=attribute_group,
            requires_review=requires_review,
        )
    except KProductKnowledgeError as exc:
        raise exc.to_http_exception() from None
    return ProductKnowledgeAttributeListResponse(items=items, count=len(items))


@router.patch(
    "/{product_id}/attributes",
    response_model=ProductKnowledgeAttributeListResponse,
)
def product_knowledge_attributes_patch(
    product_id: UUID,
    payload: ProductKnowledgeAttributePatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProductKnowledgeAttributeListResponse:
    require_k_product_knowledge_access(user, "attributes.manage")
    try:
        items = patch_attributes(
            db,
            product_id=product_id,
            payload=payload,
            scope_context=default_scope_context(),
        )
    except KProductKnowledgeError as exc:
        raise exc.to_http_exception() from None
    return ProductKnowledgeAttributeListResponse(items=items, count=len(items))


@router.get(
    "/{product_id}/keywords",
    response_model=ProductKnowledgeKeywordListResponse,
)
def product_knowledge_keywords(
    product_id: UUID,
    keyword_type: str | None = Query(default=None, max_length=50),
    status_filter: str | None = Query(default=None, alias="status"),
    language_code: str | None = Query(default=None, max_length=16),
    market: str | None = Query(default=None, max_length=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProductKnowledgeKeywordListResponse:
    require_k_product_knowledge_access(user, "read")
    try:
        items = get_keywords(
            db,
            product_id=product_id,
            scope_context=default_scope_context(),
            keyword_type=keyword_type,
            status_filter=status_filter,
            language_code=language_code,
            market=market,
        )
    except KProductKnowledgeError as exc:
        raise exc.to_http_exception() from None
    return ProductKnowledgeKeywordListResponse(items=items, count=len(items))


@router.patch(
    "/{product_id}/keywords",
    response_model=ProductKnowledgeKeywordListResponse,
)
def product_knowledge_keywords_patch(
    product_id: UUID,
    payload: ProductKnowledgeKeywordPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProductKnowledgeKeywordListResponse:
    require_k_product_knowledge_access(user, "keywords.manage")
    try:
        items = patch_keywords(
            db,
            product_id=product_id,
            payload=payload,
            scope_context=default_scope_context(),
        )
    except KProductKnowledgeError as exc:
        raise exc.to_http_exception() from None
    return ProductKnowledgeKeywordListResponse(items=items, count=len(items))


@router.get(
    "/{product_id}/risk-terms",
    response_model=ProductKnowledgeRiskTermListResponse,
)
def product_knowledge_risk_terms(
    product_id: UUID,
    risk_type: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProductKnowledgeRiskTermListResponse:
    require_k_product_knowledge_access(user, "read")
    try:
        items = get_risk_terms(
            db,
            product_id=product_id,
            scope_context=default_scope_context(),
            risk_type=risk_type,
            status_filter=status_filter,
        )
    except KProductKnowledgeError as exc:
        raise exc.to_http_exception() from None
    return ProductKnowledgeRiskTermListResponse(items=items, count=len(items))


@router.patch(
    "/{product_id}/risk-terms",
    response_model=ProductKnowledgeRiskTermListResponse,
)
def product_knowledge_risk_terms_patch(
    product_id: UUID,
    payload: ProductKnowledgeRiskTermPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProductKnowledgeRiskTermListResponse:
    require_k_product_knowledge_access(user, "risk_terms.manage")
    try:
        items = patch_risk_terms(
            db,
            product_id=product_id,
            payload=payload,
            scope_context=default_scope_context(),
        )
    except KProductKnowledgeError as exc:
        raise exc.to_http_exception() from None
    return ProductKnowledgeRiskTermListResponse(items=items, count=len(items))
