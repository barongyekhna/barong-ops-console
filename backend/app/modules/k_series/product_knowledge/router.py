from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....api.deps import get_current_user
from ....db.session import get_db
from ....models.user import User
from ....services.api_key_orchestration import ApiKeyIsolationError
from ....services.ai_provider_router import AIExecutionRouter, AIProviderExecutionError
from ....services.module_execution_gate import (
    ModuleExecutionContext,
    ModuleExecutionGateError,
    require_module_execution_ready,
)
from ....services.permission_service import resolve_current_user_permission_info
from .constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_SCOPE_MODE,
    DEFAULT_WORKSPACE_KEY,
    MODULE_KEY,
    PERMISSION_ARCHIVE,
    PERMISSION_ATTRIBUTES_MANAGE,
    PERMISSION_CREATE,
    PERMISSION_KEYWORDS_MANAGE,
    PERMISSION_PRODUCTS_READ,
    PERMISSION_READ,
    PERMISSION_RISK_TERMS_MANAGE,
    PERMISSION_UPDATE,
    PERMISSION_EXPORT,
    PERMISSION_WORKFLOW_EXECUTE,
    TARGET_ORGANIZATION_NAME,
)
from .errors import KConflictError, KProductKnowledgeError, KProductNotFoundError
from .models import (
    KProductKnowledgeAIEvent,
    KProductKnowledgeAttribute,
    KProductKnowledgeKeyword,
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeResearchRun,
    KProductKnowledgeRiskTerm,
    KProductKnowledgeTranslation,
)
from .schemas import (
    ArchiveProductKnowledgeRequest,
    ProductKnowledgeAttributeListResponse,
    ProductKnowledgeAttributePatch,
    ProductKnowledgeCreate,
    ProductKnowledgeKeywordItem,
    ProductKnowledgeKeywordListResponse,
    ProductKnowledgeKeywordPatch,
    ProductKnowledgeListItem,
    ProductKnowledgeListResponse,
    ProductKnowledgeImageBindRequest,
    ProductKnowledgeMediaDownloadResponse,
    ProductKnowledgeRead,
    ProductKnowledgeRiskReviewRequest,
    ProductKnowledgeRiskTermItem,
    ProductKnowledgeRiskTermListResponse,
    ProductKnowledgeRiskTermPatch,
    ProductKnowledgeUpdate,
    ProductKnowledgeWorkflowControlRequest,
    ProductKnowledgeWorkflowExecutionRead,
    ProductKnowledgeWorkflowExportRequest,
    ProductKnowledgeWorkflowExportResponse,
    ProductKnowledgeWorkflowStartRequest,
)
from .scope_shim import KScopeContext, apply_scope_filters
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
from .workflow_engine import (
    IMAGE_SOURCE_MANUAL,
    KWorkflowOrchestratorV2,
    KWorkflowExecutionError,
)

router = APIRouter(prefix="/k", tags=["k-product-knowledge"])


class KeywordEntry(BaseModel):
    id: str
    product_id: str
    keyword: str
    source: str
    status: str
    created_at: datetime
    updated_at: datetime


class KeywordEntryResponse(BaseModel):
    keyword_entry: KeywordEntry
    status: Literal["created", "updated", "archived"]
    timestamp: datetime


class KeywordListResponse(BaseModel):
    keyword_entries: list[KeywordEntry]
    status: Literal["ok"] = "ok"
    timestamp: datetime


class CreateKeywordPayload(BaseModel):
    keyword: str = Field(min_length=1, max_length=512)
    product_id: str = Field(min_length=1)
    source: str = Field(default="manual", min_length=1, max_length=50)
    status: str | None = Field(default="active", max_length=50)


class UpdateKeywordPayload(BaseModel):
    keyword: str | None = Field(default=None, max_length=512)
    product_id: str | None = Field(default=None)
    source: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, max_length=50)


class RiskTermEntry(BaseModel):
    id: str
    product_id: str
    term: str
    risk_level: str
    category: str
    source: str
    status: str
    created_at: datetime
    updated_at: datetime


class RiskTermResponse(BaseModel):
    risk_term: RiskTermEntry
    status: Literal["created", "updated", "ignored"]
    timestamp: datetime


class RiskListResponse(BaseModel):
    risk_terms: list[RiskTermEntry]
    status: Literal["ok"] = "ok"
    timestamp: datetime


class CreateRiskPayload(BaseModel):
    product_id: str = Field(min_length=1)
    term: str = Field(min_length=1, max_length=512)
    risk_level: str = Field(default="low", max_length=50)
    category: str = Field(default="marketing", max_length=100)
    source: str = Field(default="manual", max_length=50)
    status: str | None = Field(default="active", max_length=50)


class UpdateRiskPayload(BaseModel):
    product_id: str | None = Field(default=None)
    term: str | None = Field(default=None, max_length=512)
    risk_level: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    source: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, max_length=50)


class StartResearchRunRequest(BaseModel):
    product_id: str = Field(min_length=1)


class ResearchRunResponse(BaseModel):
    run_id: str
    id: str
    product_id: str
    status: Literal["pending", "running", "completed", "failed"]
    query_type: Literal["keyword_research"] = "keyword_research"
    created_at: datetime
    updated_at: datetime
    keywords: list[str] = Field(default_factory=list)
    competitor_brands: list[str] = Field(default_factory=list)
    search_intent: str = ""
    source: Literal["k15_trigger", "manual", "system"] = "k15_trigger"
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)


class SERPItem(BaseModel):
    title: str
    url: str
    snippet: str = ""
    rank: int = Field(ge=1)


class SERPSearchRequest(BaseModel):
    product_id: str = Field(min_length=1)
    market: str = Field(min_length=1, max_length=50)
    query: str = Field(min_length=1)


class SERPResultResponse(BaseModel):
    id: str
    product_id: str
    market: str
    query: str
    organic_results: list[SERPItem]
    competitor_links: list[str]
    keywords: list[str]
    source: str
    created_at: datetime
    updated_at: datetime


class ProviderExecutionResponse(BaseModel):
    status: Literal["completed"]
    provider: str
    product_id: str
    stored_event_id: str
    output: dict[str, Any]


class SellingPointBullet(BaseModel):
    category: str
    text: str
    importance_score: int | float


class SellingPointsResponse(BaseModel):
    bullets: list[SellingPointBullet]
    seo_keywords: list[str] = Field(default_factory=list)
    market_tags: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    source: str


class GenerateSellingPointsRequest(BaseModel):
    product: dict[str, Any] = Field(default_factory=dict)
    mode: str | None = None


class MediaAssetCreate(BaseModel):
    product_id: str = Field(min_length=1)
    asset_type: str = Field(min_length=1, max_length=50)
    asset_role: str = Field(default="gallery", min_length=1, max_length=50)
    filename: str | None = Field(default=None, max_length=255)
    file_url_placeholder: str | None = Field(default=None, max_length=2048)
    mime_type: str | None = Field(default=None, max_length=100)
    source: str | None = Field(default=IMAGE_SOURCE_MANUAL, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MediaAssetRead(BaseModel):
    id: str
    product_id: str
    asset_type: str
    asset_role: str
    status: str
    review_status: str
    object_key: str | None
    file_url_placeholder: str | None
    mime_type: str | None
    source: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class MediaAssetListResponse(BaseModel):
    items: list[MediaAssetRead]
    count: int


def _raise_k_error(exc: KProductKnowledgeError) -> None:
    raise exc.to_http_exception() from exc


def _require_k_permission(permission_key: str):
    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(db, user, request=request)
        allowed_permission_keys = {permission_key}
        if permission_key == PERMISSION_READ:
            allowed_permission_keys.add(PERMISSION_PRODUCTS_READ)
        if permissions.is_owner_full_access or allowed_permission_keys.intersection(
            permissions.permission_keys
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission_key}",
        )

    return dependency


def _scope_context(request: Request | None) -> KScopeContext:
    org_id = None
    if request is not None:
        org_id = getattr(request.state, "org_id", None)
        if org_id is None:
            org_context = getattr(request.state, "org_context", None)
            org_id = getattr(org_context, "org_id", None)
    workspace_key = str(org_id).strip() if org_id else DEFAULT_WORKSPACE_KEY
    return KScopeContext(
        workspace_key=workspace_key,
        business_context=DEFAULT_BUSINESS_CONTEXT,
        scope_mode="production",
    )


def _product_read(product: KProductKnowledgeProduct) -> ProductKnowledgeRead:
    return ProductKnowledgeRead.model_validate(product)


def _product_list_item(product: KProductKnowledgeProduct) -> ProductKnowledgeListItem:
    return ProductKnowledgeListItem.model_validate(product)


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
            KProductKnowledgeProduct.product_key == normalized,
        ),
        KProductKnowledgeProduct,
        scope_context,
    )
    product = db.scalar(query)
    if product is not None:
        return product
    if not create_shell:
        raise KProductNotFoundError(f"K product '{normalized}' was not found.")

    product = KProductKnowledgeProduct(
        id=uuid4(),
        workspace_key=scope_context.workspace_key,
        business_context=scope_context.business_context,
        scope_mode=scope_context.scope_mode,
        organization_name=TARGET_ORGANIZATION_NAME,
        product_key=normalized,
        product_status="draft",
        review_status="draft",
        canonical_language="en",
        raw_input_text=f"Runtime shell for {normalized}",
        raw_input_language="en",
        source_system="k_adapter",
    )
    db.add(product)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise KConflictError() from exc
    return product


def _product_public_ref(product: KProductKnowledgeProduct) -> str:
    return product.product_key or str(product.id)


def _k19_status_to_model(status_value: str | None) -> str:
    mapping = {
        "active": "approved",
        "edited": "approved",
        "suggested": "candidate",
        "archived": "removed",
    }
    return mapping.get((status_value or "active").strip().lower(), "candidate")


def _k19_status_from_model(status_value: str) -> str:
    mapping = {
        "approved": "active",
        "candidate": "suggested",
        "removed": "archived",
        "rejected": "archived",
    }
    return mapping.get(status_value, "suggested")


def _keyword_entry(
    db: Session,
    keyword: KProductKnowledgeKeyword,
) -> KeywordEntry:
    product = db.get(KProductKnowledgeProduct, keyword.product_id)
    return KeywordEntry(
        id=str(keyword.id),
        product_id=_product_public_ref(product) if product else str(keyword.product_id),
        keyword=keyword.keyword_text,
        source=keyword.source,
        status=_k19_status_from_model(keyword.status),
        created_at=keyword.created_at,
        updated_at=keyword.updated_at,
    )


def _k20_status_to_model(status_value: str | None) -> str:
    mapping = {
        "active": "candidate",
        "resolved": "confirmed",
        "ignored": "false_positive",
    }
    return mapping.get((status_value or "active").strip().lower(), "candidate")


def _k20_status_from_model(status_value: str) -> str:
    mapping = {
        "candidate": "active",
        "confirmed": "resolved",
        "false_positive": "ignored",
        "removed": "ignored",
    }
    return mapping.get(status_value, "active")


def _risk_entry(db: Session, risk: KProductKnowledgeRiskTerm) -> RiskTermEntry:
    product = db.get(KProductKnowledgeProduct, risk.product_id)
    risk_parts = (risk.risk_type or "marketing").split(":", 1)
    risk_level = risk_parts[0] if len(risk_parts) == 2 else "low"
    category = risk_parts[1] if len(risk_parts) == 2 else risk_parts[0]
    return RiskTermEntry(
        id=str(risk.id),
        product_id=_product_public_ref(product) if product else str(risk.product_id),
        term=risk.term_en,
        risk_level=risk_level,
        category=category,
        source=risk.source,
        status=_k20_status_from_model(risk.status),
        created_at=risk.created_at,
        updated_at=risk.updated_at,
    )


def _gate_error(exc: ModuleExecutionGateError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": str(exc),
            "module_id": exc.module_id,
            "org_id": exc.org_id,
        },
    )


def _workflow_error(exc: KWorkflowExecutionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.error_report)


def _execution_context(
    db: Session,
    *,
    request: Request,
    user: User,
    key_requirements: dict[str, str],
):
    try:
        return require_module_execution_ready(
            db,
            module_id=MODULE_KEY,
            user=user,
            request=request,
            key_requirements=key_requirements,
        )
    except ModuleExecutionGateError as exc:
        raise _gate_error(exc) from exc


def _execute_provider_json(
    db: Session,
    *,
    context: ModuleExecutionContext,
    provider: str,
    task_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        return AIExecutionRouter(db).execute(
            provider=provider,
            task_type=task_type,  # type: ignore[arg-type]
            payload=payload,
            org=TARGET_ORGANIZATION_NAME,
            module_id=MODULE_KEY,
            execution_context=context,
        )
    except AIProviderExecutionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.structured_error(),
        ) from exc


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _organic_results(value: Any) -> list[SERPItem]:
    if not isinstance(value, list):
        return []
    items: list[SERPItem] = []
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("name") or "").strip()
        url = str(raw.get("url") or raw.get("link") or "").strip()
        if not title or not url:
            continue
        items.append(
            SERPItem(
                title=title,
                url=url,
                snippet=str(raw.get("snippet") or raw.get("description") or ""),
                rank=int(raw.get("rank") or raw.get("position") or index),
            )
        )
    return items


def _now() -> datetime:
    return datetime.now(UTC)


def _source_text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@router.get("/products", response_model=ProductKnowledgeListResponse)
def product_knowledge_list(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    review_status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> ProductKnowledgeListResponse:
    del user
    scope_context = _scope_context(request)
    items = list_products(
        db,
        scope_context=scope_context,
        limit=limit,
        offset=offset,
        status_filter=status_filter,
        review_status=review_status,
        q=q,
    )
    return ProductKnowledgeListResponse(
        items=[_product_list_item(item) for item in items],
        count=_count_products(
            db,
            scope_context=scope_context,
            status_filter=status_filter,
            review_status=review_status,
            q=q,
        ),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/products",
    response_model=ProductKnowledgeRead,
    status_code=status.HTTP_201_CREATED,
)
def product_knowledge_create(
    request: Request,
    payload: ProductKnowledgeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_CREATE)),
) -> ProductKnowledgeRead:
    del user
    try:
        product = create_product(
            db,
            payload=payload,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return _product_read(product)


@router.get("/products/{product_id}", response_model=ProductKnowledgeRead)
def product_knowledge_detail(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> ProductKnowledgeRead:
    del user
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return _product_read(product)


@router.patch("/products/{product_id}", response_model=ProductKnowledgeRead)
def product_knowledge_update(
    product_id: UUID,
    payload: ProductKnowledgeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> ProductKnowledgeRead:
    del user
    try:
        product = update_product(
            db,
            product_id=product_id,
            payload=payload,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return _product_read(product)


@router.post("/products/{product_id}/archive", response_model=ProductKnowledgeRead)
def product_knowledge_archive(
    product_id: UUID,
    request: Request,
    payload: ArchiveProductKnowledgeRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_ARCHIVE)),
) -> ProductKnowledgeRead:
    del user
    try:
        product = archive_product(
            db,
            product_id=product_id,
            payload=payload or ArchiveProductKnowledgeRequest(),
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return _product_read(product)


@router.get(
    "/products/{product_id}/attributes",
    response_model=ProductKnowledgeAttributeListResponse,
)
def product_knowledge_attributes(
    product_id: UUID,
    request: Request,
    attribute_group: str | None = Query(default=None, max_length=128),
    requires_review: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> ProductKnowledgeAttributeListResponse:
    del user
    try:
        items = get_attributes(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
            attribute_group=attribute_group,
            requires_review=requires_review,
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return ProductKnowledgeAttributeListResponse(items=items, count=len(items))


@router.patch(
    "/products/{product_id}/attributes",
    response_model=ProductKnowledgeAttributeListResponse,
)
def product_knowledge_attributes_patch(
    product_id: UUID,
    payload: ProductKnowledgeAttributePatch,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_ATTRIBUTES_MANAGE)),
) -> ProductKnowledgeAttributeListResponse:
    del user
    try:
        items = patch_attributes(
            db,
            product_id=product_id,
            payload=payload,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return ProductKnowledgeAttributeListResponse(items=items, count=len(items))


@router.get(
    "/products/{product_id}/keywords",
    response_model=ProductKnowledgeKeywordListResponse,
)
def product_knowledge_keywords(
    product_id: UUID,
    request: Request,
    keyword_type: str | None = Query(default=None, max_length=50),
    status_filter: str | None = Query(default=None, alias="status"),
    language_code: str | None = Query(default=None, max_length=16),
    market: str | None = Query(default=None, max_length=50),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> ProductKnowledgeKeywordListResponse:
    del user
    try:
        items = get_keywords(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
            keyword_type=keyword_type,
            status_filter=status_filter,
            language_code=language_code,
            market=market,
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return ProductKnowledgeKeywordListResponse(items=items, count=len(items))


@router.patch(
    "/products/{product_id}/keywords",
    response_model=ProductKnowledgeKeywordListResponse,
)
def product_knowledge_keywords_patch(
    product_id: UUID,
    payload: ProductKnowledgeKeywordPatch,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_KEYWORDS_MANAGE)),
) -> ProductKnowledgeKeywordListResponse:
    del user
    try:
        items = patch_keywords(
            db,
            product_id=product_id,
            payload=payload,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return ProductKnowledgeKeywordListResponse(items=items, count=len(items))


@router.get(
    "/products/{product_id}/risk-terms",
    response_model=ProductKnowledgeRiskTermListResponse,
)
def product_knowledge_risk_terms(
    product_id: UUID,
    request: Request,
    risk_type: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> ProductKnowledgeRiskTermListResponse:
    del user
    try:
        items = get_risk_terms(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
            risk_type=risk_type,
            status_filter=status_filter,
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return ProductKnowledgeRiskTermListResponse(items=items, count=len(items))


@router.patch(
    "/products/{product_id}/risk-terms",
    response_model=ProductKnowledgeRiskTermListResponse,
)
def product_knowledge_risk_terms_patch(
    product_id: UUID,
    payload: ProductKnowledgeRiskTermPatch,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_RISK_TERMS_MANAGE)),
) -> ProductKnowledgeRiskTermListResponse:
    del user
    try:
        items = patch_risk_terms(
            db,
            product_id=product_id,
            payload=payload,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return ProductKnowledgeRiskTermListResponse(items=items, count=len(items))


@router.get(
    "/products/{product_id}/workflow/latest",
    response_model=ProductKnowledgeWorkflowExecutionRead,
)
def product_knowledge_workflow_latest(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> ProductKnowledgeWorkflowExecutionRead:
    del user
    try:
        execution = KWorkflowOrchestratorV2(db).latest_execution_for_product(
            product_id=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="K workflow execution was not found.",
        )
    return ProductKnowledgeWorkflowExecutionRead.model_validate(execution)


@router.post(
    "/products/{product_id}/workflow/start",
    response_model=ProductKnowledgeWorkflowExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def product_knowledge_workflow_start(
    product_id: UUID,
    payload: ProductKnowledgeWorkflowStartRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_WORKFLOW_EXECUTE)),
) -> ProductKnowledgeWorkflowExecutionRead:
    try:
        execution = KWorkflowOrchestratorV2(db).start_pipeline(
            product_id=product_id,
            payload=payload,
            scope_context=_scope_context(request),
            request=request,
            user=user,
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    except KWorkflowExecutionError as exc:
        raise _workflow_error(exc) from exc
    return ProductKnowledgeWorkflowExecutionRead.model_validate(execution)


@router.post(
    "/products/{product_id}/workflow/risk-review",
    response_model=ProductKnowledgeWorkflowExecutionRead,
)
def product_knowledge_workflow_risk_review(
    product_id: UUID,
    payload: ProductKnowledgeRiskReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_RISK_TERMS_MANAGE)),
) -> ProductKnowledgeWorkflowExecutionRead:
    try:
        execution = KWorkflowOrchestratorV2(db).review_risk_terms(
            product_id=product_id,
            payload=payload,
            scope_context=_scope_context(request),
            user=user,
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    except KWorkflowExecutionError as exc:
        raise _workflow_error(exc) from exc
    return ProductKnowledgeWorkflowExecutionRead.model_validate(execution)


@router.post(
    "/products/{product_id}/workflow/export",
    response_model=ProductKnowledgeWorkflowExportResponse,
)
def product_knowledge_workflow_export(
    product_id: UUID,
    request: Request,
    payload: ProductKnowledgeWorkflowExportRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_EXPORT)),
) -> ProductKnowledgeWorkflowExportResponse:
    try:
        execution, report = KWorkflowOrchestratorV2(db).export_payloads(
            product_id=product_id,
            payload=payload or ProductKnowledgeWorkflowExportRequest(),
            scope_context=_scope_context(request),
            user=user,
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    except KWorkflowExecutionError as exc:
        raise _workflow_error(exc) from exc
    return ProductKnowledgeWorkflowExportResponse(
        execution=ProductKnowledgeWorkflowExecutionRead.model_validate(execution),
        report=report,
    )


def _workflow_control_id(
    db: Session,
    *,
    product_id: UUID,
    payload: ProductKnowledgeWorkflowControlRequest | None,
    request: Request,
) -> UUID:
    if payload is not None and payload.execution_id is not None:
        return payload.execution_id
    execution = KWorkflowOrchestratorV2(db).latest_execution_for_product(
        product_id=product_id,
        scope_context=_scope_context(request),
    )
    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="K workflow execution was not found.",
        )
    return execution.id


@router.post(
    "/products/{product_id}/workflow/pause",
    response_model=ProductKnowledgeWorkflowExecutionRead,
)
def product_knowledge_workflow_pause(
    product_id: UUID,
    request: Request,
    payload: ProductKnowledgeWorkflowControlRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_WORKFLOW_EXECUTE)),
) -> ProductKnowledgeWorkflowExecutionRead:
    try:
        execution = KWorkflowOrchestratorV2(db).pause(
            workflow_id=_workflow_control_id(
                db,
                product_id=product_id,
                payload=payload,
                request=request,
            ),
            scope_context=_scope_context(request),
            user=user,
        )
    except KWorkflowExecutionError as exc:
        raise _workflow_error(exc) from exc
    return ProductKnowledgeWorkflowExecutionRead.model_validate(execution)


@router.post(
    "/products/{product_id}/workflow/resume",
    response_model=ProductKnowledgeWorkflowExecutionRead,
)
def product_knowledge_workflow_resume(
    product_id: UUID,
    request: Request,
    payload: ProductKnowledgeWorkflowControlRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_WORKFLOW_EXECUTE)),
) -> ProductKnowledgeWorkflowExecutionRead:
    try:
        execution = KWorkflowOrchestratorV2(db).resume(
            workflow_id=_workflow_control_id(
                db,
                product_id=product_id,
                payload=payload,
                request=request,
            ),
            scope_context=_scope_context(request),
            request=request,
            user=user,
        )
    except KWorkflowExecutionError as exc:
        raise _workflow_error(exc) from exc
    return ProductKnowledgeWorkflowExecutionRead.model_validate(execution)


@router.post(
    "/products/{product_id}/workflow/retry",
    response_model=ProductKnowledgeWorkflowExecutionRead,
)
def product_knowledge_workflow_retry(
    product_id: UUID,
    payload: ProductKnowledgeWorkflowControlRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_WORKFLOW_EXECUTE)),
) -> ProductKnowledgeWorkflowExecutionRead:
    if not payload.step:
        raise HTTPException(status_code=422, detail="retry requires step.")
    try:
        execution = KWorkflowOrchestratorV2(db).retry(
            workflow_id=_workflow_control_id(
                db,
                product_id=product_id,
                payload=payload,
                request=request,
            ),
            step=payload.step,
            payload=payload.workflow_payload,
            scope_context=_scope_context(request),
            request=request,
            user=user,
        )
    except KWorkflowExecutionError as exc:
        raise _workflow_error(exc) from exc
    return ProductKnowledgeWorkflowExecutionRead.model_validate(execution)


@router.post(
    "/products/{product_id}/workflow/rollback",
    response_model=ProductKnowledgeWorkflowExecutionRead,
)
def product_knowledge_workflow_rollback(
    product_id: UUID,
    payload: ProductKnowledgeWorkflowControlRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_WORKFLOW_EXECUTE)),
) -> ProductKnowledgeWorkflowExecutionRead:
    if not payload.step:
        raise HTTPException(status_code=422, detail="rollback requires step.")
    try:
        execution = KWorkflowOrchestratorV2(db).rollback(
            workflow_id=_workflow_control_id(
                db,
                product_id=product_id,
                payload=payload,
                request=request,
            ),
            step=payload.step,
            scope_context=_scope_context(request),
            user=user,
        )
    except KWorkflowExecutionError as exc:
        raise _workflow_error(exc) from exc
    return ProductKnowledgeWorkflowExecutionRead.model_validate(execution)


@router.get("/keywords/{product_id}", response_model=KeywordListResponse)
def k19_keywords_by_product(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> KeywordListResponse:
    del user
    try:
        product = _product_by_ref(
            db,
            product_ref=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError:
        return KeywordListResponse(keyword_entries=[], timestamp=_now())
    rows = list(
        db.scalars(
            select(KProductKnowledgeKeyword)
            .where(KProductKnowledgeKeyword.product_id == product.id)
            .order_by(KProductKnowledgeKeyword.updated_at.desc())
        )
    )
    return KeywordListResponse(
        keyword_entries=[_keyword_entry(db, row) for row in rows],
        timestamp=_now(),
    )


@router.post(
    "/keywords",
    response_model=KeywordEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
def k19_keyword_create(
    payload: CreateKeywordPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_KEYWORDS_MANAGE)),
) -> KeywordEntryResponse:
    del user
    product = _product_by_ref(
        db,
        product_ref=payload.product_id,
        scope_context=_scope_context(request),
        create_shell=True,
    )
    row = KProductKnowledgeKeyword(
        product_id=product.id,
        keyword_text=payload.keyword.strip(),
        keyword_type="primary",
        language_code="en",
        source=payload.source.strip() or "manual",
        status=_k19_status_to_model(payload.status),
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return KeywordEntryResponse(
        keyword_entry=_keyword_entry(db, row),
        status="created",
        timestamp=_now(),
    )


@router.patch("/keywords/{keyword_id}", response_model=KeywordEntryResponse)
def k19_keyword_update(
    keyword_id: UUID,
    payload: UpdateKeywordPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_KEYWORDS_MANAGE)),
) -> KeywordEntryResponse:
    del user
    row = db.get(KProductKnowledgeKeyword, keyword_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Keyword was not found.")
    if payload.product_id is not None:
        product = _product_by_ref(
            db,
            product_ref=payload.product_id,
            scope_context=_scope_context(request),
            create_shell=True,
        )
        row.product_id = product.id
    if payload.keyword is not None:
        row.keyword_text = payload.keyword.strip()
    if payload.source is not None:
        row.source = payload.source.strip() or row.source
    if payload.status is not None:
        row.status = _k19_status_to_model(payload.status)
    db.add(row)
    db.flush()
    db.refresh(row)
    return KeywordEntryResponse(
        keyword_entry=_keyword_entry(db, row),
        status="updated",
        timestamp=_now(),
    )


@router.delete("/keywords/{keyword_id}", response_model=KeywordEntryResponse)
def k19_keyword_archive(
    keyword_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_KEYWORDS_MANAGE)),
) -> KeywordEntryResponse:
    del user
    row = db.get(KProductKnowledgeKeyword, keyword_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Keyword was not found.")
    row.status = "removed"
    db.add(row)
    db.flush()
    db.refresh(row)
    return KeywordEntryResponse(
        keyword_entry=_keyword_entry(db, row),
        status="archived",
        timestamp=_now(),
    )


@router.get("/risks", response_model=RiskListResponse)
@router.get("/risk", response_model=RiskListResponse)
def k20_risks(
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> RiskListResponse:
    del user
    rows = list(
        db.scalars(
            select(KProductKnowledgeRiskTerm).order_by(
                KProductKnowledgeRiskTerm.updated_at.desc()
            )
        )
    )
    return RiskListResponse(
        risk_terms=[_risk_entry(db, row) for row in rows],
        timestamp=_now(),
    )


@router.post(
    "/risks",
    response_model=RiskTermResponse,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/risk",
    response_model=RiskTermResponse,
    status_code=status.HTTP_201_CREATED,
)
def k20_risk_create(
    payload: CreateRiskPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_RISK_TERMS_MANAGE)),
) -> RiskTermResponse:
    del user
    product = _product_by_ref(
        db,
        product_ref=payload.product_id,
        scope_context=_scope_context(request),
        create_shell=True,
    )
    row = KProductKnowledgeRiskTerm(
        product_id=product.id,
        term_en=payload.term.strip(),
        risk_type=f"{payload.risk_level}:{payload.category}",
        source=payload.source,
        status=_k20_status_to_model(payload.status),
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return RiskTermResponse(risk_term=_risk_entry(db, row), status="created", timestamp=_now())


@router.patch("/risks/{risk_id}", response_model=RiskTermResponse)
@router.patch("/risk/{risk_id}", response_model=RiskTermResponse)
def k20_risk_update(
    risk_id: UUID,
    payload: UpdateRiskPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_RISK_TERMS_MANAGE)),
) -> RiskTermResponse:
    del user
    row = db.get(KProductKnowledgeRiskTerm, risk_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Risk term was not found.")
    if payload.product_id is not None:
        product = _product_by_ref(
            db,
            product_ref=payload.product_id,
            scope_context=_scope_context(request),
            create_shell=True,
        )
        row.product_id = product.id
    if payload.term is not None:
        row.term_en = payload.term.strip()
    entry = _risk_entry(db, row)
    risk_level = payload.risk_level or entry.risk_level
    category = payload.category or entry.category
    row.risk_type = f"{risk_level}:{category}"
    if payload.source is not None:
        row.source = payload.source
    if payload.status is not None:
        row.status = _k20_status_to_model(payload.status)
    db.add(row)
    db.flush()
    db.refresh(row)
    return RiskTermResponse(risk_term=_risk_entry(db, row), status="updated", timestamp=_now())


@router.delete("/risks/{risk_id}", response_model=RiskTermResponse)
@router.delete("/risk/{risk_id}", response_model=RiskTermResponse)
def k20_risk_ignore(
    risk_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_RISK_TERMS_MANAGE)),
) -> RiskTermResponse:
    del user
    row = db.get(KProductKnowledgeRiskTerm, risk_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Risk term was not found.")
    row.status = "false_positive"
    db.add(row)
    db.flush()
    db.refresh(row)
    return RiskTermResponse(risk_term=_risk_entry(db, row), status="ignored", timestamp=_now())


@router.post(
    "/research",
    response_model=ResearchRunResponse,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/keyword-research/start",
    response_model=ResearchRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def k15_keyword_research_start(
    payload: StartResearchRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_KEYWORDS_MANAGE)),
) -> ResearchRunResponse:
    context = _execution_context(
        db,
        request=request,
        user=user,
        key_requirements={"serp": "serp"},
    )
    product = _product_by_ref(
        db,
        product_ref=payload.product_id,
        scope_context=_scope_context(request),
        create_shell=True,
    )
    now = _now()
    row = KProductKnowledgeResearchRun(
        id=uuid4(),
        product_id=product.id,
        run_type="keyword_research",
        status="queued",
        target_market="general",
        target_language="en",
        serp_provider=context.key_for_step("serp").name,
        started_at=now,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return ResearchRunResponse(
        run_id=str(row.id),
        id=str(row.id),
        product_id=_product_public_ref(product),
        status="pending",
        created_at=row.created_at,
        updated_at=row.updated_at,
        source="k15_trigger",
    )


@router.post("/serp/search", response_model=SERPResultResponse)
def k16_serp_search(
    payload: SERPSearchRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_KEYWORDS_MANAGE)),
) -> SERPResultResponse:
    context = _execution_context(
        db,
        request=request,
        user=user,
        key_requirements={"serp": "serp"},
    )
    provider_output = _execute_provider_json(
        db,
        context=context,
        provider="serp",
        task_type="search",
        payload={
            "product_id": payload.product_id,
            "market": payload.market,
            "query": payload.query,
            "module_id": MODULE_KEY,
        },
    )
    organic_results = _organic_results(
        provider_output.get("organic_results")
        or provider_output.get("results")
        or provider_output.get("items")
    )
    if not organic_results:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="SERP provider response did not include organic results.",
        )
    product = _product_by_ref(
        db,
        product_ref=payload.product_id,
        scope_context=_scope_context(request),
        create_shell=True,
    )
    keywords = _safe_string_list(provider_output.get("keywords"))
    competitors = _safe_string_list(
        provider_output.get("competitor_links") or provider_output.get("competitors")
    )
    run = KProductKnowledgeResearchRun(
        id=uuid4(),
        product_id=product.id,
        run_type="serp_search",
        status="succeeded",
        target_market=payload.market,
        target_language="en",
        serp_provider=key.name,
        serp_result_summary_json=provider_output,
        selected_keyword_ids_json=keywords,
        started_at=_now(),
        finished_at=_now(),
    )
    db.add(run)
    db.flush()
    timestamp = _now()
    return SERPResultResponse(
        id=str(run.id),
        product_id=_product_public_ref(product),
        market=payload.market,
        query=payload.query,
        organic_results=organic_results,
        competitor_links=competitors,
        keywords=keywords,
        source=key.name,
        created_at=timestamp,
        updated_at=timestamp,
    )


@router.post("/products/{product_id}/enrich/deepseek", response_model=ProviderExecutionResponse)
def deepseek_enrich_product(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> ProviderExecutionResponse:
    context = _execution_context(
        db,
        request=request,
        user=user,
        key_requirements={"deepseek": "deepseek"},
    )
    product = _product_by_ref(
        db,
        product_ref=product_id,
        scope_context=_scope_context(request),
    )
    provider_output = _execute_provider_json(
        db,
        context=context,
        provider="deepseek",
        task_type="generate",
        payload={
            "product": ProductKnowledgeRead.model_validate(product).model_dump(mode="json"),
            "module_id": MODULE_KEY,
            "task": "deepseek_enrichment",
        },
    )
    product.deepseek_structured_output_json = provider_output
    product.review_status = "ai_structured"
    event = KProductKnowledgeAIEvent(
        id=uuid4(),
        product_id=product.id,
        event_type="deepseek_enrichment",
        provider=key.name,
        input_hash=_source_text_hash(product.raw_input_text or product.product_key),
        output_summary_json={"keys": sorted(provider_output)[:20]},
        output_payload_json=provider_output,
        status="succeeded",
    )
    db.add_all([product, event])
    db.flush()
    return ProviderExecutionResponse(
        status="completed",
        provider=key.name,
        product_id=_product_public_ref(product),
        stored_event_id=str(event.id),
        output=provider_output,
    )


@router.post("/products/{product_id}/translate", response_model=ProviderExecutionResponse)
def translate_product(
    product_id: str,
    request: Request,
    target_language: str = Query(default="zh", min_length=1, max_length=16),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> ProviderExecutionResponse:
    context = _execution_context(
        db,
        request=request,
        user=user,
        key_requirements={"ai_provider": "ai_provider"},
    )
    product = _product_by_ref(
        db,
        product_ref=product_id,
        scope_context=_scope_context(request),
    )
    source_text = product.long_description_en or product.raw_input_text or product.product_key
    provider_output = _execute_provider_json(
        db,
        context=context,
        provider="chatgpt",
        task_type="generate",
        payload={
            "product_id": _product_public_ref(product),
            "source_language": product.canonical_language,
            "target_language": target_language,
            "text": source_text,
            "module_id": MODULE_KEY,
            "task": "bilingual_translation",
        },
    )
    translation = KProductKnowledgeTranslation(
        id=uuid4(),
        product_id=product.id,
        language_code=target_language,
        translation_type="product_content",
        source_text_hash=_source_text_hash(source_text),
        translated_payload_json=provider_output,
        provider=key.name,
        review_status="needs_review",
    )
    db.add(translation)
    db.flush()
    return ProviderExecutionResponse(
        status="completed",
        provider=key.name,
        product_id=_product_public_ref(product),
        stored_event_id=str(translation.id),
        output=provider_output,
    )


@router.post("/products/{product_id}/risk-filter", response_model=ProviderExecutionResponse)
def risk_filter_product(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_RISK_TERMS_MANAGE)),
) -> ProviderExecutionResponse:
    context = _execution_context(
        db,
        request=request,
        user=user,
        key_requirements={"ai_provider": "ai_provider"},
    )
    product = _product_by_ref(
        db,
        product_ref=product_id,
        scope_context=_scope_context(request),
    )
    provider_output = _execute_provider_json(
        db,
        context=context,
        provider="chatgpt",
        task_type="generate",
        payload={
            "product": ProductKnowledgeRead.model_validate(product).model_dump(mode="json"),
            "module_id": MODULE_KEY,
            "task": "risk_filtering",
        },
    )
    for term in provider_output.get("risk_terms", []):
        if not isinstance(term, dict):
            continue
        text = str(term.get("term") or term.get("term_en") or "").strip()
        if not text:
            continue
        db.add(
            KProductKnowledgeRiskTerm(
                id=uuid4(),
                product_id=product.id,
                term_en=text,
                term_zh=term.get("term_zh"),
                risk_type=str(term.get("risk_type") or term.get("category") or "ai:marketing"),
                risk_reason=term.get("risk_reason") or term.get("reason"),
                suggested_action=term.get("suggested_action"),
                source="K13",
                status="candidate",
            )
        )
    event = KProductKnowledgeAIEvent(
        id=uuid4(),
        product_id=product.id,
        event_type="risk_filtering",
        provider=key.name,
        input_hash=_source_text_hash(product.raw_input_text or product.product_key),
        output_summary_json={"risk_terms": len(provider_output.get("risk_terms", []))},
        output_payload_json=provider_output,
        status="succeeded",
    )
    db.add(event)
    db.flush()
    return ProviderExecutionResponse(
        status="completed",
        provider=key.name,
        product_id=_product_public_ref(product),
        stored_event_id=str(event.id),
        output=provider_output,
    )


@router.post("/selling-points/generate", response_model=SellingPointsResponse)
def generate_selling_points(
    payload: GenerateSellingPointsRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> SellingPointsResponse:
    context = _execution_context(
        db,
        request=request,
        user=user,
        key_requirements={"ai_provider": "ai_provider"},
    )
    provider_output = _execute_provider_json(
        db,
        context=context,
        provider="chatgpt",
        task_type="generate",
        payload={
            "product": payload.product,
            "module_id": MODULE_KEY,
            "task": "selling_points",
        },
    )
    try:
        return SellingPointsResponse.model_validate(
            {
                "bullets": provider_output.get("bullets"),
                "seo_keywords": provider_output.get("seo_keywords", []),
                "market_tags": provider_output.get("market_tags", []),
                "confidence_score": provider_output.get("confidence_score", 0),
                "source": key.name,
            }
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider response did not match selling-points schema.",
        ) from exc


@router.get("/media", response_model=MediaAssetListResponse)
def list_media_assets(
    request: Request,
    product_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> MediaAssetListResponse:
    del user
    query = select(KProductKnowledgeMediaAsset).order_by(
        KProductKnowledgeMediaAsset.updated_at.desc()
    )
    if product_id:
        product = _product_by_ref(
            db,
            product_ref=product_id,
            scope_context=_scope_context(request),
        )
        query = query.where(KProductKnowledgeMediaAsset.product_id == product.id)
    rows = list(db.scalars(query))
    items = [
        MediaAssetRead(
            id=str(row.id),
            product_id=str(row.product_id),
            asset_type=row.asset_type,
            asset_role=row.asset_role,
            status=row.status,
            review_status=row.review_status,
            object_key=row.object_key,
            file_url_placeholder=row.file_url_placeholder,
            mime_type=row.mime_type,
            source=row.source,
            metadata=row.metadata_json,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    return MediaAssetListResponse(items=items, count=len(items))


@router.post("/media", response_model=MediaAssetRead, status_code=status.HTTP_201_CREATED)
def create_media_asset(
    payload: MediaAssetCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> MediaAssetRead:
    del user
    if (payload.source or IMAGE_SOURCE_MANUAL) != IMAGE_SOURCE_MANUAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "K series only supports manual image uploads. "
                "AI image generation and AI image review belong to I series."
            ),
        )
    product = _product_by_ref(
        db,
        product_ref=payload.product_id,
        scope_context=_scope_context(request),
        create_shell=True,
    )
    filename = (
        payload.filename
        or (payload.file_url_placeholder or "image").rsplit("/", 1)[-1]
        or "image"
    )
    object_key = f"k-products/{product.product_key}/images/{filename}"
    row = KProductKnowledgeMediaAsset(
        id=uuid4(),
        product_id=product.id,
        asset_type=payload.asset_type,
        asset_role=payload.asset_role,
        status="available",
        review_status="not_applicable",
        object_key=object_key,
        file_url_placeholder=payload.file_url_placeholder,
        mime_type=payload.mime_type,
        source=IMAGE_SOURCE_MANUAL,
        metadata_json={
            **payload.metadata,
            "filename": filename,
            "product_folder": f"k-products/{product.product_key}",
            "source_type": IMAGE_SOURCE_MANUAL,
            "product_key": product.product_key,
            "sku": product.sku,
            "k_image_ai_generation_allowed": False,
            "k_image_review_allowed": False,
        },
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return MediaAssetRead(
        id=str(row.id),
        product_id=_product_public_ref(product),
        asset_type=row.asset_type,
        asset_role=row.asset_role,
        status=row.status,
        review_status=row.review_status,
        object_key=row.object_key,
        file_url_placeholder=row.file_url_placeholder,
        mime_type=row.mime_type,
        source=row.source,
        metadata=row.metadata_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post(
    "/products/{product_id}/images/bind",
    response_model=ProductKnowledgeWorkflowExecutionRead,
)
def bind_product_image(
    product_id: UUID,
    payload: ProductKnowledgeImageBindRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> ProductKnowledgeWorkflowExecutionRead:
    try:
        execution = KWorkflowOrchestratorV2(db).bind_image_asset(
            product_id=product_id,
            payload=payload,
            scope_context=_scope_context(request),
            user=user,
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    except KWorkflowExecutionError as exc:
        raise _workflow_error(exc) from exc
    return ProductKnowledgeWorkflowExecutionRead.model_validate(execution)


@router.get(
    "/media/{asset_id}/download",
    response_model=ProductKnowledgeMediaDownloadResponse,
)
def download_media_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> ProductKnowledgeMediaDownloadResponse:
    del user
    row = db.get(KProductKnowledgeMediaAsset, asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Media asset was not found.")
    filename = None
    if isinstance(row.metadata_json, dict):
        filename = row.metadata_json.get("filename")
    return ProductKnowledgeMediaDownloadResponse(
        asset_id=row.id,
        product_id=row.product_id,
        object_key=row.object_key,
        download_url=row.file_url_placeholder,
        filename=filename,
        review_status=row.review_status,
        status=row.status,
    )
