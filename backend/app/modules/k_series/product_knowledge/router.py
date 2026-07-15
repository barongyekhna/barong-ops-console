"""K product-knowledge API router (single flat file by design for now).

导航索引(行号会漂移,按小节标题/装饰器搜索):
  1. 请求/响应模型          class *Payload / *Response          (~L160-450)
  2. 权限/作用域/幂等 helper _require_k_permission / _scope_*    (~L450-600)
  3. 产品读写 helper         _product_* / _variant_* / _count_*  (~L600-2000)
  4. 产品 CRUD 端点          @router "/products*"                (~L2020-2710)
  5. 关键词/风险词端点        "/keywords*" "/risks*"              (~L2710-3000)
  6. AI 执行端点             "/serp" "/enrich" "/translate"
                             "/selling-points" "/generate-*"     (~L3000-4030)
  7. 渲染/工作流/图片端点     "/render-*" "/workflow/*" "/images/*"(~L4030-4450)
  8. 类目/R搬运/媒体端点      "/categories" "/import-from-r"
                             "/media*"                           (~L4450-EOF)

拆分计划: 按上述小节拆为子模块 + 聚合 router。因 feature/k-series-
product-knowledge 分支(K21 操作日志系统)尚有 100+ 未合并提交且改动本文件,
拆分推迟到该分支合并后执行,避免制造合并冲突。(2026-07-11 批次3 决定)
"""

from __future__ import annotations

import hashlib
import base64
import json
import logging
import os
import re
from collections.abc import Sequence
from pathlib import Path
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from ....api.deps import get_current_user
from ....core.roles import is_super_admin_role
from ....db.session import SessionLocal, get_db
from ....models.user import User
from ....services.api_key_orchestration import ApiKeyIsolationError
from ....services.ai_provider_router import AIExecutionRouter, AIProviderExecutionError
from ....services.module_execution_gate import (
    API_KEY_BINDING_MISSING_CODE,
    API_KEY_INJECTION_FAILED_CODE,
    MODULE_DISABLED_CODE,
    MODULE_NOT_REGISTERED_CODE,
    ModuleExecutionContext,
    ModuleExecutionGateError,
    ORG_CONTEXT_REQUIRED_CODE,
    require_module_execution_ready,
)
from ....services.permission_service import resolve_current_user_permission_info
from ....services.media_store import (
    DERIVED_IMAGE_CACHE_CONTROL,
    INLINE_IMAGE_CACHE_CONTROL,
    ensure_image_derivative,
    media_file_etag,
    write_media_file,
)
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
    KProductKnowledgeVariant,
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
    ProductKnowledgeVariantRead,
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
    delete_product,
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
    IMAGE_SOURCE_I_SYSTEM,
    KWorkflowOrchestratorV2,
    KWorkflowExecutionError,
    _user_uuid,
)
from ....services.module_execution_gate import ModuleExecutionGateError
from .generation_jobs import enqueue_generation_jobs, jobs_status
from .image_render_jobs import (
    KImageRenderError,
    download_reference_image,
    enqueue_image_render_jobs,
    enqueue_rework_job,
    list_render_assets,
    render_jobs_status,
    retry_failed_render_jobs,
    save_render_assets,
)
from .r_to_k_transfer import transfer_from_rw
from .prompt_skills import (
    SELLING_POINTS_SKILL_VERSION,
    selling_points_instruction,
    selling_points_skill_context,
)

router = APIRouter(prefix="/k", tags=["k-product-knowledge"])
logger = logging.getLogger(__name__)

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
    main_keyword: str | None = Field(default=None, max_length=512)


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
    marketing_copy: str | None = None
    translated_version: str | None = None
    chinese_translation: str | None = None
    target_language: str | None = None
    product_id: str | None = None
    stored_event_id: str | None = None


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


class GenerateSellingPointsRequest(BaseModel):
    product: dict[str, Any] = Field(default_factory=dict)
    mode: str | None = None


class ApproveSellingPointsRequest(BaseModel):
    bullets: list[SellingPointBullet] = Field(min_length=1)
    seo_keywords: list[str] = Field(default_factory=list)
    market_tags: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str | None = Field(default="manual_review", max_length=100)
    marketing_copy: str | None = None
    translated_version: str | None = None
    chinese_translation: str | None = None
    target_language: str | None = Field(default=None, max_length=32)


class ProductDeleteRequest(BaseModel):
    product_key: str = Field(min_length=1, max_length=128)


class ProductDeleteResponse(BaseModel):
    status: Literal["deleted"] = "deleted"
    product_id: str
    product_key: str
    deleted_counts: dict[str, int]


class MediaAssetCreate(BaseModel):
    product_id: str = Field(min_length=1)
    variant_sku: str = Field(min_length=1, max_length=180)
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
    variant_sku: str | None
    asset_type: str
    asset_role: str
    status: str
    review_status: str
    object_key: str | None
    file_url_placeholder: str | None
    file_url: str | None
    thumbnail_url: str | None
    preview_url: str | None
    mime_type: str | None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    source: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class MediaAssetListResponse(BaseModel):
    items: list[MediaAssetRead]
    count: int


class ISystemImageImportItem(BaseModel):
    image_base64: str = Field(min_length=1)
    mime_type: str = Field(default="image/png", max_length=100)
    width: int | None = Field(default=None, ge=1, le=8192)
    height: int | None = Field(default=None, ge=1, le=8192)
    content_sha256: str | None = Field(default=None, max_length=64)
    candidate_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ISystemImageImportRequest(BaseModel):
    variant_id: UUID
    source_type: Literal["generate", "edit"]
    image_prompt_enhanced: str = Field(min_length=1, max_length=12000)
    prompt_original: str | None = Field(default=None, max_length=8000)
    aspect_ratio: str | None = Field(default=None, max_length=16)
    style_config: dict[str, Any] = Field(default_factory=dict)
    event_id: UUID | None = None
    images: list[ISystemImageImportItem] = Field(min_length=1, max_length=8)


class ISystemImageImportResponse(BaseModel):
    status: Literal["saved"] = "saved"
    product_id: UUID
    variant_id: UUID
    variant_sku: str
    asset_ids: list[UUID]
    submitted: bool
    submit_status: str
    message: str | None = None


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
        if (
            permissions.is_owner_full_access
            or is_super_admin_role(user.role)
            or allowed_permission_keys.intersection(permissions.permission_keys)
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


def _product_create_idempotency_cache_key(
    request: Request,
    *,
    fingerprint: str,
    scope_context: KScopeContext,
    user: User,
) -> str:
    supplied_key = (request.headers.get("idempotency-key") or "").strip()
    key = supplied_key or f"auto:{fingerprint}"
    raw = _canonical_payload(
        {
            "business_context": scope_context.business_context,
            "key": key,
            "scope_mode": scope_context.scope_mode,
            "user_id": str(user.id),
            "workspace_key": scope_context.workspace_key,
        }
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def _product_variants_by_product_ids(
    db: Session,
    product_ids: Sequence[UUID],
) -> dict[UUID, list[KProductKnowledgeVariant]]:
    if not product_ids:
        return {}

    grouped: dict[UUID, list[KProductKnowledgeVariant]] = {
        product_id: [] for product_id in product_ids
    }
    variants = db.scalars(
        select(KProductKnowledgeVariant)
        .where(KProductKnowledgeVariant.product_id.in_(product_ids))
        .order_by(
            KProductKnowledgeVariant.product_id.asc(),
            KProductKnowledgeVariant.created_at.asc(),
        )
    )
    for variant in variants:
        grouped.setdefault(variant.product_id, []).append(variant)
    return grouped


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


def _product_list_item(
    db: Session,
    product: KProductKnowledgeProduct,
    variants: list[KProductKnowledgeVariant] | None = None,
) -> ProductKnowledgeListItem:
    if variants is None:
        variants = _product_variants(db, product)
    return ProductKnowledgeListItem.model_validate(product).model_copy(
        update={
            "main_keyword": product.primary_keyword,
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
        parent_sku=normalized,
        sku=normalized,
        source_system="k_adapter",
    )
    db.add(product)
    default_variant_sku = f"{normalized}-SHELL"
    db.add(
        KProductKnowledgeVariant(
            id=uuid4(),
            product_id=product.id,
            parent_sku=normalized,
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


def _variant_by_id(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    variant_id: UUID,
) -> KProductKnowledgeVariant:
    variant = db.get(KProductKnowledgeVariant, variant_id)
    if variant is None or variant.product_id != product.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant was not found for this product.",
        )
    return variant


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


def _is_execution_configuration_error(code: str | None) -> bool:
    return code in {
        API_KEY_BINDING_MISSING_CODE,
        API_KEY_INJECTION_FAILED_CODE,
        MODULE_DISABLED_CODE,
        MODULE_NOT_REGISTERED_CODE,
        ORG_CONTEXT_REQUIRED_CODE,
    }


def _execution_configuration_message() -> str:
    return (
        "K module execution is not fully configured. The current user permission "
        "is valid, but the module requires an active organization context and "
        "usable API key binding."
    )


def _execution_error_reason(code: str | None) -> str:
    if code == API_KEY_BINDING_MISSING_CODE:
        return "missing_key"
    if code == API_KEY_INJECTION_FAILED_CODE:
        return "key_resolution_failed"
    if code == ORG_CONTEXT_REQUIRED_CODE:
        return "missing_context"
    if code == MODULE_DISABLED_CODE:
        return "module_disabled"
    if code == MODULE_NOT_REGISTERED_CODE:
        return "module_not_registered"
    return "execution_error"


def _structured_execution_error_detail(
    *,
    reason: str,
    message: str,
    code: str | None = None,
    module_id: str | None = None,
    org_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "status": "failed",
        "reason": reason,
        "message": message,
    }
    if code is not None:
        detail["code"] = code
    if module_id is not None:
        detail["module_id"] = module_id
    if org_id is not None:
        detail["org_id"] = org_id
    if extra:
        detail.update(extra)
    return detail


def _gate_error(exc: ModuleExecutionGateError) -> HTTPException:
    is_configuration_error = _is_execution_configuration_error(exc.code)
    status_code = status.HTTP_400_BAD_REQUEST if exc.code == ORG_CONTEXT_REQUIRED_CODE else (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if is_configuration_error
        else exc.status_code
    )
    message = (
        _execution_configuration_message()
        if is_configuration_error
        else str(exc)
    )
    return HTTPException(
        status_code=status_code,
        detail=_structured_execution_error_detail(
            reason=_execution_error_reason(exc.code),
            code=exc.code,
            message=message,
            module_id=exc.module_id,
            org_id=exc.org_id,
        ),
    )


def _workflow_error(exc: KWorkflowExecutionError) -> HTTPException:
    code = exc.error_report.get("code") if isinstance(exc.error_report, dict) else None
    if _is_execution_configuration_error(code if isinstance(code, str) else None):
        detail = dict(exc.error_report)
        detail.setdefault("status", "failed")
        detail.setdefault("reason", _execution_error_reason(code if isinstance(code, str) else None))
        detail["message"] = _execution_configuration_message()
        return HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
                if code == ORG_CONTEXT_REQUIRED_CODE
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=detail,
        )
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
    del db
    provider_db = SessionLocal()
    try:
        return AIExecutionRouter(provider_db).execute(
            provider=provider,
            task_type=task_type,  # type: ignore[arg-type]
            payload=payload,
            org=TARGET_ORGANIZATION_NAME,
            module_id=MODULE_KEY,
            execution_context=context,
        )
    except AIProviderExecutionError as exc:
        provider_detail = exc.structured_error()
        extra = provider_detail if isinstance(provider_detail, dict) else None
        raise HTTPException(
            status_code=exc.status_code,
            detail=_structured_execution_error_detail(
                reason="provider_error",
                code=exc.code,
                message=str(exc),
                module_id=MODULE_KEY,
                org_id=context.org_id,
                extra={"provider_error": extra} if extra else None,
            ),
        ) from exc
    except Exception as exc:
        logger.exception("K provider execution failed provider=%s", provider)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_structured_execution_error_detail(
                reason="provider_error",
                code="PROVIDER_EXECUTION_FAILED",
                message="Provider execution failed.",
                module_id=MODULE_KEY,
                org_id=context.org_id,
                extra={"provider": provider},
            ),
        ) from exc
    finally:
        provider_db.close()


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _strict_json_messages(
    *,
    instruction: str,
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True),
        },
    ]


def _safe_filename(value: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "image").strip())
    cleaned = cleaned.strip(".-_")
    return cleaned[:180] or "image"


def _media_storage_root() -> Path:
    return Path(os.getenv("K_PRODUCT_MEDIA_STORAGE_DIR", "/var/lib/barong/k-media"))


SUPPORTED_IMAGE_MIME_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}

RESERVED_MEDIA_METADATA_KEYS = {
    "content_sha256",
    "db_content_base64",
    "direct_binary_upload",
    "preview_path",
    "storage_path",
    "storage_provider",
    "storage_relative_path",
    "thumbnail_path",
}


def _detect_image_mime(contents: bytes) -> str | None:
    if contents.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contents.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if (
        len(contents) >= 12
        and contents[0:4] == b"RIFF"
        and contents[8:12] == b"WEBP"
    ):
        return "image/webp"
    return None


def _validate_uploaded_image(contents: bytes, declared_mime: str | None) -> str:
    detected_mime = _detect_image_mime(contents)
    if detected_mime is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is not a supported image.",
        )
    normalized_declared = (declared_mime or "").split(";", 1)[0].strip().lower()
    if normalized_declared and normalized_declared not in {
        detected_mime,
        "application/octet-stream",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image MIME type does not match the file contents.",
        )
    return detected_mime


def _decode_image_base64(value: str) -> bytes:
    raw = value.strip()
    if raw.startswith("data:"):
        _, _, raw = raw.partition(",")
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image payload is not valid base64.",
        ) from exc


def _db_image_bytes_from_metadata(row: KProductKnowledgeMediaAsset) -> bytes | None:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    encoded = metadata.get("db_content_base64")
    if not isinstance(encoded, str) or not encoded.strip():
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except Exception:
        return None


def _safe_media_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key not in RESERVED_MEDIA_METADATA_KEYS
    }


def _public_media_metadata(metadata: Any) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    redacted = {
        key: value
        for key, value in metadata.items()
        if key not in {"db_content_base64", "storage_path", "thumbnail_path", "preview_path"}
    }
    return redacted


def _path_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _media_asset_local_path(row: KProductKnowledgeMediaAsset) -> Path | None:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    root = _media_storage_root().resolve(strict=False)
    candidates: list[Path] = []
    storage_path_value = metadata.get("storage_path")
    if (
        row.storage_provider == "local_filesystem"
        or metadata.get("storage_provider") == "local_filesystem"
    ) and storage_path_value:
        candidates.append(Path(str(storage_path_value)))
    if row.object_key:
        candidates.append(root / row.object_key)

    for candidate in candidates:
        path = candidate if candidate.is_absolute() else root / candidate
        resolved = path.resolve(strict=False)
        if _path_within_root(resolved, root):
            return resolved
    return None


def _write_k_media_file(object_key: str, contents: bytes) -> Path:
    try:
        return write_media_file(_media_storage_root(), object_key, contents)
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=507,
            detail="K media storage is not writable.",
        ) from exc


def _ensure_media_asset_file(row: KProductKnowledgeMediaAsset) -> Path:
    path = _media_asset_local_path(row)
    if path is not None and path.is_file():
        return path
    db_contents = _db_image_bytes_from_metadata(row)
    if db_contents is not None and row.object_key:
        path = _write_k_media_file(row.object_key, db_contents)
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        row.storage_provider = "local_filesystem"
        row.file_size = row.file_size or len(db_contents)
        row.metadata_json = {
            **{
                key: value
                for key, value in metadata.items()
                if key != "db_content_base64"
            },
            "storage_provider": "local_filesystem",
            "storage_relative_path": row.object_key,
            "storage_path": str(path),
        }
        return path
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Media file was not found.",
    )


def _ensure_media_asset_derivative(
    row: KProductKnowledgeMediaAsset,
    *,
    kind: str,
    max_side: int,
) -> Path:
    if not row.object_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file was not found.",
        )
    _ensure_media_asset_file(row)
    path, object_key, _media_type = ensure_image_derivative(
        root=_media_storage_root(),
        object_key=row.object_key,
        kind=kind,
        max_side=max_side,
    )
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    key_name = f"{kind}_object_key"
    if metadata.get(key_name) != object_key:
        row.metadata_json = {**metadata, key_name: object_key}
    return path


def _media_asset_requires_local_file(row: KProductKnowledgeMediaAsset) -> bool:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    return (
        row.storage_provider == "local_filesystem"
        or metadata.get("storage_provider") == "local_filesystem"
        or metadata.get("direct_binary_upload") is True
    )


def _media_asset_file_info(row: KProductKnowledgeMediaAsset) -> dict[str, Any]:
    path = _media_asset_local_path(row)
    if path is None:
        return {"file_available": False, "file_size": None}
    try:
        stat = path.stat()
    except OSError:
        return {"file_available": False, "file_size": None}
    return {
        "file_available": path.is_file(),
        "file_size": stat.st_size if path.is_file() else None,
    }


def _product_full_ai_payload(
    db: Session,
    product: KProductKnowledgeProduct,
) -> dict[str, Any]:
    variants = [
        ProductKnowledgeVariantRead.model_validate(variant).model_dump(mode="json")
        for variant in _product_variants(db, product)
    ]
    attributes = [
        {
            "attribute_key": row.attribute_key,
            "attribute_value_text": row.attribute_value_text,
            "attribute_value_json": row.attribute_value_json,
            "attribute_unit": row.attribute_unit,
            "attribute_group": row.attribute_group,
            "source": row.source,
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
        "attributes": attributes,
        "variants": variants,
        "keywords": keywords,
        "risk_terms": risk_terms,
        "dimensions": product.dimensions_json,
        "weight": product.weight_json,
        "price": {
            "regular_price": str(product.regular_price)
            if product.regular_price is not None
            else None,
            "currency": product.price_currency,
        },
    }


def _normalize_selling_points_response(
    provider_output: dict[str, Any],
    *,
    product: KProductKnowledgeProduct | None = None,
    source: str,
    stored_event_id: UUID | None = None,
) -> SellingPointsResponse:
    def _first_present_from(record: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = record.get(key)
            if value:
                return value
        return None

    def _first_present(*keys: str) -> Any:
        return _first_present_from(provider_output, *keys)

    raw_bullets = _first_present(
        "bullets",
        "selling_points",
        "high_conversion_selling_points",
        "structured_bullet_points",
        "bullet_points",
        "conversion_selling_points",
        "conversion_bullets",
        "value_propositions",
        "卖点",
        "转化卖点",
    ) or []
    if isinstance(raw_bullets, dict):
        raw_bullets = _first_present_from(
            raw_bullets,
            "items",
            "bullets",
            "points",
            "selling_points",
            "structured_bullet_points",
        ) or list(raw_bullets.values())
    bullets: list[SellingPointBullet] = []
    if isinstance(raw_bullets, list):
        for index, raw in enumerate(raw_bullets, start=1):
            if isinstance(raw, dict):
                text = str(
                    raw.get("text")
                    or raw.get("copy")
                    or raw.get("point")
                    or raw.get("headline")
                    or raw.get("benefit")
                    or raw.get("value_proposition")
                    or raw.get("卖点")
                    or raw.get("文案")
                    or ""
                ).strip()
                category = str(
                    raw.get("category")
                    or raw.get("type")
                    or raw.get("theme")
                    or raw.get("类别")
                    or "conversion"
                ).strip()
                score_raw = (
                    raw.get("importance_score")
                    or raw.get("score")
                    or raw.get("priority")
                    or raw.get("权重")
                    or 1
                )
            else:
                text = str(raw).strip()
                category = "conversion"
                score_raw = index
            if not text:
                continue
            try:
                score = float(score_raw)
            except (TypeError, ValueError):
                score = float(index)
            bullets.append(
                SellingPointBullet(
                    category=category or "conversion",
                    text=text,
                    importance_score=score,
                )
            )
    if not bullets and isinstance(provider_output.get("content"), str):
        bullets.append(
            SellingPointBullet(
                category="marketing",
                text=str(provider_output["content"]).strip(),
                importance_score=1,
            )
        )
    if not bullets:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_structured_execution_error_detail(
                reason="provider_error",
                code="SELLING_POINTS_EMPTY",
                message="DeepSeek selling points response did not include usable bullet points.",
                module_id=MODULE_KEY,
            ),
        )

    confidence_raw = provider_output.get("confidence_score") or provider_output.get("confidence") or 0.8
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except (TypeError, ValueError):
        confidence = 0.8
    return SellingPointsResponse(
        bullets=bullets,
        seo_keywords=_safe_string_list(
            _first_present("seo_keywords", "keywords", "search_keywords", "关键词")
        ),
        market_tags=_safe_string_list(
            _first_present("market_tags", "tags", "audience_tags", "市场标签")
        ),
        confidence_score=confidence,
        source=source,
        marketing_copy=(
            _first_present("marketing_copy", "copy", "conversion_copy", "营销文案")
            if isinstance(
                _first_present("marketing_copy", "copy", "conversion_copy", "营销文案"),
                str,
            )
            else None
        ),
        translated_version=(
            _first_present("translated_version", "localized_copy", "translation")
            if isinstance(
                _first_present("translated_version", "localized_copy", "translation"),
                str,
            )
            else None
        ),
        chinese_translation=(
            _first_present(
                "chinese_translation",
                "zh_translation",
                "translated_version_zh",
                "chinese_version",
                "中文翻译",
                "中文版本",
            )
            if isinstance(
                _first_present(
                    "chinese_translation",
                    "zh_translation",
                    "translated_version_zh",
                    "chinese_version",
                    "中文翻译",
                    "中文版本",
                ),
                str,
            )
            else None
        ),
        target_language=(
            str(provider_output.get("target_language"))
            if provider_output.get("target_language")
            else product.canonical_language if product else None
        ),
        product_id=str(product.id) if product else None,
        stored_event_id=str(stored_event_id) if stored_event_id else None,
    )


def _media_asset_read(
    row: KProductKnowledgeMediaAsset,
    *,
    product_ref: str | None = None,
    include_metadata: bool = False,
) -> MediaAssetRead:
    file_url = (
        row.file_url_placeholder
        if row.file_url_placeholder and not row.object_key
        else f"/k/media/{row.id}/file"
    )
    thumbnail_url = (
        row.file_url_placeholder
        if row.file_url_placeholder and not row.object_key
        else f"/k/media/{row.id}/thumbnail"
    )
    preview_url = (
        row.file_url_placeholder
        if row.file_url_placeholder and not row.object_key
        else f"/k/media/{row.id}/preview"
    )
    return MediaAssetRead(
        id=str(row.id),
        product_id=product_ref or str(row.product_id),
        variant_sku=row.variant_sku,
        asset_type=row.asset_type,
        asset_role=row.asset_role,
        status=row.status,
        review_status=row.review_status,
        object_key=row.object_key,
        file_url_placeholder=row.file_url_placeholder,
        file_url=file_url,
        thumbnail_url=thumbnail_url,
        preview_url=preview_url,
        mime_type=row.mime_type,
        width=row.width,
        height=row.height,
        file_size=row.file_size,
        source=row.source,
        metadata=_public_media_metadata(row.metadata_json) if include_metadata else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


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


def _stable_payload_digest(value: Any) -> str:
    return _source_text_hash(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    )


def _product_ai_warnings(product: KProductKnowledgeProduct) -> dict[str, Any]:
    return (
        dict(product.ai_warnings_json)
        if isinstance(product.ai_warnings_json, dict)
        else {}
    )


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


def _active_media_snapshot(
    db: Session,
    product: KProductKnowledgeProduct,
) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(KProductKnowledgeMediaAsset)
            .where(
                KProductKnowledgeMediaAsset.product_id == product.id,
                KProductKnowledgeMediaAsset.status != "removed",
            )
            .order_by(
                KProductKnowledgeMediaAsset.variant_sku.asc(),
                KProductKnowledgeMediaAsset.object_key.asc(),
                KProductKnowledgeMediaAsset.id.asc(),
            )
        )
    )
    items = []
    usable_count = 0
    for row in rows:
        file_info = _media_asset_file_info(row)
        requires_local_file = _media_asset_requires_local_file(row)
        file_available = (
            file_info["file_available"]
            if requires_local_file
            else bool(row.file_url_placeholder or row.object_key)
        )
        if file_available:
            usable_count += 1
        items.append(
            {
                "asset_role": row.asset_role,
                "asset_type": row.asset_type,
                "file_available": file_available,
                "file_size": file_info["file_size"] or row.file_size,
                "id": str(row.id),
                "object_key": row.object_key,
                "review_status": row.review_status,
                "source": row.source,
                "status": row.status,
                "storage_provider": row.storage_provider,
                "variant_sku": row.variant_sku,
            }
        )
    payload = {"active_count": len(items), "count": usable_count, "items": items}
    return {**payload, "digest": _stable_payload_digest(payload)}


def _stored_selling_points_payload(
    product: KProductKnowledgeProduct,
) -> dict[str, Any] | None:
    payload = _product_ai_warnings(product).get("selling_points")
    return payload if isinstance(payload, dict) else None


def _selling_points_snapshot(product: KProductKnowledgeProduct) -> dict[str, Any]:
    payload = _stored_selling_points_payload(product)
    if payload is None:
        empty = {"count": 0, "payload": None}
        return {**empty, "digest": _stable_payload_digest(empty)}
    bullets = payload.get("bullets")
    count = len(bullets) if isinstance(bullets, list) else 0
    stable_payload = {
        "bullets": bullets if isinstance(bullets, list) else [],
        "chinese_translation": payload.get("chinese_translation"),
        "confidence_score": payload.get("confidence_score"),
        "market_tags": _safe_string_list(payload.get("market_tags")),
        "marketing_copy": payload.get("marketing_copy"),
        "product_id": str(product.id),
        "seo_keywords": _safe_string_list(payload.get("seo_keywords")),
        "source": payload.get("source"),
        "target_language": payload.get("target_language"),
        "translated_version": payload.get("translated_version"),
    }
    snapshot_payload = {"count": count, "payload": stable_payload}
    return {
        **snapshot_payload,
        "digest": _stable_payload_digest(snapshot_payload),
    }


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


def _store_keyword_review_snapshot(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    execution: Any | None = None,
    user: User | None = None,
) -> ProductSectionState:
    snapshot = _active_keyword_snapshot(db, product)
    if int(snapshot.get("count") or 0) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_structured_execution_error_detail(
                reason="invalid_state",
                code="KEYWORD_SECTION_INCOMPLETE",
                message="At least one active non-risk keyword is required before submitting keywords.",
                module_id=MODULE_KEY,
            ),
        )
    reviewed_at = _now().isoformat()
    marker = {
        "status": "submitted",
        "submitted_at": reviewed_at,
        "keyword_digest": snapshot["digest"],
        "keyword_count": snapshot["count"],
        "submitted_by_user_id": (
            str(_user_uuid(user)) if user is not None and _user_uuid(user) else None
        ),
    }
    if execution is not None:
        marker["execution_id"] = str(execution.id)
    product.ai_warnings_json = {**_product_ai_warnings(product), "keyword_review": marker}
    if execution is not None and isinstance(execution.risk_approval_log_json, dict):
        execution.risk_approval_log_json = {
            **execution.risk_approval_log_json,
            "keyword_digest": snapshot["digest"],
            "keyword_count": snapshot["count"],
        }
        db.add_all([product, execution])
    else:
        db.add(product)
    db.flush()
    return _product_readiness(db, product).keywords


def _store_image_review_snapshot(
    db: Session,
    *,
    product: KProductKnowledgeProduct,
    user: User,
) -> ProductSectionState:
    snapshot = _active_media_snapshot(db, product)
    if int(snapshot.get("count") or 0) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_structured_execution_error_detail(
                reason="missing_context",
                code="IMAGE_SECTION_INCOMPLETE",
                message="At least 5 active images are required before submitting images.",
                module_id=MODULE_KEY,
            ),
        )
    submitted_at = _now().isoformat()
    product.ai_warnings_json = {
        **_product_ai_warnings(product),
        "image_review": {
            "status": "submitted",
            "submitted_at": submitted_at,
            "submitted_by_user_id": str(_user_uuid(user)) if _user_uuid(user) else None,
            "media_digest": snapshot["digest"],
            "media_count": snapshot["count"],
        },
    }
    db.add(product)
    db.flush()
    return _product_readiness(db, product).images


def _selling_points_response_from_payload(
    product: KProductKnowledgeProduct,
    payload: dict[str, Any],
) -> SellingPointsResponse:
    return SellingPointsResponse(
        bullets=[
            SellingPointBullet.model_validate(bullet)
            for bullet in payload.get("bullets", [])
            if isinstance(bullet, dict)
        ],
        seo_keywords=_safe_string_list(payload.get("seo_keywords")),
        market_tags=_safe_string_list(payload.get("market_tags")),
        confidence_score=float(payload.get("confidence_score") or 1),
        source=str(payload.get("source") or "manual_review"),
        marketing_copy=(
            str(payload["marketing_copy"])
            if isinstance(payload.get("marketing_copy"), str)
            else None
        ),
        translated_version=(
            str(payload["translated_version"])
            if isinstance(payload.get("translated_version"), str)
            else None
        ),
        chinese_translation=(
            str(payload["chinese_translation"])
            if isinstance(payload.get("chinese_translation"), str)
            else None
        ),
        target_language=(
            str(payload["target_language"])
            if isinstance(payload.get("target_language"), str)
            else product.canonical_language
        ),
        product_id=str(product.id),
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
    variants_by_product_id = _product_variants_by_product_ids(
        db,
        [item.id for item in items],
    )
    return ProductKnowledgeListResponse(
        items=[
            _product_list_item(
                db,
                item,
                variants_by_product_id.get(item.id, []),
            )
            for item in items
        ],
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
    scope_context = _scope_context(request)
    fingerprint = _product_create_fingerprint(payload, scope_context)
    cache_key = _product_create_idempotency_cache_key(
        request,
        fingerprint=fingerprint,
        scope_context=scope_context,
        user=user,
    )
    record: ProductCreateIdempotencyRecord | None = None
    try:
        record = _claim_product_create_idempotency(
            cache_key=cache_key,
            fingerprint=fingerprint,
        )
        if record.product_id is not None:
            try:
                product = get_product(
                    db,
                    product_id=record.product_id,
                    scope_context=scope_context,
                )
                return _product_read(db, product)
            except KProductKnowledgeError:
                _discard_product_create_idempotency(
                    cache_key=cache_key,
                    record=record,
                )

        product = create_product(
            db,
            payload=payload,
            scope_context=scope_context,
        )
        _complete_product_create_idempotency(
            cache_key=cache_key,
            record=record,
            product_id=product.id,
        )
    except KProductKnowledgeError as exc:
        if record is not None and record.product_id is None:
            _discard_product_create_idempotency(
                cache_key=cache_key,
                record=record,
            )
        _raise_k_error(exc)
    finally:
        if record is not None:
            record.lock.release()
    return _product_read(db, product)


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
        raise
    return _product_read(db, product)


@router.get(
    "/products/{product_id}/readiness",
    response_model=ProductReadinessResponse,
)
def product_knowledge_readiness(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> ProductReadinessResponse:
    del user
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return _product_readiness(db, product)


@router.patch("/products/{product_id}", response_model=ProductKnowledgeRead)
def product_knowledge_update(
    product_id: UUID,
    payload: ProductKnowledgeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> ProductKnowledgeRead:
    del user
    if payload.review_status == "approved":
        try:
            product = get_product(
                db,
                product_id=product_id,
                scope_context=_scope_context(request),
            )
        except KProductKnowledgeError as exc:
            _raise_k_error(exc)
        _ensure_product_ready_for_approval(db, product)
    try:
        product = update_product(
            db,
            product_id=product_id,
            payload=payload,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return _product_read(db, product)


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
    return _product_read(db, product)


@router.delete("/products/{product_id}", response_model=ProductDeleteResponse)
def product_knowledge_delete(
    product_id: UUID,
    request: Request,
    payload: ProductDeleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_ARCHIVE)),
) -> ProductDeleteResponse:
    del user
    try:
        deleted_counts = delete_product(
            db,
            product_id=product_id,
            product_key=payload.product_key,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return ProductDeleteResponse(
        product_id=str(product_id),
        product_key=payload.product_key,
        deleted_counts=deleted_counts,
    )


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


@router.post(
    "/products/{product_id}/keywords/submit",
    response_model=ProductSectionState,
)
def product_knowledge_keywords_submit(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_KEYWORDS_MANAGE)),
) -> ProductSectionState:
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    section_state = _store_keyword_review_snapshot(db, product=product, user=user)
    db.commit()
    return section_state


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
    except Exception as exc:
        logger.exception(
            "K workflow start failed after resilience layer: product_id=%s",
            product_id,
        )
        try:
            db.rollback()
        except Exception:
            logger.exception(
                "K workflow start rollback failed: product_id=%s",
                product_id,
            )
        try:
            execution = KWorkflowOrchestratorV2(db).latest_execution_for_product(
                product_id=product_id,
                scope_context=_scope_context(request),
            )
        except Exception:
            logger.exception(
                "K workflow start partial state reload failed: product_id=%s",
                product_id,
            )
            execution = None
        if execution is not None:
            return ProductKnowledgeWorkflowExecutionRead.model_validate(execution)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "K_WORKFLOW_START_UNAVAILABLE",
                "message": "K workflow start could not complete, and no partial workflow state was available.",
                "product_id": str(product_id),
                "raw_error_class": exc.__class__.__name__,
            },
        ) from exc
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
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    _store_keyword_review_snapshot(db, product=product, execution=execution)
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
    try:
        product = _product_by_ref(
            db,
            product_ref=payload.product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_structured_execution_error_detail(
                reason="missing_context",
                code="PRODUCT_CONTEXT_MISSING",
                message=str(exc),
                module_id=MODULE_KEY,
            ),
        ) from exc

    context = _execution_context(
        db,
        request=request,
        user=user,
        key_requirements={"serp": "serp"},
    )
    key = context.key_for_step("serp")
    main_keyword = (payload.main_keyword or product.primary_keyword or "").strip()
    if not context.org_id or not product.product_key or not payload.market or not main_keyword:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_structured_execution_error_detail(
                reason="missing_context",
                code="PRODUCT_CONTEXT_INCOMPLETE",
                message="SERP execution requires product_id, product_key, target_market, main_keyword, and org_id.",
                module_id=MODULE_KEY,
                org_id=context.org_id,
                extra={
                    "missing": [
                        field
                        for field, present in {
                            "product_id": bool(product.id),
                            "product_key": bool(product.product_key),
                            "target_market": bool(payload.market),
                            "main_keyword": bool(main_keyword),
                            "org_id": bool(context.org_id),
                        }.items()
                        if not present
                    ],
                },
            ),
        )
    product_context = {
        "org_id": context.org_id,
        "product_id": str(product.id),
        "product_key": product.product_key,
        "target_market": payload.market,
        "main_keyword": main_keyword,
    }
    provider_output = _execute_provider_json(
        db,
        context=context,
        provider="serp",
        task_type="search",
        payload={
            "product_context": product_context,
            "product_id": product_context["product_id"],
            "product_key": product_context["product_key"],
            "org_id": product_context["org_id"],
            "market": payload.market,
            "main_keyword": main_keyword,
            "query": main_keyword,
            "requested_query": payload.query,
            "target_market": payload.market,
            "module_id": MODULE_KEY,
        },
    )
    organic_results = _organic_results(
        provider_output.get("organic_results")
        or provider_output.get("organic")
        or provider_output.get("results")
        or provider_output.get("items")
    )
    if not organic_results:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_structured_execution_error_detail(
                reason="provider_error",
                code="SERP_ORGANIC_RESULTS_MISSING",
                message="SERP provider response did not include organic results.",
                module_id=MODULE_KEY,
                org_id=context.org_id,
            ),
        )
    product = db.merge(product)
    db.flush()
    db.refresh(product)
    product = _product_by_ref(
        db,
        product_ref=str(product.id),
        scope_context=_scope_context(request),
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
        query=main_keyword,
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
    key = context.key_for_step("deepseek")
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
    key = context.key_for_step("ai_provider")
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
    key = context.key_for_step("ai_provider")
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
        key_requirements={"deepseek": "deepseek"},
    )
    key = context.key_for_step("deepseek")
    db.rollback()
    ai_payload = {
        "product": payload.product,
        "module_id": MODULE_KEY,
        "task": "selling_points",
        "selling_points_skill": selling_points_skill_context(),
        "required_output": [
            "high_conversion_selling_points",
            "structured_bullet_points",
            "marketing_optimized_copy",
            "translated_version",
            "chinese_translation",
        ],
    }
    ai_payload["messages"] = _strict_json_messages(
        instruction=selling_points_instruction(),
        payload=ai_payload,
    )
    provider_output = _execute_provider_json(
        db,
        context=context,
        provider="deepseek",
        task_type="selling_points",
        payload=ai_payload,
    )
    try:
        return _normalize_selling_points_response(
            provider_output,
            source=key.name,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_structured_execution_error_detail(
                reason="provider_error",
                code="AI_RESPONSE_SCHEMA_MISMATCH",
                message="AI provider response did not match selling-points schema.",
                module_id=MODULE_KEY,
                org_id=context.org_id,
                extra={"provider": key.name},
            ),
        ) from exc


@router.post(
    "/products/{product_id}/selling-points/generate",
    response_model=SellingPointsResponse,
)
def generate_product_selling_points(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> SellingPointsResponse:
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    if not (product.primary_keyword or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_structured_execution_error_detail(
                reason="missing_context",
                code="MAIN_KEYWORD_REQUIRED",
                message="Selling points generation requires product main_keyword.",
                module_id=MODULE_KEY,
            ),
        )
    context = _execution_context(
        db,
        request=request,
        user=user,
        key_requirements={"deepseek": "deepseek"},
    )
    key = context.key_for_step("deepseek")
    product_payload = _product_full_ai_payload(db, product)
    scope_context = _scope_context(request)
    source_name = key.name
    db.rollback()
    ai_payload = {
        "product": product_payload,
        "module_id": MODULE_KEY,
        "task": "selling_points",
        "provider": "deepseek",
        "task_type": "selling_points",
        "selling_points_skill": selling_points_skill_context(),
        "required_output": [
            "high_conversion_selling_points",
            "structured_bullet_points",
            "marketing_optimized_copy",
            "translated_version",
            "chinese_translation",
        ],
    }
    ai_payload["messages"] = _strict_json_messages(
        instruction=selling_points_instruction(),
        payload=ai_payload,
    )
    provider_output = _execute_provider_json(
        db,
        context=context,
        provider="deepseek",
        task_type="selling_points",
        payload=ai_payload,
    )
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=scope_context,
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    try:
        response = _normalize_selling_points_response(
            provider_output,
            product=product,
            source=source_name,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_structured_execution_error_detail(
                reason="provider_error",
                code="AI_RESPONSE_SCHEMA_MISMATCH",
                message="AI provider response did not match selling-points schema.",
                module_id=MODULE_KEY,
                org_id=context.org_id,
                extra={"provider": source_name},
            ),
        ) from exc
    output_payload = response.model_dump(mode="json")
    event = KProductKnowledgeAIEvent(
        id=uuid4(),
        product_id=product.id,
        event_type="selling_points_generation",
        provider=source_name,
        provider_model="deepseek-v4-pro",
        prompt_version=SELLING_POINTS_SKILL_VERSION,
        input_hash=_source_text_hash(json.dumps(product_payload, sort_keys=True, default=str)),
        output_summary_json={
            "bullet_count": len(response.bullets),
            "target_language": response.target_language,
            "target_market": product.target_market,
        },
        output_payload_json=output_payload,
        status="succeeded",
        created_by_user_id=_user_uuid(user),
        updated_by_user_id=_user_uuid(user),
    )
    product.deepseek_structured_output_json = {
        **(product.deepseek_structured_output_json or {}),
        "selling_points_generation": provider_output,
    }
    product.ai_warnings_json = {
        **(product.ai_warnings_json or {}),
        "selling_points": output_payload,
    }
    latest_execution = KWorkflowOrchestratorV2(db).latest_execution_for_product(
        product_id=product.id,
        scope_context=_scope_context(request),
    )
    if latest_execution is not None:
        latest_execution.trace_json = [
            *(latest_execution.trace_json or []),
            {
                "step": "selling_points_generation",
                "status": "completed",
                "timestamp": _now().isoformat(),
                "output_summary": {
                    "bullet_count": len(response.bullets),
                    "provider": source_name,
                },
            },
        ]
        latest_execution.execution_gate_logs_json = [
            *(latest_execution.execution_gate_logs_json or []),
            {
                "gate": "workflow_state_machine_v2",
                "status": "allowed",
                "details": {
                    "event": "selling_points_generated",
                    "state": "SELLING_POINTS_GENERATED",
                    "step": "selling_points_generation",
                    "closed_loop": True,
                },
                "timestamp": _now().isoformat(),
            },
        ]
        db.add(latest_execution)
    db.add_all([product, event])
    db.commit()
    db.refresh(event)
    return response.model_copy(update={"stored_event_id": str(event.id)})


@router.get(
    "/products/{product_id}/selling-points",
    response_model=SellingPointsResponse,
)
def get_product_selling_points(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> SellingPointsResponse:
    del user
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    payload = _stored_selling_points_payload(product)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selling points were not found for this product.",
        )
    return _selling_points_response_from_payload(product, payload)


@router.post(
    "/products/{product_id}/selling-points/approve",
    response_model=SellingPointsResponse,
)
def approve_product_selling_points(
    product_id: UUID,
    payload: ApproveSellingPointsRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> SellingPointsResponse:
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)

    source = (payload.source or "manual_review").strip() or "manual_review"
    target_language = (
        payload.target_language.strip()
        if payload.target_language and payload.target_language.strip()
        else product.canonical_language
    )
    output_payload = {
        "bullets": [bullet.model_dump(mode="json") for bullet in payload.bullets],
        "seo_keywords": _safe_string_list(payload.seo_keywords),
        "market_tags": _safe_string_list(payload.market_tags),
        "confidence_score": payload.confidence_score,
        "source": source,
        "marketing_copy": payload.marketing_copy,
        "translated_version": payload.translated_version,
        "chinese_translation": payload.chinese_translation,
        "target_language": target_language,
        "product_id": str(product.id),
        "review_status": "approved",
        "approved_at": _now().isoformat(),
    }
    response = SellingPointsResponse(
        bullets=payload.bullets,
        seo_keywords=output_payload["seo_keywords"],
        market_tags=output_payload["market_tags"],
        confidence_score=payload.confidence_score,
        source=source,
        marketing_copy=payload.marketing_copy,
        translated_version=payload.translated_version,
        chinese_translation=payload.chinese_translation,
        target_language=target_language,
        product_id=str(product.id),
    )
    event = KProductKnowledgeAIEvent(
        id=uuid4(),
        product_id=product.id,
        event_type="selling_points_manual_review",
        provider=source,
        provider_model=None,
        prompt_version="k-selling-points-manual-review-v1",
        input_hash=_source_text_hash(
            json.dumps(output_payload, sort_keys=True, default=str)
        ),
        output_summary_json={
            "bullet_count": len(payload.bullets),
            "target_language": target_language,
            "review_status": "approved",
        },
        output_payload_json=output_payload,
        status="succeeded",
        created_by_user_id=_user_uuid(user),
        updated_by_user_id=_user_uuid(user),
    )
    pending_snapshot_payload = {
        "count": len(output_payload["bullets"]),
        "payload": {
            "bullets": output_payload["bullets"],
            "chinese_translation": output_payload.get("chinese_translation"),
            "confidence_score": output_payload.get("confidence_score"),
            "market_tags": output_payload.get("market_tags"),
            "marketing_copy": output_payload.get("marketing_copy"),
            "product_id": str(product.id),
            "seo_keywords": output_payload.get("seo_keywords"),
            "source": output_payload.get("source"),
            "target_language": output_payload.get("target_language"),
            "translated_version": output_payload.get("translated_version"),
        },
    }
    selling_points_digest = _stable_payload_digest(pending_snapshot_payload)
    product.ai_warnings_json = {
        **_product_ai_warnings(product),
        "selling_points": output_payload,
        "selling_points_review": {
            "status": "approved",
            "event_id": str(event.id),
            "approved_at": output_payload["approved_at"],
            "selling_points_digest": selling_points_digest,
            "bullet_count": len(output_payload["bullets"]),
        },
    }
    db.add_all([product, event])
    db.commit()
    db.refresh(event)
    return response.model_copy(update={"stored_event_id": str(event.id)})


@router.get("/media", response_model=MediaAssetListResponse)
def list_media_assets(
    request: Request,
    product_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> MediaAssetListResponse:
    del user
    query = select(KProductKnowledgeMediaAsset).where(
        KProductKnowledgeMediaAsset.status != "removed"
    )
    count_query = select(func.count()).select_from(KProductKnowledgeMediaAsset).where(
        KProductKnowledgeMediaAsset.status != "removed"
    )
    if product_id:
        product = _product_by_ref(
            db,
            product_ref=product_id,
            scope_context=_scope_context(request),
        )
        query = query.where(KProductKnowledgeMediaAsset.product_id == product.id)
        count_query = count_query.where(KProductKnowledgeMediaAsset.product_id == product.id)
    rows = list(
        db.scalars(
            query.options(defer(KProductKnowledgeMediaAsset.metadata_json))
            .order_by(KProductKnowledgeMediaAsset.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    items = [
        _media_asset_read(row)
        for row in rows
    ]
    count = (
        len(rows)
        if offset == 0 and len(rows) < limit
        else int(db.scalar(count_query) or 0)
    )
    return MediaAssetListResponse(items=items, count=count)


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
    variant = _variant_by_sku(db, product=product, variant_sku=payload.variant_sku)
    filename = (
        payload.filename
        or (payload.file_url_placeholder or "image").rsplit("/", 1)[-1]
        or "image"
    )
    object_key = f"images/{product.product_key}/{variant.variant_sku}/{filename}"
    row = KProductKnowledgeMediaAsset(
        id=uuid4(),
        product_id=product.id,
        variant_id=variant.id,
        variant_sku=variant.variant_sku,
        asset_type=payload.asset_type,
        asset_role=payload.asset_role,
        status="available",
        review_status="not_applicable",
        object_key=object_key,
        file_url_placeholder=payload.file_url_placeholder,
        mime_type=payload.mime_type,
        source=IMAGE_SOURCE_MANUAL,
        metadata_json={
            **_safe_media_metadata(payload.metadata),
            "filename": filename,
            "product_folder": f"images/{product.product_key}",
            "source_type": IMAGE_SOURCE_MANUAL,
            "product_key": product.product_key,
            "variant_folder": f"images/{product.product_key}/{variant.variant_sku}",
            "variant_sku": variant.variant_sku,
            "sku": product.sku,
            "k_image_ai_generation_allowed": False,
            "k_image_review_allowed": False,
        },
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    db.commit()
    db.refresh(row)
    return _media_asset_read(row, product_ref=_product_public_ref(product))


@router.post(
    "/products/{product_id}/media/upload",
    response_model=MediaAssetRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_product_media_asset(
    product_id: UUID,
    request: Request,
    variant_sku: str = Form(...),
    asset_role: str = Form(default="main"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> MediaAssetRead:
    del user
    product = get_product(
        db,
        product_id=product_id,
        scope_context=_scope_context(request),
    )
    variant = _variant_by_sku(db, product=product, variant_sku=variant_sku)
    filename = _safe_filename(file.filename)
    contents = file.file.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image file is empty.",
        )
    mime_type = _validate_uploaded_image(contents, file.content_type)
    object_key = f"images/{product.product_key}/{variant.variant_sku}/{uuid4()}-{filename}"
    storage_path = _write_k_media_file(object_key, contents)
    content_sha256 = hashlib.sha256(contents).hexdigest()
    thumbnail_path, thumbnail_object_key, _thumbnail_media_type = ensure_image_derivative(
        root=_media_storage_root(),
        object_key=object_key,
        kind="thumbnail",
        max_side=320,
        contents=contents,
    )
    preview_path, preview_object_key, _preview_media_type = ensure_image_derivative(
        root=_media_storage_root(),
        object_key=object_key,
        kind="preview",
        max_side=1280,
        contents=contents,
    )
    row = KProductKnowledgeMediaAsset(
        id=uuid4(),
        product_id=product.id,
        variant_id=variant.id,
        variant_sku=variant.variant_sku,
        asset_type="image",
        asset_role=asset_role or "main",
        status="available",
        review_status="not_applicable",
        storage_provider="local_filesystem",
        object_key=object_key,
        file_url_placeholder=None,
        file_size=len(contents),
        mime_type=mime_type,
        source=IMAGE_SOURCE_MANUAL,
        metadata_json={
            "content_sha256": content_sha256,
            "filename": filename,
            "storage_provider": "local_filesystem",
            "storage_relative_path": object_key,
            "storage_path": str(storage_path),
            "direct_binary_upload": True,
            "product_folder": f"images/{product.product_key}",
            "source_type": IMAGE_SOURCE_MANUAL,
            "product_key": product.product_key,
            "variant_folder": f"images/{product.product_key}/{variant.variant_sku}",
            "variant_sku": variant.variant_sku,
            "sku": product.sku,
            "k_image_ai_generation_allowed": False,
            "k_image_review_allowed": False,
            "preview_object_key": preview_object_key,
            "preview_path": str(preview_path),
            "thumbnail_object_key": thumbnail_object_key,
            "thumbnail_path": str(thumbnail_path),
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _media_asset_read(row, product_ref=_product_public_ref(product))


@router.post(
    "/products/{product_id}/images/import-i-output",
    response_model=ISystemImageImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_i_system_images(
    product_id: UUID,
    payload: ISystemImageImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> ISystemImageImportResponse:
    product = get_product(
        db,
        product_id=product_id,
        scope_context=_scope_context(request),
    )
    variant = _variant_by_id(db, product=product, variant_id=payload.variant_id)

    decoded_images: list[tuple[ISystemImageImportItem, bytes, str, str]] = []
    for item in payload.images:
        contents = _decode_image_base64(item.image_base64)
        mime_type = _validate_uploaded_image(contents, item.mime_type)
        content_sha256 = hashlib.sha256(contents).hexdigest()
        if item.content_sha256 and item.content_sha256 != content_sha256:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image content hash does not match content_sha256.",
            )
        decoded_images.append((item, contents, mime_type, content_sha256))

    rows: list[KProductKnowledgeMediaAsset] = []
    for index, (item, contents, mime_type, content_sha256) in enumerate(
        decoded_images,
        start=1,
    ):
        extension = "png" if mime_type == "image/png" else "img"
        candidate_part = _safe_filename(item.candidate_id or f"i-output-{index}")
        filename = f"{uuid4()}-{candidate_part}.{extension}"
        object_key = (
            f"images/{product.product_key}/{variant.variant_sku}/"
            f"i-series/{filename}"
        )
        storage_path = _write_k_media_file(object_key, contents)
        thumbnail_path, thumbnail_object_key, _thumbnail_media_type = (
            ensure_image_derivative(
                root=_media_storage_root(),
                object_key=object_key,
                kind="thumbnail",
                max_side=320,
                contents=contents,
            )
        )
        preview_path, preview_object_key, _preview_media_type = ensure_image_derivative(
            root=_media_storage_root(),
            object_key=object_key,
            kind="preview",
            max_side=1280,
            contents=contents,
        )
        row = KProductKnowledgeMediaAsset(
            id=uuid4(),
            product_id=product.id,
            variant_id=variant.id,
            variant_sku=variant.variant_sku,
            asset_type="image",
            asset_role="main",
            status="available",
            review_status="i_system_managed",
            storage_provider="local_filesystem",
            object_key=object_key,
            file_url_placeholder=None,
            file_size=len(contents),
            mime_type=mime_type,
            width=item.width,
            height=item.height,
            source=IMAGE_SOURCE_I_SYSTEM,
            metadata_json={
                **_safe_media_metadata(item.metadata),
                "content_sha256": content_sha256,
                "direct_i_handoff": True,
                "event_id": str(payload.event_id) if payload.event_id else None,
                "filename": filename,
                "i_system_media_library_saved": False,
                "image_prompt_enhanced": payload.image_prompt_enhanced,
                "prompt_original": payload.prompt_original,
                "source_type": IMAGE_SOURCE_I_SYSTEM,
                "i_generation_source_type": payload.source_type,
                "storage_provider": "local_filesystem",
                "storage_relative_path": object_key,
                "storage_path": str(storage_path),
                "product_key": product.product_key,
                "product_id": str(product.id),
                "variant_id": str(variant.id),
                "variant_folder": f"images/{product.product_key}/{variant.variant_sku}",
                "variant_sku": variant.variant_sku,
                "sku": product.sku,
                "k_image_ai_generation_allowed": False,
                "k_image_review_allowed": False,
                "reference_images_stored": False,
                "temporary_uploads_stored": False,
                "style_config": payload.style_config,
                "aspect_ratio": payload.aspect_ratio,
                "preview_object_key": preview_object_key,
                "preview_path": str(preview_path),
                "thumbnail_object_key": thumbnail_object_key,
                "thumbnail_path": str(thumbnail_path),
            },
            created_by_user_id=_user_uuid(user),
            updated_by_user_id=_user_uuid(user),
        )
        db.add(row)
        rows.append(row)

    db.flush()
    first_asset = rows[0]
    product.selected_image_path = first_asset.object_key
    product.image_asset_status = "bound"
    product.media_notes_json = {
        **(product.media_notes_json or {}),
        "bound_asset_id": str(first_asset.id),
        "image_source_type": IMAGE_SOURCE_I_SYSTEM,
        "variant_id": str(variant.id),
        "variant_sku": variant.variant_sku,
        "bound_at": _now().isoformat(),
        "direct_i_handoff": True,
        "i_system_media_library_saved": False,
        "object_key": first_asset.object_key,
        "original_url": f"/k/media/{first_asset.id}/file",
        "preview_url": f"/k/media/{first_asset.id}/preview",
        "thumbnail_url": f"/k/media/{first_asset.id}/thumbnail",
    }
    # I 图已存回 K，临时作图参考图用完即删
    product.reference_image_url = None
    db.add(product)

    submitted = False
    submit_status = "pending"
    message = None
    try:
        section_state = _store_image_review_snapshot(db, product=product, user=user)
        submitted = section_state.submitted
        submit_status = section_state.status
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, dict) and isinstance(detail.get("message"), str):
            message = detail["message"]
        elif isinstance(detail, str):
            message = detail
        else:
            message = "Images were saved but the K image section is not complete."
    db.commit()
    for row in rows:
        db.refresh(row)
    return ISystemImageImportResponse(
        product_id=product.id,
        variant_id=variant.id,
        variant_sku=variant.variant_sku,
        asset_ids=[row.id for row in rows],
        submitted=submitted,
        submit_status=submit_status,
        message=message,
    )


@router.post(
    "/products/{product_id}/images/submit",
    response_model=ProductSectionState,
)
def submit_product_images(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> ProductSectionState:
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return _store_image_review_snapshot(db, product=product, user=user)


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


class GenerationJobItem(BaseModel):
    job_id: str
    product_id: str
    job_type: str
    status: str
    error: str | None = None
    skill_version: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class GenerationEnqueueResponse(BaseModel):
    batch_id: str
    jobs: list[GenerationJobItem]


class GenerationJobsStatusResponse(BaseModel):
    jobs: list[GenerationJobItem]


class ProductGenerateBatchRequest(BaseModel):
    product_ids: list[UUID]


def _enqueue_generation(
    product_ids: list[UUID],
    job_type: str,
    request: Request,
    db: Session,
    user: User,
) -> GenerationEnqueueResponse:
    scope_context = _scope_context(request)
    for product_id in product_ids:
        try:
            get_product(db, product_id=product_id, scope_context=scope_context)
        except KProductKnowledgeError as exc:
            _raise_k_error(exc)
    batch_id, jobs = enqueue_generation_jobs(
        db,
        product_ids=product_ids,
        job_type=job_type,
        user=user,
        scope_context=scope_context,
    )
    db.commit()
    return GenerationEnqueueResponse(
        batch_id=str(batch_id),
        jobs=[GenerationJobItem(**job) for job in jobs],
    )


@router.post(
    "/products/{product_id}/generate-copy",
    response_model=GenerationEnqueueResponse,
)
def product_knowledge_generate_copy(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> GenerationEnqueueResponse:
    return _enqueue_generation([product_id], "marketing_copy", request, db, user)


@router.post(
    "/products/{product_id}/generate-image-brief",
    response_model=GenerationEnqueueResponse,
)
def product_knowledge_generate_image_brief(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> GenerationEnqueueResponse:
    return _enqueue_generation([product_id], "image_brief", request, db, user)


@router.post(
    "/products/{product_id}/brand-audit",
    response_model=GenerationEnqueueResponse,
)
def product_knowledge_brand_audit(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> GenerationEnqueueResponse:
    """品牌硬门审查：黑名单+AI 全文字面 + 每张成品图视觉审（k-worker 异步）。"""
    return _enqueue_generation([product_id], "brand_audit", request, db, user)


@router.post(
    "/products/generate-copy/batch",
    response_model=GenerationEnqueueResponse,
)
def product_knowledge_generate_copy_batch(
    payload: ProductGenerateBatchRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> GenerationEnqueueResponse:
    return _enqueue_generation(payload.product_ids, "marketing_copy", request, db, user)


@router.post(
    "/products/generate-image-brief/batch",
    response_model=GenerationEnqueueResponse,
)
def product_knowledge_generate_image_brief_batch(
    payload: ProductGenerateBatchRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> GenerationEnqueueResponse:
    return _enqueue_generation(payload.product_ids, "image_brief", request, db, user)


# --- 一次性作图 (P 图片体系阶段 2+3) -----------------------------------------


class RenderImagesRequest(BaseModel):
    positions: list[int] | None = None


class RenderRetryRequest(BaseModel):
    batch_id: UUID


class RenderJobItem(BaseModel):
    job_id: str
    batch_id: str
    position: int
    placement: str
    role_label: str | None = None
    asset_role: str
    status: str
    error: str | None = None
    asset_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class RenderEnqueueResponse(BaseModel):
    batch_id: str
    jobs: list[RenderJobItem]


class RenderJobsResponse(BaseModel):
    batch_id: str | None
    jobs: list[RenderJobItem]
    summary: dict[str, int]


def _raise_render_error(exc: KImageRenderError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post(
    "/products/{product_id}/render-images",
    response_model=RenderEnqueueResponse,
)
def product_knowledge_render_images(
    product_id: UUID,
    request: Request,
    payload: RenderImagesRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> RenderEnqueueResponse:
    """按作图指令一次性渲染全部（或指定 position 的）产品图。"""
    scope_context = _scope_context(request)
    try:
        product = get_product(db, product_id=product_id, scope_context=scope_context)
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    try:
        batch_id, jobs = enqueue_image_render_jobs(
            db,
            product=product,
            user=user,
            scope_context=scope_context,
            positions=payload.positions if payload is not None else None,
        )
    except KImageRenderError as exc:
        _raise_render_error(exc)
    db.commit()
    return RenderEnqueueResponse(
        batch_id=str(batch_id),
        jobs=[RenderJobItem(**job) for job in jobs],
    )


@router.get(
    "/products/{product_id}/render-jobs",
    response_model=RenderJobsResponse,
)
def product_knowledge_render_jobs(
    product_id: UUID,
    request: Request,
    batch_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> RenderJobsResponse:
    del user
    try:
        get_product(db, product_id=product_id, scope_context=_scope_context(request))
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    result = render_jobs_status(db, product_id=product_id, batch_id=batch_id)
    return RenderJobsResponse(
        batch_id=result["batch_id"],
        jobs=[RenderJobItem(**job) for job in result["jobs"]],
        summary=result["summary"],
    )


@router.post(
    "/products/{product_id}/render-images/retry",
    response_model=RenderJobsResponse,
)
def product_knowledge_render_images_retry(
    product_id: UUID,
    payload: RenderRetryRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> RenderJobsResponse:
    del user
    try:
        get_product(db, product_id=product_id, scope_context=_scope_context(request))
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    retried = retry_failed_render_jobs(
        db,
        product_id=product_id,
        batch_id=payload.batch_id,
    )
    if retried == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "NO_FAILED_JOBS",
                "message": "这个批次没有失败的图可以重试。",
            },
        )
    db.commit()
    result = render_jobs_status(db, product_id=product_id, batch_id=payload.batch_id)
    return RenderJobsResponse(
        batch_id=result["batch_id"],
        jobs=[RenderJobItem(**job) for job in result["jobs"]],
        summary=result["summary"],
    )


class RenderAssetItem(BaseModel):
    asset_id: str
    position: int
    placement: str
    asset_role: str
    status: str
    role_label: str | None = None
    staged_at: str | None = None


class RenderAssetsResponse(BaseModel):
    assets: list[RenderAssetItem]


@router.get(
    "/products/{product_id}/render-assets",
    response_model=RenderAssetsResponse,
)
def product_knowledge_render_assets(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> RenderAssetsResponse:
    """渲染成品资产视图：暂存（staged）+ 已保存（available）并存。"""
    del user
    try:
        product = get_product(
            db, product_id=product_id, scope_context=_scope_context(request)
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    return RenderAssetsResponse(
        assets=[RenderAssetItem(**item) for item in list_render_assets(db, product)]
    )


class RenderSaveRequest(BaseModel):
    asset_ids: list[UUID] | None = None  # None = 全部保存


@router.post(
    "/products/{product_id}/render-assets/save",
    response_model=RenderAssetsResponse,
)
def product_knowledge_render_assets_save(
    product_id: UUID,
    request: Request,
    payload: RenderSaveRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> RenderAssetsResponse:
    """保存暂存图：staged→正式入库（归档旧图/绑主图/触发品牌审查）。"""
    scope_context = _scope_context(request)
    try:
        product = get_product(db, product_id=product_id, scope_context=scope_context)
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    try:
        save_render_assets(
            db,
            product=product,
            user=user,
            scope_context=scope_context,
            asset_ids=payload.asset_ids if payload is not None else None,
        )
    except KImageRenderError as exc:
        _raise_render_error(exc)
    db.commit()
    return RenderAssetsResponse(
        assets=[RenderAssetItem(**item) for item in list_render_assets(db, product)]
    )


class RenderReworkRequest(BaseModel):
    asset_id: UUID
    extra_prompt: str
    use_current_as_reference: bool = False


@router.post(
    "/products/{product_id}/render-rework",
    response_model=RenderEnqueueResponse,
)
def product_knowledge_render_rework(
    product_id: UUID,
    payload: RenderReworkRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> RenderEnqueueResponse:
    """单张重做：原 prompt + 临时修改要求；参考图 = 这版图或原始参考图。"""
    scope_context = _scope_context(request)
    try:
        product = get_product(db, product_id=product_id, scope_context=scope_context)
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    try:
        batch_id, job = enqueue_rework_job(
            db,
            product=product,
            user=user,
            scope_context=scope_context,
            asset_id=payload.asset_id,
            extra_prompt=payload.extra_prompt,
            use_current_as_reference=payload.use_current_as_reference,
        )
    except KImageRenderError as exc:
        _raise_render_error(exc)
    db.commit()
    return RenderEnqueueResponse(
        batch_id=str(batch_id),
        jobs=[RenderJobItem(**job)],
    )


@router.get("/products/{product_id}/reference-image")
def product_knowledge_reference_image(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> Response:
    """参考图代理：后端拉取外链原图（绕过浏览器跨域，SSRF 域名白名单）。"""
    del user
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    if not product.reference_image_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="产品没有参考图外链。",
        )
    try:
        _filename, contents, mime = download_reference_image(
            product.reference_image_url
        )
    except KImageRenderError as exc:
        _raise_render_error(exc)
    except Exception as exc:  # noqa: BLE001 - upstream CDN failure
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="参考图下载失败，请稍后再试。",
        ) from exc
    response = Response(content=contents, media_type=mime)
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


class CategoryTreeItem(BaseModel):
    id: str
    name: str
    full_path: str
    level: int
    is_leaf: bool


class CategorySearchResponse(BaseModel):
    tree: str
    items: list[CategoryTreeItem]


_CATEGORY_TABLES = {"google": "k_category_google", "amazon": "k_category_amazon"}


@router.get("/categories/search", response_model=CategorySearchResponse)
def product_knowledge_category_search(
    tree: str,
    request: Request,
    q: str = "",
    limit: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> CategorySearchResponse:
    """类目下拉搜索：tree=google(独立站) 或 amazon；按 full_path/name 模糊匹配。"""
    del request, user
    table = _CATEGORY_TABLES.get((tree or "").strip().lower())
    if table is None:
        raise HTTPException(status_code=422, detail="tree must be 'google' or 'amazon'")
    q = (q or "").strip()
    limit = max(1, min(limit, 100))
    rows = db.execute(
        text(
            f"SELECT id,name,full_path,level,is_leaf FROM {table} "
            "WHERE (:q = '' OR full_path ILIKE :like OR name ILIKE :like) "
            "ORDER BY is_leaf DESC, level ASC, full_path ASC LIMIT :limit"
        ),
        {"q": q, "like": f"%{q}%", "limit": limit},
    ).mappings().all()
    return CategorySearchResponse(
        tree=table.replace("k_category_", ""),
        items=[CategoryTreeItem(**dict(r)) for r in rows],
    )


class ImportFromRRequest(BaseModel):
    asins: list[str]
    channel: str = "dtc"


class ImportFromRResponse(BaseModel):
    created: list[dict[str, Any]]
    skipped: list[str]
    errors: list[dict[str, str]]


@router.post("/products/import-from-r", response_model=ImportFromRResponse)
def product_knowledge_import_from_r(
    payload: ImportFromRRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_CREATE)),
) -> ImportFromRResponse:
    """R→K 搬运：把 R-W 产品搬进 K，自动落类目 + 带参考图。"""
    result = transfer_from_rw(
        db,
        asins=payload.asins,
        channel=payload.channel,
        user=user,
        scope_context=_scope_context(request),
    )
    db.commit()
    return ImportFromRResponse(**result)


@router.get(
    "/products/{product_id}/generation-jobs",
    response_model=GenerationJobsStatusResponse,
)
def product_knowledge_generation_jobs(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> GenerationJobsStatusResponse:
    del request, user
    rows = jobs_status(db, product_id=product_id)
    return GenerationJobsStatusResponse(jobs=[GenerationJobItem(**row) for row in rows])


@router.delete("/media/{asset_id}", response_model=MediaAssetRead)
def delete_media_asset(
    asset_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> MediaAssetRead:
    row = db.get(KProductKnowledgeMediaAsset, asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Media asset was not found.")
    try:
        product = get_product(
            db,
            product_id=row.product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)

    row.status = "removed"
    row.review_status = "removed"
    row.updated_by_user_id = _user_uuid(user)
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    row.metadata_json = {
        **{
            key: value
            for key, value in metadata.items()
            if key != "db_content_base64"
        },
        "removed_at": _now().isoformat(),
        "removed_by_user_id": str(_user_uuid(user)) if _user_uuid(user) else None,
    }
    db.add(row)
    db.commit()
    db.refresh(row)
    return _media_asset_read(row, product_ref=_product_public_ref(product))


@router.get("/media/{asset_id}/file")
def download_media_asset_file(
    asset_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> Response:
    del user
    row = db.get(KProductKnowledgeMediaAsset, asset_id)
    if row is None or row.status == "removed":
        raise HTTPException(status_code=404, detail="Media asset was not found.")
    try:
        get_product(
            db,
            product_id=row.product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)

    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    storage_path = _ensure_media_asset_file(row)
    db.add(row)
    db.commit()
    filename = str(
        metadata.get("filename")
        or (storage_path.name if storage_path is not None else row.object_key)
        or f"{row.id}.img"
    )
    response = FileResponse(
        path=storage_path,
        content_disposition_type="inline",
        filename=filename,
        media_type=row.mime_type or "application/octet-stream",
    )
    response.headers["Cache-Control"] = INLINE_IMAGE_CACHE_CONTROL
    response.headers["ETag"] = media_file_etag(storage_path)
    response.headers["X-K-Media-Asset-Id"] = str(row.id)
    return response


@router.get("/media/{asset_id}/thumbnail")
def thumbnail_media_asset_file(
    asset_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> Response:
    del user
    row = db.get(KProductKnowledgeMediaAsset, asset_id)
    if row is None or row.status == "removed":
        raise HTTPException(status_code=404, detail="Media asset was not found.")
    try:
        get_product(
            db,
            product_id=row.product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    path = _ensure_media_asset_derivative(row, kind="thumbnail", max_side=320)
    db.add(row)
    db.commit()
    response = FileResponse(
        path=path,
        content_disposition_type="inline",
        filename=path.name,
        media_type="image/webp" if path.suffix == ".webp" else row.mime_type,
    )
    response.headers["Cache-Control"] = DERIVED_IMAGE_CACHE_CONTROL
    response.headers["ETag"] = media_file_etag(path)
    return response


@router.get("/media/{asset_id}/preview")
def preview_media_asset_file(
    asset_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> Response:
    del user
    row = db.get(KProductKnowledgeMediaAsset, asset_id)
    if row is None or row.status == "removed":
        raise HTTPException(status_code=404, detail="Media asset was not found.")
    try:
        get_product(
            db,
            product_id=row.product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    path = _ensure_media_asset_derivative(row, kind="preview", max_side=1280)
    db.add(row)
    db.commit()
    response = FileResponse(
        path=path,
        content_disposition_type="inline",
        filename=path.name,
        media_type="image/webp" if path.suffix == ".webp" else row.mime_type,
    )
    response.headers["Cache-Control"] = DERIVED_IMAGE_CACHE_CONTROL
    response.headers["ETag"] = media_file_etag(path)
    return response


@router.get(
    "/media/{asset_id}/download",
    response_model=ProductKnowledgeMediaDownloadResponse,
)
def download_media_asset(
    asset_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> ProductKnowledgeMediaDownloadResponse:
    del user
    row = db.get(KProductKnowledgeMediaAsset, asset_id)
    if row is None or row.status == "removed":
        raise HTTPException(status_code=404, detail="Media asset was not found.")
    try:
        get_product(
            db,
            product_id=row.product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    filename = None
    if isinstance(row.metadata_json, dict):
        filename = row.metadata_json.get("filename")
    return ProductKnowledgeMediaDownloadResponse(
        asset_id=row.id,
        product_id=row.product_id,
        object_key=row.object_key,
        download_url=row.file_url_placeholder,
        original_url=f"/k/media/{row.id}/file" if row.object_key else row.file_url_placeholder,
        filename=filename,
        review_status=row.review_status,
        status=row.status,
    )
