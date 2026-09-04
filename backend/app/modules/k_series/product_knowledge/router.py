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
from .errors import (
    KConflictError,
    KInvalidStateError,
    KProductKnowledgeError,
    KProductNotFoundError,
    KValidationError,
)
from .evidence_guard import TitleEvidenceConsistencyError
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
from .product_naming import sanitize_product_naming_output
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
    ProductKnowledgeVariantListResponse,
    ProductKnowledgeVariantPricePatch,
    ProductKnowledgeVariantRead,
    ProductKnowledgeVariantsSync,
    ProductKnowledgeVariantsSyncResponse,
    ProductReferenceImagesRequest,
    ProductReferenceImagesResponse,
    ReferenceImageOutcome,
    ProductKnowledgeWorkflowControlRequest,
    ProductKnowledgeWorkflowExecutionRead,
    ProductKnowledgeWorkflowExportRequest,
    ProductKnowledgeWorkflowExportResponse,
    ProductKnowledgeWorkflowStartRequest,
)
from .scope_shim import KScopeContext, apply_scope_filters
from .services.images_service import (  # noqa: F401 - 兼容 re-export
    KeywordEntry,
    RiskTermEntry,
    _db_image_bytes_from_metadata,
    _decode_image_base64,
    _detect_image_mime,
    _k19_status_from_model,
    _k20_status_from_model,
    _keyword_entry,
    _now,
    _product_public_ref,
    _product_variants_by_product_ids,
    _risk_entry,
    _store_image_review_snapshot,
    _store_keyword_review_snapshot,
    _validate_uploaded_image,
    _variant_by_id,
)
from .services.product_repo import (  # noqa: F401 - 兼容 re-export
    PRODUCT_CREATE_IDEMPOTENCY_TTL_SECONDS,
    ProductCreateIdempotencyRecord,
    ProductReadinessResponse,
    ProductSectionState,
    _active_keyword_snapshot,
    _canonical_payload,
    _claim_product_create_idempotency,
    _cleanup_product_create_idempotency,
    _complete_product_create_idempotency,
    _count_products,
    _discard_product_create_idempotency,
    _ensure_product_ready_for_approval,
    _product_by_ref,
    _product_create_fingerprint,
    _product_full_ai_payload,
    _product_read,
    _product_readiness,
    _product_variants,
    _router_unique_product_key,
    _section_state_from_marker,
    _variant_by_sku,
)
from .services.media_service import (  # noqa: F401 - 兼容 re-export
    MediaAssetRead,
    RESERVED_MEDIA_METADATA_KEYS,
    _active_media_snapshot,
    _image_asset_for_product,
    _image_dimensions,
    _media_asset_file_info,
    _media_asset_local_path,
    _media_asset_read,
    _media_asset_requires_local_file,
    _media_storage_root,
    _path_within_root,
    _public_media_metadata,
)
from .services.selling_points_service import (  # noqa: F401 - 兼容 re-export
    SellingPointBullet,
    SellingPointsResponse,
    _canonical_measurement_unit,
    _contains_evidence_phrase,
    _enrich_selling_points_chinese,
    _evidence_syntax_is_valid,
    _evidence_value_text,
    _feature_source_is_trusted,
    _humanize_selling_point_error,
    _mark_selling_point_evidence_status,
    _measurement_pairs,
    _normalize_selling_points_response,
    _normalized_evidence_text,
    _selling_point_evidence_error,
    _selling_point_evidence_snapshot,
    _selling_point_review_error_message,
    _selling_point_support_error,
    _selling_points_evidence_payload,
    _selling_points_response_from_payload,
    _selling_points_snapshot,
    _stored_selling_points_payload,
    _structured_measurement_pairs,
    _structured_spec_evidence_snapshot,
    _supported_measurement_pairs,
    _verified_feature_evidence_snapshot,
)
from .services.common import (  # noqa: F401 - 兼容 re-export
    _product_ai_warnings,
    _safe_string_list,
    _source_text_hash,
    _stable_payload_digest,
    _strict_json_messages,
)
from .services.api_support import (
    _execute_provider_json,
    _execution_configuration_message,
    _execution_context,
    _execution_error_reason,
    _gate_error,
    _is_execution_configuration_error,
    _require_k_permission,
    _scope_context,
    _structured_execution_error_detail,
    _workflow_error,
)
from .sku_allocator import ensure_product_sku
from .structured_specs import (
    apply_customer_translations,
    pending_customer_translation_requests,
)
from .service import (
    archive_product,
    create_product,
    delete_product,
    get_attributes,
    get_keywords,
    get_product,
    get_risk_terms,
    invalidate_evidence_outputs,
    list_products,
    patch_attributes,
    patch_keywords,
    patch_risk_terms,
    sync_product_variants,
    update_product,
    update_variant_prices,
)
from .workflow_engine import (
    IMAGE_SOURCE_MANUAL,
    IMAGE_SOURCE_I_SYSTEM,
    KWorkflowOrchestratorV2,
    KWorkflowExecutionError,
    _user_uuid,
    reap_orphan_running_execution,
)
from ....services.module_execution_gate import ModuleExecutionGateError
from .generation_jobs import enqueue_generation_jobs, jobs_status
from .buyer_display import (
    buyer_display_structured_specs,
    contains_cjk,
    imperial_measurement,
)
from .evidence_guard import canonical_package_includes, package_claim_error
from .faq_research import (
    evidence_number_tokens,
    imperial_equivalent_number_tokens,
    is_faq_text_brand_safe,
)
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
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from .prompt_skills import (
    SELLING_POINTS_SKILL_VERSION,
    selling_points_instruction,
    selling_points_skill_context,
)

router = APIRouter(prefix="/k", tags=["k-product-knowledge"])
logger = logging.getLogger(__name__)


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


class GenerationJobItem(BaseModel):
    job_id: str
    product_id: str
    job_type: str
    status: str
    error: str | None = None
    skill_version: str | None = None
    # 多阶段任务(卖点:bullets → zh → copy → done)的进度。单阶段任务恒为 None。
    stage: str | None = None
    stage_errors: dict[str, Any] | None = None
    # 入队时命中去重、复用了在途任务(而不是新建)。前端据此知道
    # "按钮没反应"其实是"已经在跑了"。
    deduplicated: bool | None = None
    started_at: str | None = None
    finished_at: str | None = None


class GenerationEnqueueResponse(BaseModel):
    batch_id: str
    jobs: list[GenerationJobItem]


class GenerationJobsStatusResponse(BaseModel):
    jobs: list[GenerationJobItem]


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


def _k19_status_to_model(status_value: str | None) -> str:
    mapping = {
        "active": "approved",
        "edited": "approved",
        "suggested": "candidate",
        "archived": "removed",
    }
    return mapping.get((status_value or "active").strip().lower(), "candidate")


def _k20_status_to_model(status_value: str | None) -> str:
    mapping = {
        "active": "candidate",
        "resolved": "confirmed",
        "ignored": "false_positive",
    }
    return mapping.get((status_value or "active").strip().lower(), "candidate")


def _safe_filename(value: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "image").strip())
    cleaned = cleaned.strip(".-_")
    return cleaned[:180] or "image"


def _safe_media_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key not in RESERVED_MEDIA_METADATA_KEYS
    }


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


def _structured_spec_path_exists(specs: Any, path: str) -> bool:
    return _structured_spec_evidence_snapshot(specs, path) is not None


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
    # 手动创建铁律:必须选类目 —— SKU 由叶子类目发号器统一签发(手填一律无效)。
    if not str(payload.category_id or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "status": "failed",
                "reason": "invalid_request",
                "code": "CATEGORY_REQUIRED_FOR_SKU",
                "message": "手动创建必须先选择类目;SKU 将按「叶子类目简写-编号」自动分配,不接受手填。",
            },
        )
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
    # 可选的手贴货源:SKU 已由发号器签发,顺手灌入 W-S 货源库(只填空,
    # fail-safe:货源联动失败绝不影响建品本身)。
    if (payload.source_url or "").strip():
        try:
            from ...w_series.product_sources import fill_source_if_absent

            fill_source_if_absent(
                db,
                sku=getattr(product, "sku", None),
                source_url=payload.source_url,
                notes="K 手动建品时贴入",
            )
            db.commit()
        except Exception:  # noqa: BLE001 - sources are an optional sidecar
            logger.exception(
                "manual-create source autofill failed product=%s",
                getattr(product, "id", None),
            )
    # 可选参考图:贴图链直下,或从 1688 货源链接自动取主图(ACL 未开通时
    # 安静跳过)。同样 fail-safe:参考图失败绝不阻塞建品。
    if (payload.reference_image_url or "").strip() or (payload.source_url or "").strip():
        try:
            from .manual_reference import attach_manual_reference_images

            combined_urls = [
                url
                for url in [
                    payload.reference_image_url,
                    *(payload.reference_image_urls or []),
                ]
                if url
            ]
            outcomes = attach_manual_reference_images(
                db,
                product=product,
                reference_image_urls=combined_urls,
                source_url=payload.source_url,
                user=user,
            )
            if any(item.get("status") == "stored" for item in outcomes):
                db.commit()
            logger.info(
                "manual-create reference images product=%s outcomes=%s",
                product.id,
                outcomes,
            )
        except Exception:  # noqa: BLE001 - reference image is optional garnish
            logger.exception(
                "manual-create reference image failed product=%s",
                getattr(product, "id", None),
            )
        try:
            from .manual_reference import attach_variant_reference_images

            variant_outcomes = attach_variant_reference_images(
                db, product=product, user=user
            )
            if any(item.get("status") == "stored" for item in variant_outcomes):
                db.commit()
            if variant_outcomes:
                logger.info(
                    "variant reference images product=%s outcomes=%s",
                    product.id,
                    variant_outcomes,
                )
        except Exception:  # noqa: BLE001 - reference image is optional garnish
            logger.exception(
                "manual-create reference image failed product=%s",
                getattr(product, "id", None),
            )
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
    "/products/{product_id}/variant-prices",
    response_model=ProductKnowledgeVariantListResponse,
)
def product_knowledge_variant_prices_patch(
    product_id: UUID,
    payload: ProductKnowledgeVariantPricePatch,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> ProductKnowledgeVariantListResponse:
    del user
    try:
        variants = update_variant_prices(
            db,
            product_id=product_id,
            payload=payload,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    items = [
        ProductKnowledgeVariantRead.model_validate(variant) for variant in variants
    ]
    return ProductKnowledgeVariantListResponse(items=items, count=len(items))


@router.put(
    "/products/{product_id}/variants",
    response_model=ProductKnowledgeVariantsSyncResponse,
)
def product_knowledge_variants_sync(
    product_id: UUID,
    payload: ProductKnowledgeVariantsSync,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> ProductKnowledgeVariantsSyncResponse:
    """建好之后改类型与变体(「基础档案」面板)。

    变体行同步在事务里一次落定;变体参考图链接的下载入库放在事务之后
    fail-safe 执行(与建品同一口径:图失败绝不回滚变体),结果逐条回。
    """

    try:
        product, reference_touched = sync_product_variants(
            db,
            product_id=product_id,
            payload=payload,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)

    outcomes: list[dict[str, Any]] = []
    if reference_touched:
        from .manual_reference import attach_reference_image_urls

        for variant in reference_touched:
            attrs = variant.attributes_json if isinstance(variant.attributes_json, dict) else {}
            url = str(attrs.get("reference_image_url") or "").strip()
            if not url:
                continue
            try:
                outcomes.extend(
                    attach_reference_image_urls(
                        db, product=product, urls=[url], variant=variant, user=user
                    )
                )
            except Exception as exc:  # noqa: BLE001 - 图是配菜,变体已落定
                logger.exception(
                    "variant reference attach failed product=%s variant=%s",
                    product.id,
                    variant.variant_sku,
                )
                outcomes.append(
                    {
                        "url": url,
                        "status": "failed",
                        "variant_sku": variant.variant_sku,
                        "asset_id": None,
                        "error": str(exc)[:200],
                    }
                )
        if any(item.get("status") == "stored" for item in outcomes):
            db.commit()
            db.refresh(product)
    return ProductKnowledgeVariantsSyncResponse(
        product=_product_read(db, product),
        reference_images=[ReferenceImageOutcome(**item) for item in outcomes],
    )


@router.post(
    "/products/{product_id}/reference-images",
    response_model=ProductReferenceImagesResponse,
)
def product_knowledge_reference_images_add(
    product_id: UUID,
    payload: ProductReferenceImagesRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> ProductReferenceImagesResponse:
    """建好之后补参考图链接。逐条入库、逐条回结果,域名不在白名单的原话回。"""

    from .manual_reference import attach_reference_image_urls

    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
        )
        if product.product_status == "archived":
            raise KInvalidStateError("Archived K products cannot be updated.")
        variant = None
        if payload.variant_id is not None:
            variant = db.scalar(
                select(KProductKnowledgeVariant).where(
                    KProductKnowledgeVariant.id == payload.variant_id,
                    KProductKnowledgeVariant.product_id == product.id,
                )
            )
            if variant is None:
                raise KValidationError("Variant does not belong to this product.")
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)

    outcomes = attach_reference_image_urls(
        db, product=product, urls=payload.urls, variant=variant, user=user
    )
    if any(item.get("status") == "stored" for item in outcomes):
        db.commit()
        db.refresh(product)
    return ProductReferenceImagesResponse(
        product=_product_read(db, product),
        items=[ReferenceImageOutcome(**item) for item in outcomes],
    )


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
    # 发版重启杀成的孤儿 running 在读取时自愈为 blocked,解锁重试按钮。
    reap_orphan_running_execution(db, execution)
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
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> RiskListResponse:
    """品牌风险词台账。

    ``k_product_knowledge_risk_terms`` 没有租户列，隔离只能靠 join 父产品表。
    2026-08-31 体检：这条以前是裸的 select + order_by，**零 scope**，制造组织的
    超管一个 GET 就能读到国际贸易的全部 50 条风险词——等于把关键词策略和踩雷
    记录摊给另一家公司。
    """
    del user
    scope = _scope_context(request)
    rows = list(
        db.scalars(
            select(KProductKnowledgeRiskTerm)
            .join(
                KProductKnowledgeProduct,
                KProductKnowledgeProduct.id == KProductKnowledgeRiskTerm.product_id,
            )
            .where(
                KProductKnowledgeProduct.workspace_key == scope.workspace_key,
                KProductKnowledgeProduct.business_context == scope.business_context,
            )
            .order_by(KProductKnowledgeRiskTerm.updated_at.desc())
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
    try:
        provider_output = sanitize_product_naming_output(
            provider_output,
            structured_specs=getattr(product, "structured_specs_json", None),
            package_includes=getattr(product, "package_includes_json", None),
        )
    except TitleEvidenceConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    response_model=GenerationEnqueueResponse,
)
def generate_product_selling_points(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
):
    """把卖点生成排进后台队列,立即返回。

    2026-08-03 之前这里是同步跑完两次串行 DeepSeek 调用才返回,实测中位数
    100s、最慢 903s,运营只能干等且刷新即丢。现在走 ``k_generation_jobs``
    三阶段(bullets → zh → copy),前端轮 ``/generation-jobs`` 看进度。

    前置校验仍留在这里当场拦:排了队再失败的话,运营要等一分钟才知道
    自己少填了主关键词。
    """

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
    # key / 模块门禁干跑一次,让配置类错误当场以结构化 4xx 返回,
    # 而不是变成 90 秒后 job 行里的一串字符串。
    _execution_context(
        db,
        request=request,
        user=user,
        key_requirements={"deepseek": "deepseek"},
    )
    return _enqueue_generation([product_id], "selling_points", request, db, user)


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

    approved_bullets: list[SellingPointBullet] = []
    rejected_bullets: list[SellingPointBullet] = []
    review_errors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, bullet in enumerate(payload.bullets):
        bullet_id = str(bullet.id or f"sp-{index + 1}").strip()
        if bullet_id in seen_ids:
            review_errors.append(
                {
                    "index": index,
                    "text": bullet.text,
                    "error": f"Duplicate selling-point id: {bullet_id}",
                }
            )
            continue
        seen_ids.add(bullet_id)
        bullet = bullet.model_copy(update={"id": bullet_id})
        # operator_fact 未填摘录时以卖点文本自证:人工逐条批准即背书
        # (前端同样兜底,这里双保险防旧客户端/API 直调)。
        if (
            str(bullet.evidence or "").strip() == "operator_fact"
            and not str(bullet.evidence_excerpt or "").strip()
        ):
            bullet = bullet.model_copy(update={"evidence_excerpt": bullet.text})
        if bullet.review_decision == "candidate":
            review_errors.append(
                {
                    "index": index,
                    "text": bullet.text,
                    "error": "Every candidate must be approved, edited, or rejected.",
                }
            )
            continue
        if bullet.review_decision == "reject":
            rejected_bullets.append(bullet)
            continue
        evidence_snapshot, evidence_error = _selling_point_evidence_snapshot(
            db,
            product,
            bullet.evidence,
            operator_excerpt=bullet.evidence_excerpt,
        )
        if evidence_error:
            review_errors.append(
                {"index": index, "text": bullet.text, "error": evidence_error}
            )
            continue
        assert evidence_snapshot is not None
        support_error = _selling_point_support_error(
            bullet,
            evidence_snapshot,
            package_includes=getattr(product, "package_includes_json", None),
            structured_specs=product.structured_specs_json,
        )
        if support_error:
            review_errors.append(
                {"index": index, "text": bullet.text, "error": support_error}
            )
            continue
        snapshot_digest = hashlib.sha256(
            _canonical_payload(evidence_snapshot).encode("utf-8")
        ).hexdigest()
        approved_bullets.append(
            bullet.model_copy(
                update={
                    "verification_status": "verified",
                    "evidence_excerpt": str(
                        evidence_snapshot.get("value_text") or ""
                    ).strip(),
                    "evidence_snapshot": evidence_snapshot,
                    "evidence_digest": snapshot_digest,
                }
            )
        )
    if review_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_structured_execution_error_detail(
                reason="invalid_state",
                code="SELLING_POINT_EVIDENCE_REQUIRED",
                message=_selling_point_review_error_message(review_errors),
                module_id=MODULE_KEY,
                extra={"items": review_errors},
            ),
        )
    if not approved_bullets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_structured_execution_error_detail(
                reason="invalid_state",
                code="SELLING_POINTS_EMPTY_AFTER_REVIEW",
                message="至少要有一条通过证据审批的卖点。",
                module_id=MODULE_KEY,
            ),
        )

    # Approved selling-point IDs are a positional contract for downstream image
    # briefs. Rejections can leave holes in candidate IDs (for example bp1, bp3),
    # so freeze the retained set with IDs that match its 1-based list order.
    approved_bullets = [
        bullet.model_copy(update={"id": f"bp{index}"})
        for index, bullet in enumerate(approved_bullets, start=1)
    ]

    source = (payload.source or "manual_review").strip() or "manual_review"
    target_language = (
        payload.target_language.strip()
        if payload.target_language and payload.target_language.strip()
        else product.canonical_language
    )
    output_payload = {
        "bullets": [bullet.model_dump(mode="json") for bullet in approved_bullets],
        "rejected_bullets": [
            bullet.model_dump(mode="json") for bullet in rejected_bullets
        ],
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
        bullets=approved_bullets,
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
            "bullet_count": len(approved_bullets),
            "rejected_count": len(rejected_bullets),
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
            "review_status": output_payload.get("review_status"),
        },
    }
    selling_points_digest = _stable_payload_digest(pending_snapshot_payload)
    # A new human-approved authority invalidates copy/image/FAQ derived from
    # any previous approval before the reviewed snapshot is persisted.
    invalidate_evidence_outputs(product)
    product.selling_points_candidates_json = {
        **output_payload,
        "review_status": "reviewed",
    }
    product.selling_points_approved_json = output_payload
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
    orchestrator = KWorkflowOrchestratorV2(db)
    latest_execution = orchestrator.latest_execution_for_product(
        product_id=product.id,
        scope_context=_scope_context(request),
    )
    if (
        latest_execution is not None
        and orchestrator._risk_review_is_approved(latest_execution)
        and bool(latest_execution.final_keyword_set_json)
        and orchestrator._image_is_bound(product, latest_execution)
    ):
        orchestrator._mark_export_ready(product, latest_execution)
        db.add(latest_execution)
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
    # k_product_knowledge_media_assets 没有租户列，隔离靠 join 父产品表。
    # 2026-08-31 体检：这条以前只 where(status != "removed")，**零 scope**，
    # 制造组织超管能枚举国际贸易全部 117 条产品图元数据（SKU、变体色号、
    # 渲染管线存储路径）。图片字节没漏是因为 /media/{id}/file 逐条校验，
    # 但清单本身就是情报。
    scope = _scope_context(request)
    _scoped_media = (
        select(KProductKnowledgeMediaAsset.id)
        .join(
            KProductKnowledgeProduct,
            KProductKnowledgeProduct.id == KProductKnowledgeMediaAsset.product_id,
        )
        .where(
            KProductKnowledgeProduct.workspace_key == scope.workspace_key,
            KProductKnowledgeProduct.business_context == scope.business_context,
        )
    )
    query = select(KProductKnowledgeMediaAsset).where(
        KProductKnowledgeMediaAsset.status != "removed",
        KProductKnowledgeMediaAsset.id.in_(_scoped_media),
    )
    count_query = select(func.count()).select_from(KProductKnowledgeMediaAsset).where(
        KProductKnowledgeMediaAsset.status != "removed",
        KProductKnowledgeMediaAsset.id.in_(_scoped_media),
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
    img_width, img_height = _image_dimensions(contents)
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
        width=img_width,
        height=img_height,
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


class ImageUploadBoundRequest(BaseModel):
    bound: bool = True


@router.post(
    "/products/{product_id}/images/{asset_id}/upload-bound",
    response_model=MediaAssetRead,
)
def set_image_upload_bound(
    product_id: UUID,
    asset_id: UUID,
    payload: ImageUploadBoundRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> MediaAssetRead:
    """把一张手动上传的图标记「绑定(取图)」或取消。绑定的手动图会随 K 渲染图
    一起进 P 上架包;未绑定的不取。对 K 渲染图无影响(它们始终取)。"""
    del user
    product = get_product(
        db, product_id=product_id, scope_context=_scope_context(request)
    )
    asset = _image_asset_for_product(db, product=product, asset_id=asset_id)
    meta = dict(asset.metadata_json) if isinstance(asset.metadata_json, dict) else {}
    meta["upload_bound"] = bool(payload.bound)
    asset.metadata_json = meta
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _media_asset_read(asset, product_ref=_product_public_ref(product))


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
            width=item.width if item.width is not None else _image_dimensions(contents)[0],
            height=item.height if item.height is not None else _image_dimensions(contents)[1],
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


class BrandAuditIgnoreRequest(BaseModel):
    kind: str = Field(pattern="^(text|image)$")
    ignored: bool = True
    surface: str | None = None
    term: str | None = None
    position: int | None = None
    category: str | None = None
    # 图片指纹自 2026-08-31 起含 asset_id：忽略绑定到具体那一张图，
    # 重渲出新图就不再继承旧的放行。
    asset_id: str | None = None
    # 放行理由。留痕用，不做强制——但空理由会原样记进台账。
    reason: str = ""


@router.post("/products/{product_id}/brand-audit/ignore")
def product_knowledge_brand_audit_ignore(
    product_id: UUID,
    payload: BrandAuditIgnoreRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> dict[str, Any]:
    """人工放行/撤销一条品牌审查发现(误报或已人工确认保留)。被忽略的发现不再
    阻塞上架;errors 永不可忽略。审查重跑会结转忽略清单。"""
    from .brand_guard import (
        _audit_violation_fingerprints as _brand_audit_fingerprints,
        brand_finding_fingerprint,
        set_brand_finding_ignored,
    )

    product = get_product(
        db, product_id=product_id, scope_context=_scope_context(request)
    )
    fingerprint = brand_finding_fingerprint(
        payload.kind,
        {
            "surface": payload.surface,
            "term": payload.term,
            "position": payload.position,
            "category": payload.category,
            "asset_id": payload.asset_id,
        },
    )
    # 只允许忽略「当前审查结论里真实存在」的发现。
    # 以前不校验，等于可以对一个还不存在的违规预先放行——下次那个位号出什么问题
    # 都自动放行。撤销(ignored=False)不设限：那永远是收紧方向。
    if payload.ignored:
        audit_now = (
            product.brand_audit_json
            if isinstance(product.brand_audit_json, dict)
            else {}
        )
        known = set(
            _brand_audit_fingerprints(
                audit_now.get("text_violations") or [],
                audit_now.get("image_violations") or [],
            )
        )
        if fingerprint not in known:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="只能忽略当前审查结论里已存在的发现；请先重跑品牌审查。",
            )
    audit = set_brand_finding_ignored(
        db,
        product=product,
        fingerprint=fingerprint,
        ignored=payload.ignored,
        user=user,
        reason=payload.reason,
    )
    db.commit()
    return {"brand_audit_json": audit, "fingerprint": fingerprint}


class OperatingModelUpdateRequest(BaseModel):
    """运营者手改的「这个产品怎么工作」。"""

    how_it_works: str = ""
    hard_constraints: list[str] = Field(default_factory=list)
    forbidden_depictions: list[str] = Field(default_factory=list)
    buyer_personas: list[str] = Field(default_factory=list)


@router.put("/products/{product_id}/operating-model")
def product_knowledge_update_operating_model(
    product_id: UUID,
    payload: OperatingModelUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> dict[str, Any]:
    """人工修正产品的工作原理/物理约束/买家画像。

    存在 image_instruction_json["operating_model"]（零迁移）。置
    edited_by_user=True 后，重新生成作图指令不会再用 AI 推导覆盖它 —— 人工
    纠正永远权威（见 workflow_engine._resolve_operating_model）。
    """
    from sqlalchemy.orm.attributes import flag_modified

    product = get_product(
        db, product_id=product_id, scope_context=_scope_context(request)
    )
    brief = (
        dict(product.image_instruction_json)
        if isinstance(product.image_instruction_json, dict)
        else {}
    )
    previous = brief.get("operating_model")
    previous = previous if isinstance(previous, dict) else {}

    def _clean(values: list[str]) -> list[str]:
        out: list[str] = []
        for item in values:
            text_value = str(item).strip()[:300]
            if text_value and text_value not in out:
                out.append(text_value)
        return out[:8]

    brief["operating_model"] = {
        **previous,
        "how_it_works": payload.how_it_works.strip()[:1200],
        "hard_constraints": _clean(payload.hard_constraints),
        "forbidden_depictions": _clean(payload.forbidden_depictions),
        "buyer_personas": _clean(payload.buyer_personas),
        "edited_by_user": True,
        "edited_at": datetime.now(UTC).isoformat(),
    }
    product.image_instruction_json = brief
    flag_modified(product, "image_instruction_json")
    product.updated_by_user_id = user.id
    db.add(product)
    db.commit()
    return {"operating_model": brief["operating_model"]}


@router.get("/products/{product_id}/image-plates")
def product_knowledge_list_image_plates(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> dict[str, Any]:
    """能当作图底板的实拍图，带姿态与「是否已圈产品」。

    浮窗第一步用它：列出底图，标出哪些还没刷蒙版。没刷的图不会被当底板，
    所以不存在「忘了刷导致出错」——最多是可用场景少几个。
    """
    del user
    from .brand_guard import (
        POSE_NONE,
        product_operating_model,
        reference_kind_usable,
        reference_pose,
    )
    from .image_render_jobs import product_mask_by_plate

    product = get_product(
        db, product_id=product_id, scope_context=_scope_context(request)
    )
    operating_model = product_operating_model(product)
    classification = operating_model.get("reference_classification")
    classification = classification if isinstance(classification, dict) else {}
    masks = product_mask_by_plate(db, product)

    rows = db.scalars(
        select(KProductKnowledgeMediaAsset)
        .where(
            KProductKnowledgeMediaAsset.product_id == product.id,
            KProductKnowledgeMediaAsset.asset_role == "reference",
            KProductKnowledgeMediaAsset.status == "available",
            KProductKnowledgeMediaAsset.asset_type == "image",
        )
        .order_by(KProductKnowledgeMediaAsset.created_at.asc())
    ).all()

    items: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.object_key or "")
        pose = reference_pose(operating_model, key)
        usable = reference_kind_usable(classification.get(key))
        if not usable or pose == POSE_NONE:
            continue  # 证书/纯文字页当不了底板
        mask = masks.get(str(row.id))
        # 图片响应头是 max-age=31536000, immutable —— 那个前提是「URL 唯一
        # 标识内容」。参考图被原地修过(2026-08-03 串图修复)，URL 不变内容变了，
        # 浏览器连硬刷新都不会回源，六张缩略图会一直显示成同一张旧图。
        # 挂上内容指纹，内容一变 URL 就变，缓存自动失效。
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        version = str(meta.get("content_sha256") or "")[:12] or str(row.updated_at)
        items.append(
            {
                "asset_id": str(row.id),
                "pose": pose,
                "has_mask": mask is not None,
                "mask_asset_id": str(mask.id) if mask is not None else None,
                "width": row.width,
                "height": row.height,
                "file_url": f"/k/media/{row.id}/file?v={version}",
                "preview_url": f"/k/media/{row.id}/preview?v={version}",
                # 列表缩略图走 320px 派生图。用 preview(1280px) 铺一屏
                # 会一次拉好几 MB，首次打开明显发卡。
                "thumbnail_url": f"/k/media/{row.id}/thumbnail?v={version}",
            }
        )
    return {
        "items": items,
        "masked_count": sum(1 for item in items if item["has_mask"]),
    }


class ProductMaskUpdateRequest(BaseModel):
    """画笔导出的 PNG（data URL 或裸 base64）。"""

    mask_png_base64: str = Field(min_length=32)


@router.put("/products/{product_id}/image-plates/{asset_id}/mask")
def product_knowledge_put_plate_mask(
    product_id: UUID,
    asset_id: UUID,
    payload: ProductMaskUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> dict[str, Any]:
    """保存某张底图的「产品保护区」蒙版（覆盖式，一张底图只留一份）。"""
    from .image_render_jobs import store_product_mask_asset

    product = get_product(
        db, product_id=product_id, scope_context=_scope_context(request)
    )
    plate = _image_asset_for_product(db, product=product, asset_id=asset_id)

    raw = payload.mask_png_base64.strip()
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        contents = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="蒙版不是有效的 base64 PNG。",
        ) from exc

    try:
        mask = store_product_mask_asset(
            db, product=product, plate_asset=plate, contents=contents, user=user
        )
    except KImageRenderError as exc:
        _raise_render_error(exc)
    db.commit()
    return {
        "asset_id": str(plate.id),
        "mask_asset_id": str(mask.id),
        "bytes": len(contents),
    }


class BrandAuditOverrideRequest(BaseModel):
    """人工放行：审查结论不再拥有否决权。"""

    enabled: bool = True
    reason: str = ""


@router.post("/products/{product_id}/brand-audit/override")
def product_knowledge_brand_audit_override(
    product_id: UUID,
    payload: BrandAuditOverrideRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> dict[str, Any]:
    """人工放行整个产品的品牌审查（**高于一切 fail-closed 规则**）。

    2026-08-11 用户拍板：审查器是 AI，它不真正了解产品——花洒手柄上的
    "STOP"（一键止水标识）被判成品牌字样，"panda pump"（产品描述）被判成商标。
    运营者看过图、做了决定之后，这个控制台里不允许任何一道程序再拦他。

    打开后审查照跑、结论照存照显示，只是不再挡上架。开关留痕（谁/何时/为何）。
    """
    from .brand_guard import set_operator_override

    product = get_product(
        db, product_id=product_id, scope_context=_scope_context(request)
    )
    audit = set_operator_override(
        db,
        product=product,
        enabled=payload.enabled,
        user=user,
        reason=payload.reason,
    )
    db.commit()
    return {
        "brand_audit_json": audit,
        "operator_override": audit.get("operator_override"),
    }


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
    variant_color: str | None = None
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
    extra_prompt: str = ""
    use_current_as_reference: bool = False
    # 可选:为这张图贴专属参考图(优先级最高;落地为 reference 媒资)。
    # 两种来源二选一:reference_image_url=贴链接;reference_asset_id=先上传本地
    # 文件(asset_role=reference)拿到的资产 id。asset_id 优先。
    reference_image_url: str | None = Field(default=None, max_length=2000)
    reference_asset_id: UUID | None = None


class BriefImageAddRequest(BaseModel):
    scene: str = Field(min_length=1, max_length=2000)
    placement: Literal["gallery", "description"]
    reference_image_url: str | None = Field(default=None, max_length=2000)
    reference_asset_id: UUID | None = None


class BriefOverlayApplyRequest(BaseModel):
    source_fields: list[str] = Field(min_length=1, max_length=8)


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
    """单张重做：原 prompt + 临时修改要求；参考图 = 专属新参考图/这版图/原始参考图。"""
    scope_context = _scope_context(request)
    try:
        product = get_product(db, product_id=product_id, scope_context=scope_context)
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    reference_override = None
    if payload.reference_asset_id is not None:
        # 运营者先上传本地文件(asset_role=reference)拿到的资产,直接当参考图。
        reference_override = _image_asset_for_product(
            db, product=product, asset_id=payload.reference_asset_id
        )
    elif payload.reference_image_url:
        from .brief_operator_edits import store_operator_reference_asset

        try:
            reference_override = store_operator_reference_asset(
                db,
                product=product,
                reference_image_url=payload.reference_image_url.strip(),
                user=user,
            )
        except Exception as exc:  # noqa: BLE001 - 下载失败要人话报错
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"专属参考图下载失败：{str(exc)[:200]}",
            ) from exc
    try:
        batch_id, job = enqueue_rework_job(
            db,
            product=product,
            user=user,
            scope_context=scope_context,
            asset_id=payload.asset_id,
            extra_prompt=payload.extra_prompt,
            use_current_as_reference=payload.use_current_as_reference,
            reference_override=reference_override,
        )
    except KImageRenderError as exc:
        _raise_render_error(exc)
    db.commit()
    return RenderEnqueueResponse(
        batch_id=str(batch_id),
        jobs=[RenderJobItem(**job)],
    )


@router.post(
    "/products/{product_id}/brief-images",
    response_model=RenderEnqueueResponse,
)
def product_knowledge_brief_image_add(
    product_id: UUID,
    payload: BriefImageAddRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> RenderEnqueueResponse:
    """在 AI 作图方案之外新增一张图:手选去处,SEO 四件套保证齐全,当场排渲染。"""
    scope_context = _scope_context(request)
    try:
        product = get_product(db, product_id=product_id, scope_context=scope_context)
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    instruction = product.image_instruction_json
    if not isinstance(instruction, dict) or not isinstance(
        instruction.get("images"), list
    ) or not instruction["images"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先生成作图指令，再在方案之外新增图片。",
        )
    from .brief_operator_edits import (
        build_operator_brief_image,
        operator_image_prompt_and_seo,
        store_operator_reference_asset,
    )

    reference_asset_id: str | None = None
    if payload.reference_asset_id is not None:
        # 已上传的本地文件(asset_role=reference)直接当参考图。
        asset = _image_asset_for_product(
            db, product=product, asset_id=payload.reference_asset_id
        )
        reference_asset_id = str(asset.id)
    elif payload.reference_image_url:
        try:
            asset = store_operator_reference_asset(
                db,
                product=product,
                reference_image_url=payload.reference_image_url.strip(),
                user=user,
            )
            reference_asset_id = str(asset.id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"参考图下载失败：{str(exc)[:200]}",
            ) from exc
    prompt_and_seo = operator_image_prompt_and_seo(
        db, product=product, scene=payload.scene.strip()
    )
    positions = [
        int(image.get("position") or 0)
        for image in instruction["images"]
        if isinstance(image, dict)
    ]
    new_position = max(positions or [0]) + 1
    spec = build_operator_brief_image(
        position=new_position,
        placement=payload.placement,
        scene=payload.scene.strip(),
        prompt_and_seo=prompt_and_seo,
        reference_asset_id=reference_asset_id,
    )
    updated = dict(instruction)
    updated["images"] = [*instruction["images"], spec]
    updated["image_count"] = len(updated["images"])
    product.image_instruction_json = updated
    db.add(product)
    db.flush()
    try:
        batch_id, jobs = enqueue_image_render_jobs(
            db,
            product=product,
            user=user,
            scope_context=scope_context,
            positions=[new_position],
        )
    except KImageRenderError as exc:
        _raise_render_error(exc)
    db.commit()
    return RenderEnqueueResponse(
        batch_id=str(batch_id),
        jobs=[RenderJobItem(**job) for job in jobs],
    )


@router.get("/products/{product_id}/overlay-fields")
def product_knowledge_overlay_fields(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_READ)),
) -> dict[str, Any]:
    """「加标注」可选字段:当前产品已核实、可画上图的规格值。"""
    del user
    try:
        product = get_product(
            db, product_id=product_id, scope_context=_scope_context(request)
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    from .brief_operator_edits import available_overlay_fields

    return {"fields": available_overlay_fields(db, product)}


@router.post(
    "/products/{product_id}/brief-images/{position}/overlay",
    response_model=RenderEnqueueResponse,
)
def product_knowledge_brief_overlay_apply(
    product_id: UUID,
    position: int,
    payload: BriefOverlayApplyRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> RenderEnqueueResponse:
    """给方案中某张图加标注(真实规格值由合成器画上图)并重排渲染。"""
    scope_context = _scope_context(request)
    try:
        product = get_product(db, product_id=product_id, scope_context=scope_context)
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)
    instruction = product.image_instruction_json
    images = (
        instruction.get("images") if isinstance(instruction, dict) else None
    )
    if not isinstance(images, list) or not images:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先生成作图指令。",
        )
    target_index = next(
        (
            index
            for index, image in enumerate(images)
            if isinstance(image, dict) and int(image.get("position") or 0) == position
        ),
        None,
    )
    if target_index is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"作图方案里没有第 {position} 张图。",
        )
    target = dict(images[target_index])
    if str(target.get("role") or "").strip().lower() == "main":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="白底主图不允许加标注（家规：主图只有产品）。",
        )
    from .brief_operator_edits import build_preset_overlay

    try:
        overlay = build_preset_overlay(payload.source_fields)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    target["overlay"] = overlay
    target["role"] = "feature_callout"
    new_images = [*images]
    new_images[target_index] = target
    updated = dict(instruction)
    updated["images"] = new_images
    product.image_instruction_json = updated
    db.add(product)
    db.flush()
    try:
        batch_id, jobs = enqueue_image_render_jobs(
            db,
            product=product,
            user=user,
            scope_context=scope_context,
            positions=[position],
        )
    except KImageRenderError as exc:
        _raise_render_error(exc)
    db.commit()
    return RenderEnqueueResponse(
        batch_id=str(batch_id),
        jobs=[RenderJobItem(**job) for job in jobs],
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
        execution_options=SKIP_ORG_DATA_ISOLATION,
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


# ---------------------------------------------------------------------------
# FAQ 人工编辑（上架前/后均可）：page_faq 是唯一数据源——可见 FAQ、_kp_faq meta、
# FAQPage schema 全部由它派生，因此这里改完再「重推」，三处自动一致。
# 人工即质量门：运营编辑过的 FAQ 直接标记 schema 合格（红线仍硬卡：英文、问句）。
# ---------------------------------------------------------------------------


class ProductFaqItemPayload(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=1500)


class ProductFaqUpdateRequest(BaseModel):
    items: list[ProductFaqItemPayload] = Field(default_factory=list, max_length=8)


class ProductFaqUpdateResponse(BaseModel):
    page_faq: list[dict[str, Any]]
    faq_quality: dict[str, Any]
    faq_schema_eligible: bool


@router.put(
    "/products/{product_id}/faq",
    response_model=ProductFaqUpdateResponse,
)
def product_knowledge_update_faq(
    product_id: UUID,
    payload: ProductFaqUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_k_permission(PERMISSION_UPDATE)),
) -> ProductFaqUpdateResponse:
    del user
    try:
        product = get_product(
            db,
            product_id=product_id,
            scope_context=_scope_context(request),
        )
    except KProductKnowledgeError as exc:
        _raise_k_error(exc)

    errors: list[dict[str, Any]] = []
    cleaned: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    for index, item in enumerate(payload.items):
        question = " ".join(item.question.split()).strip()
        answer = " ".join(item.answer.split()).strip()
        problems: list[str] = []
        if contains_cjk(question) or contains_cjk(answer):
            problems.append("买家可见内容不允许中文（英文红线）")
        if not question:
            problems.append("问题不能为空")
        elif not question.endswith("?"):
            problems.append("问题必须是英文问句（以 ? 结尾）")
        elif not is_faq_text_brand_safe(question):
            problems.append("问题不得包含第三方品牌")
        if not answer:
            problems.append("答案不能为空")
        elif not is_faq_text_brand_safe(answer):
            problems.append("答案不得包含第三方品牌")
        key = question.casefold()
        if key and key in seen_questions:
            problems.append("问题重复")
        if problems:
            errors.append({"index": index, "question": question, "errors": problems})
            continue
        seen_questions.add(key)
        cleaned.append(
            {"question": question, "answer": answer, "source": "manual_review"}
        )
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "status": "failed",
                "reason": "invalid_faq",
                "code": "FAQ_MANUAL_VALIDATION_FAILED",
                "items": errors,
            },
        )

    mcj = dict(product.marketing_copy_json or {})
    mcj["page_faq"] = cleaned
    mcj["faq_quality"] = {
        "eligible_for_schema": bool(cleaned),
        "source": "manual_review",
        "question_count": len(cleaned),
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    product.marketing_copy_json = mcj
    db.add(product)
    db.commit()
    return ProductFaqUpdateResponse(
        page_faq=cleaned,
        faq_quality=mcj["faq_quality"],
        faq_schema_eligible=bool(cleaned),
    )


# ---------------------------------------------------------------------------
# 兼容 re-export（2026-09-03 起，剥 service 层时保留）
# ---------------------------------------------------------------------------
#
# 上面那些 `_xxx` 已经搬到 `services/api_support.py`，这里用 import 把名字
# 保留在本模块的命名空间里 —— 22 个存量测试文件直接 `from ...router import _xxx`，
# 少一个名字整份测试文件会以 ImportError 崩掉（不是某条断言变红），
# 在一堆输出里很容易被误读成「环境问题」。
#
# 兼容面由 `tests/backend/test_k_router_route_inventory.py` 逐个符号钉住。
# 全部剥完后单独一个提交改测试的 import、删掉这一层。
__all__ = [name for name in dir() if not name.startswith("__")]