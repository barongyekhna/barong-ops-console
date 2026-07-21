"""W-S logistics hub API.

Human endpoints manage templates, imported order snapshots, and manually
entered tracking numbers.  Machine endpoints receive n8n/17TRACK callbacks.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from math import ceil
from typing import Any, Literal
from uuid import UUID

from anyio import to_thread
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.config import Settings, get_settings
from ...core.roles import is_super_admin_role
from ...db.session import SessionLocal, get_db
from ...models.user import User
from ...services.permission_service import resolve_current_user_permission_info
from ..k_series.product_knowledge.models import KProductKnowledgeProduct
from . import logistics, product_sources
from .logistics_schemas import (
    OrderItem,
    OrderListResponse,
    OrdersIngestRequest,
    OrdersIngestResponse,
    PublicTrackLookupRequest,
    PublicTrackLookupResponse,
    PublicTrackResult,
    PublicTrackingEvent,
    ShippingSyncJobResponse,
    SyncResultRequest,
    SyncResultResponse,
    TrackingPatchRequest,
    TrackingPatchResponse,
    TrackingRefreshResponse,
    ZoneRate,
)
from .shipping import engine, service
from .shipping.models import (
    WOrder,
    WProductSource,
    WShippingClass,
    WShippingRule,
    WSyncJob,
)
from .source_schemas import (
    ProductSourceListResponse,
    ProductSourceRead,
    ProductSourceUpsertRequest,
)

router = APIRouter(prefix="/w", tags=["w-site-ops"])
# Server-to-server endpoints are also mounted at bare /w paths in main.py.
machine_router = APIRouter(prefix="/w", tags=["w-site-ops-machine"])
public_router = APIRouter(prefix="/track", tags=["w-site-ops-public"])

MODULE_KEY = "w.site_ops"
PERMISSION_READ = "w.site_ops.read"
PERMISSION_MANAGE = "w.site_ops.manage"
SOURCE_PAGE_SIZE = 50
MAX_PUBLIC_TRACK_BODY_BYTES = 32 * 1024
PUBLIC_TRACKING_STATUSES = frozenset(
    {
        "not_found",
        "info_received",
        "in_transit",
        "out_for_delivery",
        "delivered",
        "exception",
        "expired",
    }
)

logger = logging.getLogger(__name__)


def _require_w_permission(permission_key: str):
    """Owner / super-admin bypass; manage permission implies read."""

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(db, user, request=request)
        allowed_keys = {permission_key}
        if permission_key == PERMISSION_READ:
            allowed_keys.add(PERMISSION_MANAGE)
        if (
            permissions.is_owner_full_access
            or is_super_admin_role(user.role)
            or allowed_keys.intersection(permissions.permission_keys)
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission_key}",
        )

    return dependency


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShippingClassCreateRequest(StrictRequest):
    slug: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    zone_rates_json: list[ZoneRate] | None = None
    origin: Literal["cn_direct", "us_stock"] = "cn_direct"
    notes: str | None = None
    sort_order: int = 100

    @field_validator("slug", "name")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class ShippingClassPatchRequest(StrictRequest):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    zone_rates_json: list[ZoneRate] | None = None
    origin: Literal["cn_direct", "us_stock"] | None = None
    notes: str | None = None
    active: bool | None = None
    sort_order: int | None = None

    @field_validator("name", "origin", "active", "sort_order")
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("must not be null")
        return value

    @field_validator("name")
    @classmethod
    def _name_nonblank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class ShippingClassItem(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    zone_rates_json: list[ZoneRate] | None
    sync_status: str
    woo_class_id: int | None
    synced_at: str | None
    sync_error: str | None
    origin: str
    notes: str | None
    active: bool
    sort_order: int
    created_at: str | None
    updated_at: str | None


class ShippingRuleCreateRequest(StrictRequest):
    priority: int
    rule_type: Literal[
        "us_stock_override",
        "battery_override",
        "weight_band",
    ]
    min_weight_kg: Decimal | None = None
    max_weight_kg: Decimal | None = None
    shipping_class_slug: str = Field(min_length=1, max_length=128)
    active: bool = True
    notes: str | None = None

    @field_validator("shipping_class_slug")
    @classmethod
    def _slug_nonblank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class ShippingRulePatchRequest(StrictRequest):
    priority: int | None = None
    min_weight_kg: Decimal | None = None
    max_weight_kg: Decimal | None = None
    shipping_class_slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    active: bool | None = None
    notes: str | None = None

    @field_validator("priority", "shipping_class_slug", "active")
    @classmethod
    def _required_when_present(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("must not be null")
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be blank")
        return value.strip() if isinstance(value, str) else value


class ShippingRuleItem(BaseModel):
    id: str
    priority: int
    rule_type: str
    min_weight_kg: float | None
    max_weight_kg: float | None
    shipping_class_slug: str
    active: bool
    notes: str | None
    created_at: str | None
    updated_at: str | None


class SimulateRequest(StrictRequest):
    weight_kg: Decimal | None = None
    volumetric_kg: Decimal | None = None
    contains_battery: bool
    us_stock: bool


class SimulateResponse(BaseModel):
    shipping_class_slug: str | None
    rule_id: str | None
    rule_type: str | None
    weight_kg: float | None
    volumetric_kg: float | None
    used_kg: float | None
    review_needed: bool
    review_reason: str | None


class AssignRequest(StrictRequest):
    force: bool = False


class AssignResponse(SimulateResponse):
    product_id: str
    skipped_manual: bool
    assignment: dict[str, Any] | None


class AssignAllResponse(BaseModel):
    assigned: int
    review_needed: int
    skipped_manual: int
    unresolved: int


class BoardSummary(BaseModel):
    total_dtc: int
    assigned: int
    unassigned: int
    review_needed: int
    exported_missing: int


class BoardItem(BaseModel):
    product_id: str
    product_name: str | None
    sku: str | None
    channel: str
    weight_kg: float | None
    volumetric_kg: float | None
    used_kg: float | None
    contains_battery: bool
    us_stock: bool
    shipping_class_slug: str | None
    shipping_class_name: str | None
    assignment: dict[str, Any] | None
    review_needed: bool
    exported: bool


class BoardResponse(BaseModel):
    summary: BoardSummary
    items: list[BoardItem]


class ProductShippingPatchRequest(StrictRequest):
    shipping_class_slug: str | None = Field(default=None, max_length=128)
    contains_battery: bool | None = None
    us_stock: bool | None = None
    clear_review: bool = False


class ProductShippingPatchResponse(BaseModel):
    product_id: str
    shipping_class_slug: str | None
    contains_battery: bool
    us_stock: bool
    assignment: dict[str, Any] | None
    review_needed: bool


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _class_item(row: WShippingClass) -> ShippingClassItem:
    return ShippingClassItem(
        id=str(row.id),
        slug=row.slug,
        name=row.name,
        description=row.description,
        zone_rates_json=row.zone_rates_json,
        sync_status=row.sync_status,
        woo_class_id=row.woo_class_id,
        synced_at=_iso(row.synced_at),
        sync_error=row.sync_error,
        origin=row.origin,
        notes=row.notes,
        active=row.active,
        sort_order=row.sort_order,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _order_item(row: WOrder) -> OrderItem:
    events = (
        row.tracking_events_json
        if isinstance(row.tracking_events_json, list)
        else None
    )
    items = row.items_json if isinstance(row.items_json, list) else None
    return OrderItem(
        id=str(row.id),
        woo_order_id=row.woo_order_id,
        order_number=row.order_number,
        woo_status=row.woo_status,
        customer_name=row.customer_name,
        country=row.country,
        total=row.total,
        currency=row.currency,
        items_json=items,
        placed_at=row.placed_at,
        tracking_number=row.tracking_number,
        carrier_code=row.carrier_code,
        tracking_status=row.tracking_status,
        tracking_events_json=events,
        tracking_registered=bool(row.tracking_registered),
        last_tracking_update=row.last_tracking_update,
        writeback_status=row.writeback_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _required_source_sku(raw_sku: str) -> str:
    normalized = product_sources.normalize_sku(raw_sku)
    if not normalized:
        raise HTTPException(status_code=422, detail="SKU 不能为空。")
    if len(normalized) > 64:
        raise HTTPException(status_code=422, detail="SKU 最长 64 个字符。")
    return normalized


def _apply_product_source_payload(
    row: WProductSource,
    payload: ProductSourceUpsertRequest,
) -> None:
    for field, value in payload.model_dump(exclude={"sku"}).items():
        setattr(row, field, value)


def _order_items_with_sources(
    db: Session,
    rows: list[WOrder],
) -> list[OrderItem]:
    """Serialize first so a failed source query cannot poison order output."""

    order_items = [_order_item(row) for row in rows]
    try:
        sources_by_sku = product_sources.load_sources_for_items(
            db,
            (order.items_json for order in order_items),
        )
        return [
            order.model_copy(
                update={
                    "items_json": product_sources.enrich_items(
                        order.items_json,
                        sources_by_sku,
                    )
                }
            )
            for order in order_items
        ]
    except Exception:  # noqa: BLE001 - source lookup must never hide orders
        logger.exception("W-S product source enrichment failed; using missing state")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001 - response is already detached from ORM
            logger.exception("W-S product source fail-safe rollback failed")
        return [
            order.model_copy(
                update={
                    "items_json": product_sources.enrich_items(
                        order.items_json,
                        {},
                    )
                }
            )
            for order in order_items
        ]


def _track_public_error(status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False})


def _expected_track_public_key(settings: Settings) -> str:
    secret = settings.track_public_key
    return secret.get_secret_value() if secret is not None else ""


def _track_public_key_is_valid(
    supplied_key: str | None,
    settings: Settings,
) -> bool:
    expected = _expected_track_public_key(settings)
    supplied = supplied_key or ""
    compared = secrets.compare_digest(
        sha256(expected.encode("utf-8")).digest(),
        sha256(supplied.encode("utf-8")).digest(),
    )
    return bool(expected and supplied and compared)


class _PublicTrackPayloadError(ValueError):
    pass


async def _read_public_track_body(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type.strip().lower() != "application/json":
        raise _PublicTrackPayloadError("content type must be JSON")

    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            raise _PublicTrackPayloadError("invalid content length") from exc
        if declared_size > MAX_PUBLIC_TRACK_BODY_BYTES:
            raise _PublicTrackPayloadError("payload too large")

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_PUBLIC_TRACK_BODY_BYTES:
            raise _PublicTrackPayloadError("payload too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _unknown_public_track_result(order_number: str) -> PublicTrackResult:
    return PublicTrackResult(
        order_number=order_number,
        state="unknown",
        tracking_number=None,
        carrier_code=None,
        tracking_status=None,
        last_update=None,
        events=[],
    )


def _public_tracking_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return normalized.astimezone(UTC)


def _public_tracking_status(value: object) -> str:
    tracking_status = str(value or "").strip()
    if tracking_status in PUBLIC_TRACKING_STATUSES:
        return tracking_status
    if tracking_status == "registered":
        # Existing W registration writes this internal pre-event marker. The
        # public contract has no equivalent beyond not_found until 17TRACK
        # supplies its first normalized status.
        return "not_found"
    raise ValueError("invalid persisted tracking status")


def _public_tracking_events(value: object) -> list[PublicTrackingEvent]:
    if not isinstance(value, list):
        return []
    events: list[PublicTrackingEvent] = []
    for raw_event in value:
        if not isinstance(raw_event, dict):
            raise ValueError("invalid persisted tracking event")
        # Construct a strict allowlist instead of validating the whole stored
        # object, so future internal metadata can never leak through this API.
        events.append(
            PublicTrackingEvent(
                time=raw_event.get("time"),
                location=raw_event.get("location"),
                description=raw_event.get("description"),
            )
        )
    return events


def _lookup_public_track_result(
    db: Session,
    order_number: str,
) -> PublicTrackResult:
    # order_number predates this endpoint and is not unique. Prefer the latest
    # Woo order deterministically if historical duplicates exist.
    row = db.scalar(
        select(WOrder)
        .where(WOrder.order_number == order_number)
        .order_by(WOrder.updated_at.desc(), WOrder.woo_order_id.desc())
        .limit(1)
    )
    if row is None:
        return _unknown_public_track_result(order_number)

    tracking_number = (row.tracking_number or "").strip()
    if not tracking_number:
        return PublicTrackResult(
            order_number=order_number,
            state="not_shipped",
            tracking_number=None,
            carrier_code=None,
            tracking_status=None,
            last_update=None,
            events=[],
        )

    return PublicTrackResult(
        order_number=order_number,
        state="tracked",
        tracking_number=tracking_number,
        carrier_code=row.carrier_code,
        tracking_status=_public_tracking_status(row.tracking_status),
        last_update=_public_tracking_timestamp(row.last_tracking_update),
        events=_public_tracking_events(row.tracking_events_json),
    )


def _process_public_track_lookup(
    raw_body: bytes,
) -> tuple[int, PublicTrackLookupResponse | None]:
    try:
        with SessionLocal() as db:
            try:
                allowed = logistics.register_track_public_rate_limit(db)
                # The shared bucket must survive the read-only order session and
                # must count requests that later fail payload validation.
                db.commit()
            except IntegrityError:
                db.rollback()
                logger.warning("Public tracking rate-limit contention")
                return status.HTTP_429_TOO_MANY_REQUESTS, None
            except SQLAlchemyError:
                db.rollback()
                logger.exception("Public tracking rate limiter unavailable")
                return status.HTTP_503_SERVICE_UNAVAILABLE, None

            if not allowed:
                return status.HTTP_429_TOO_MANY_REQUESTS, None

            try:
                raw_payload = json.loads(raw_body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return status.HTTP_422_UNPROCESSABLE_ENTITY, None

            try:
                payload = PublicTrackLookupRequest.model_validate(raw_payload)
            except ValidationError:
                return status.HTTP_422_UNPROCESSABLE_ENTITY, None

            results: list[PublicTrackResult] = []
            for order_number in payload.order_numbers:
                try:
                    # A savepoint prevents one failed statement from poisoning
                    # the PostgreSQL transaction used by subsequent lookups.
                    with db.begin_nested():
                        result = _lookup_public_track_result(db, order_number)
                except Exception:  # noqa: BLE001 - contract requires per-item fallback
                    logger.exception(
                        "Public tracking lookup failed order_number=%r",
                        order_number,
                    )
                    result = _unknown_public_track_result(order_number)
                results.append(result)

            return (
                status.HTTP_200_OK,
                PublicTrackLookupResponse(results=results),
            )
    except Exception:  # noqa: BLE001 - public endpoint fails closed
        logger.exception("Public tracking database session unavailable")
        return status.HTTP_503_SERVICE_UNAVAILABLE, None


@public_router.post(
    "/lookup",
    response_model=PublicTrackLookupResponse,
    openapi_extra={
        "parameters": [
            {
                "name": "X-BY-TRACK-KEY",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
            }
        ],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": PublicTrackLookupRequest.model_json_schema(),
                }
            },
        }
    },
)
async def public_track_lookup(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Response:
    if not _track_public_key_is_valid(
        request.headers.get("X-BY-TRACK-KEY"),
        settings,
    ):
        return _track_public_error(status.HTTP_401_UNAUTHORIZED)

    try:
        raw_body = await _read_public_track_body(request)
    except _PublicTrackPayloadError:
        return _track_public_error(status.HTTP_422_UNPROCESSABLE_ENTITY)

    response_status, response = await to_thread.run_sync(
        _process_public_track_lookup,
        raw_body,
    )
    if response is None:
        return _track_public_error(response_status)
    return JSONResponse(
        status_code=response_status,
        content=response.model_dump(mode="json"),
    )


def _rule_item(row: WShippingRule) -> ShippingRuleItem:
    return ShippingRuleItem(
        id=str(row.id),
        priority=row.priority,
        rule_type=row.rule_type,
        min_weight_kg=(
            float(row.min_weight_kg) if row.min_weight_kg is not None else None
        ),
        max_weight_kg=(
            float(row.max_weight_kg) if row.max_weight_kg is not None else None
        ),
        shipping_class_slug=row.shipping_class_slug,
        active=row.active,
        notes=row.notes,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _decision_response(
    decision: engine.ShippingDecision,
) -> SimulateResponse:
    return SimulateResponse(
        shipping_class_slug=decision.shipping_class_slug,
        rule_id=decision.rule_id,
        rule_type=decision.rule_type,
        weight_kg=decision.weight_kg,
        volumetric_kg=decision.volumetric_kg,
        used_kg=decision.used_kg,
        review_needed=decision.review_needed,
        review_reason=decision.review_reason,
    )


def _load_product(db: Session, product_id: UUID) -> KProductKnowledgeProduct:
    product = db.get(KProductKnowledgeProduct, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在。")
    return product


@router.get("/shipping/classes", response_model=list[ShippingClassItem])
def shipping_classes_list(
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_READ)),
) -> list[ShippingClassItem]:
    del user
    if logistics.reap_stale_sync_jobs(db):
        db.commit()
    return [_class_item(row) for row in service.list_shipping_classes(db)]


@router.post(
    "/shipping/classes",
    response_model=ShippingClassItem,
    status_code=status.HTTP_201_CREATED,
)
def shipping_class_create(
    payload: ShippingClassCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> ShippingClassItem:
    del user
    try:
        row = service.create_shipping_class(db, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return _class_item(row)


@router.patch("/shipping/classes/{class_id}", response_model=ShippingClassItem)
def shipping_class_patch(
    class_id: UUID,
    payload: ShippingClassPatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> ShippingClassItem:
    del user
    row = db.scalar(
        select(WShippingClass)
        .where(WShippingClass.id == class_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="运费模板不存在。")
    in_flight = db.scalar(
        select(WSyncJob.id)
        .where(WSyncJob.target_type == "shipping_class")
        .where(WSyncJob.target_id == row.id)
        .where(WSyncJob.status.in_(logistics.SYNC_IN_FLIGHT_STATUSES))
        .limit(1)
    )
    if in_flight is not None:
        raise HTTPException(
            status_code=409,
            detail="该模板已有同步任务在执行中。",
        )
    service.update_shipping_class(row, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(row)
    return _class_item(row)


@router.delete("/shipping/classes/{class_id}", status_code=status.HTTP_202_ACCEPTED)
def shipping_class_delete(
    class_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> dict[str, Any]:
    """删除运费模板：有产品挂靠先拒绝；已同步过的派 n8n 删 Woo 侧，
    回调成功后本地行才删除；从未同步过的（无 woo_class_id）直接删本地。"""
    del user
    row = db.scalar(
        select(WShippingClass)
        .where(WShippingClass.id == class_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="运费模板不存在。")

    referencing = db.scalar(
        select(func.count())
        .select_from(KProductKnowledgeProduct)
        .where(KProductKnowledgeProduct.shipping_class == row.slug)
    )
    if referencing:
        raise HTTPException(
            status_code=409,
            detail=f"有 {referencing} 个产品挂在此模板上，先重算或改挂其他模板再删除。",
        )

    if row.woo_class_id is None:
        # 从未同步进 Woo：本地草稿直接删，不派 n8n。
        db.delete(row)
        db.commit()
        return {"deleted": True, "dispatched": False}

    try:
        job = logistics.create_shipping_delete_job(db, row)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    _job, dispatched = logistics.dispatch_sync_job(db, job.job_id)
    return {"deleted": False, "dispatched": dispatched, "job_id": job.job_id}


@router.post(
    "/shipping/classes/{class_id}/sync",
    response_model=ShippingSyncJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def shipping_class_sync(
    class_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> ShippingSyncJobResponse:
    del user
    row = db.scalar(
        select(WShippingClass)
        .where(WShippingClass.id == class_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="运费模板不存在。")
    try:
        job = logistics.create_shipping_sync_job(db, row)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Persist the one-time token before any slow network call.
    db.commit()
    job, dispatched = logistics.dispatch_sync_job(db, job.job_id)
    return ShippingSyncJobResponse(
        job_id=job.job_id,
        status=job.status,
        dispatched=dispatched,
    )


@router.get("/shipping/rules", response_model=list[ShippingRuleItem])
def shipping_rules_list(
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_READ)),
) -> list[ShippingRuleItem]:
    del user
    return [_rule_item(row) for row in service.list_shipping_rules(db)]


@router.post(
    "/shipping/rules",
    response_model=ShippingRuleItem,
    status_code=status.HTTP_201_CREATED,
)
def shipping_rule_create(
    payload: ShippingRuleCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> ShippingRuleItem:
    del user
    try:
        row = service.create_shipping_rule(db, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return _rule_item(row)


@router.patch("/shipping/rules/{rule_id}", response_model=ShippingRuleItem)
def shipping_rule_patch(
    rule_id: UUID,
    payload: ShippingRulePatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> ShippingRuleItem:
    del user
    row = service.get_shipping_rule(db, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="分配规则不存在。")
    try:
        service.update_shipping_rule(
            db,
            row,
            payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return _rule_item(row)


@router.delete(
    "/shipping/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def shipping_rule_delete(
    rule_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> Response:
    del user
    row = service.get_shipping_rule(db, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="分配规则不存在。")
    service.delete_shipping_rule(db, row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/shipping/simulate", response_model=SimulateResponse)
def shipping_simulate(
    payload: SimulateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_READ)),
) -> SimulateResponse:
    del user
    decision = service.simulate(db, **payload.model_dump())
    return _decision_response(decision)


@router.post("/shipping/assign/{product_id}", response_model=AssignResponse)
def shipping_assign_one(
    product_id: UUID,
    payload: AssignRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> AssignResponse:
    del user
    product = _load_product(db, product_id)
    decision = service.assign_one(db, product, force=payload.force)
    db.commit()
    assignment = product.shipping_assignment_json
    base = _decision_response(decision).model_dump()
    return AssignResponse(
        **base,
        product_id=str(product.id),
        skipped_manual=decision.skipped_manual,
        assignment=assignment if isinstance(assignment, dict) else None,
    )


@router.post("/shipping/assign-all", response_model=AssignAllResponse)
def shipping_assign_all(
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> AssignAllResponse:
    del user
    return AssignAllResponse(**service.assign_all_dtc(db))


@router.get("/shipping/board", response_model=BoardResponse)
def shipping_board(
    filter_name: Literal[
        "all",
        "unassigned",
        "review",
        "exported_missing",
    ] = Query(default="all", alias="filter"),
    limit: int = Query(default=500, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_READ)),
) -> BoardResponse:
    del user
    return BoardResponse(
        **service.shipping_board(db, filter_name=filter_name, limit=limit)
    )


@router.patch(
    "/shipping/products/{product_id}",
    response_model=ProductShippingPatchResponse,
)
def shipping_product_patch(
    product_id: UUID,
    payload: ProductShippingPatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> ProductShippingPatchResponse:
    del user
    product = _load_product(db, product_id)
    fields = payload.model_fields_set
    try:
        service.manually_update_product(
            db,
            product,
            shipping_class_present="shipping_class_slug" in fields,
            shipping_class_slug=payload.shipping_class_slug,
            contains_battery_present="contains_battery" in fields,
            contains_battery=payload.contains_battery,
            us_stock_present="us_stock" in fields,
            us_stock=payload.us_stock,
            clear_review=payload.clear_review,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    assignment = product.shipping_assignment_json
    return ProductShippingPatchResponse(
        product_id=str(product.id),
        shipping_class_slug=(product.shipping_class or "").strip() or None,
        contains_battery=bool(product.contains_battery),
        us_stock=bool(product.us_stock),
        assignment=assignment if isinstance(assignment, dict) else None,
        review_needed=bool(product.shipping_review_needed),
    )


@router.get("/sources", response_model=ProductSourceListResponse)
def product_sources_list(
    query: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_READ)),
) -> ProductSourceListResponse:
    del user
    filters: list[Any] = []
    search_term = (query or "").strip()
    if search_term:
        pattern = f"%{search_term}%"
        filters.append(
            or_(
                WProductSource.sku.ilike(pattern),
                WProductSource.supplier_name.ilike(pattern),
            )
        )

    total = int(
        db.scalar(
            select(func.count())
            .select_from(WProductSource)
            .where(*filters)
        )
        or 0
    )
    rows = list(
        db.scalars(
            select(WProductSource)
            .where(*filters)
            .order_by(
                WProductSource.updated_at.desc(),
                WProductSource.created_at.desc(),
                WProductSource.id.desc(),
            )
            .offset((page - 1) * SOURCE_PAGE_SIZE)
            .limit(SOURCE_PAGE_SIZE)
        ).all()
    )
    return ProductSourceListResponse(
        items=[ProductSourceRead.model_validate(row) for row in rows],
        page=page,
        page_size=SOURCE_PAGE_SIZE,
        total=total,
        pages=max(1, ceil(total / SOURCE_PAGE_SIZE)),
    )


@router.put("/sources/{sku}", response_model=ProductSourceRead)
def product_source_upsert(
    sku: str,
    payload: ProductSourceUpsertRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> ProductSourceRead:
    del user
    normalized_sku = _required_source_sku(sku)
    if payload.sku is not None and payload.sku != normalized_sku:
        raise HTTPException(status_code=422, detail="body SKU 与路径 SKU 不一致。")

    row = db.scalar(
        select(WProductSource)
        .where(WProductSource.sku == normalized_sku)
        .with_for_update()
    )
    if row is None:
        row = WProductSource(sku=normalized_sku, source_url=payload.source_url)
        db.add(row)
    _apply_product_source_payload(row, payload)

    try:
        db.commit()
    except IntegrityError as first_error:
        # A concurrent creator can win between SELECT and INSERT.  Retrying as
        # an update preserves PUT upsert semantics instead of returning 409.
        db.rollback()
        row = db.scalar(
            select(WProductSource)
            .where(WProductSource.sku == normalized_sku)
            .with_for_update()
        )
        if row is None:
            raise HTTPException(
                status_code=409,
                detail="货源保存冲突，请重试。",
            ) from first_error
        _apply_product_source_payload(row, payload)
        try:
            db.commit()
        except IntegrityError as retry_error:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="货源保存冲突，请重试。",
            ) from retry_error

    db.refresh(row)
    return ProductSourceRead.model_validate(row)


@router.delete("/sources/{sku}", status_code=status.HTTP_204_NO_CONTENT)
def product_source_delete(
    sku: str,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> Response:
    del user
    normalized_sku = _required_source_sku(sku)
    row = db.scalar(
        select(WProductSource)
        .where(WProductSource.sku == normalized_sku)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="货源不存在。")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/orders", response_model=OrderListResponse)
def orders_list(
    filter_name: Literal["pending", "tracked", "all"] = Query(
        default="pending",
        alias="filter",
    ),
    limit: int = Query(default=500, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_READ)),
) -> OrderListResponse:
    del user
    if logistics.reap_stale_sync_jobs(db):
        db.commit()
    summary, rows = logistics.list_orders(
        db,
        filter_name=filter_name,
        limit=limit,
    )
    return OrderListResponse(
        summary=summary,
        orders=_order_items_with_sources(db, rows),
    )


@router.patch(
    "/orders/{order_id}/tracking",
    response_model=TrackingPatchResponse,
)
def order_tracking_patch(
    order_id: UUID,
    payload: TrackingPatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_MANAGE)),
) -> TrackingPatchResponse:
    del user
    order = db.scalar(
        select(WOrder).where(WOrder.id == order_id).with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")

    tracking_number = payload.tracking_number
    if tracking_number is None:
        already_clear = order.tracking_number is None and order.carrier_code is None
        if already_clear and order.writeback_status in ("pending", "success"):
            pending_job_id = logistics.pending_order_writeback_job_id(db, order.id)
            response = TrackingPatchResponse(order=_order_item(order))
            db.commit()
            if pending_job_id is not None:
                try:
                    logistics.dispatch_sync_job(db, pending_job_id)
                except Exception:  # noqa: BLE001 - the queued job stays durable
                    db.rollback()
            return response
        order.tracking_number = None
        order.carrier_code = None
        order.tracking_status = "none"
        order.tracking_events_json = None
        order.tracking_registered = False
        order.last_tracking_update = None
        writeback_job = logistics.create_order_writeback_job(db, order)
        writeback_job_id = writeback_job.job_id
        db.commit()
        try:
            logistics.dispatch_sync_job(db, writeback_job_id)
        except Exception:  # noqa: BLE001 - local clear must remain durable
            db.rollback()
        order = db.get(WOrder, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="订单不存在。")
        return TrackingPatchResponse(order=_order_item(order))

    number_changed = tracking_number != order.tracking_number
    carrier_changed = payload.carrier_code != order.carrier_code
    registration_required = (
        number_changed or carrier_changed or not order.tracking_registered
    )
    writeback_required = (
        number_changed
        or carrier_changed
        or order.writeback_status in ("none", "failed")
    )
    if (
        not registration_required
        and not writeback_required
    ):
        pending_job_id = logistics.pending_order_writeback_job_id(db, order.id)
        response = TrackingPatchResponse(order=_order_item(order))
        db.commit()
        if pending_job_id is not None:
            try:
                logistics.dispatch_sync_job(db, pending_job_id)
            except Exception:  # noqa: BLE001 - the queued job stays durable
                db.rollback()
        return response

    if number_changed or carrier_changed:
        logistics.supersede_order_writeback_jobs(db, order.id)
        order.writeback_status = "none"
    order.tracking_number = tracking_number
    order.carrier_code = payload.carrier_code
    if number_changed or carrier_changed:
        order.tracking_events_json = None
        order.last_tracking_update = None
    if registration_required:
        order.tracking_registered = False
        if order.last_tracking_update is None:
            order.tracking_status = "not_found"
        # The number must survive even if either downstream integration is down.
        db.commit()

    warning: str | None = None
    if registration_required:
        registered, warning = logistics.register_tracking(
            db,
            tracking_number,
            payload.carrier_code,
        )
        order = db.scalar(
            select(WOrder).where(WOrder.id == order_id).with_for_update()
        )
        if order is None:
            raise HTTPException(status_code=404, detail="订单不存在。")
        if (
            order.tracking_number != tracking_number
            or order.carrier_code != payload.carrier_code
        ):
            current = _order_item(order)
            db.rollback()
            return TrackingPatchResponse(order=current)
        if order.last_tracking_update is None:
            order.tracking_registered = registered
            order.tracking_status = "registered" if registered else "not_found"
        else:
            # A signed webhook may advance the shipment while register is in flight.
            order.tracking_registered = True

    if writeback_required:
        writeback_job = logistics.create_order_writeback_job(db, order)
        writeback_job_id: str | None = writeback_job.job_id
    else:
        writeback_job_id = None
    db.commit()

    if writeback_job_id is not None:
        try:
            logistics.dispatch_sync_job(db, writeback_job_id)
        except Exception:  # noqa: BLE001 - Woo writeback never blocks number entry
            db.rollback()
    order = db.get(WOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")
    return TrackingPatchResponse(
        order=_order_item(order),
        tracking_warning=warning,
    )


@router.post(
    "/orders/{order_id}/refresh-tracking",
    response_model=TrackingRefreshResponse,
)
def order_tracking_refresh(
    order_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_w_permission(PERMISSION_READ)),
) -> TrackingRefreshResponse:
    del user
    order = db.get(WOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")
    if not order.tracking_number:
        raise HTTPException(status_code=409, detail="该订单尚未填写运单号。")
    expected_number = order.tracking_number
    expected_carrier = order.carrier_code
    try:
        record = logistics.get_tracking_info(
            db,
            expected_number,
            expected_carrier,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail="17TRACK 密钥未绑定（去密钥管理添加）。",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - external response is untrusted
        raise HTTPException(
            status_code=502,
            detail=f"17TRACK 轨迹刷新失败：{logistics._remote_error(exc)}",
        ) from exc
    order = db.scalar(
        select(WOrder).where(WOrder.id == order_id).with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")
    if (
        order.tracking_number != expected_number
        or order.carrier_code != expected_carrier
    ):
        current = _order_item(order)
        db.rollback()
        return TrackingRefreshResponse(order=current)
    logistics.apply_tracking_record(order, record, deduplicate=True)
    db.commit()
    db.refresh(order)
    return TrackingRefreshResponse(order=_order_item(order))


@machine_router.post("/sync/{job_id}/result", response_model=SyncResultResponse)
def sync_result(
    job_id: str,
    payload: SyncResultRequest,
    x_job_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> SyncResultResponse:
    try:
        job = logistics.record_sync_result(
            db,
            job_id=job_id,
            token=x_job_token,
            result_status=payload.status,
            woo_class_id=payload.woo_class_id,
            error=payload.error,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="job token 无效。") from exc
    if job is None:
        raise HTTPException(status_code=404, detail="job 不存在。")
    response_job_id = job.job_id
    response_status = job.status
    next_job_id: str | None = None
    if job.target_type == "order_tracking":
        next_job_id = logistics.pending_order_writeback_job_id(db, job.target_id)
    db.commit()
    if next_job_id is not None and next_job_id != response_job_id:
        try:
            logistics.dispatch_sync_job(db, next_job_id)
        except Exception:  # noqa: BLE001 - callback acknowledgement must be stable
            db.rollback()
    return SyncResultResponse(job_id=response_job_id, status=response_status)


@machine_router.post("/orders/ingest", response_model=OrdersIngestResponse)
def orders_ingest(
    payload: OrdersIngestRequest,
    x_ingest_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> OrdersIngestResponse:
    expected = os.getenv("W_ORDERS_INGEST_TOKEN") or ""
    supplied = x_ingest_token or ""
    if not expected or not supplied or not secrets.compare_digest(
        expected.encode("utf-8"),
        supplied.encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="ingest token 无效。")
    rows = [
        item.model_dump(mode="python", exclude_unset=True)
        for item in payload.orders
    ]
    created, updated = logistics.upsert_orders(db, rows)
    db.commit()
    return OrdersIngestResponse(
        accepted=len(rows),
        created=created,
        updated=updated,
    )


@machine_router.post("/tracking/webhook")
async def tracking_webhook(
    request: Request,
    sign: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="webhook JSON 无效。") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="webhook JSON 无效。")

    if logistics.track17_sign_mode() == "sha256":
        try:
            key = logistics.track17_key(db)
        except RuntimeError as exc:
            raise HTTPException(status_code=401, detail="webhook 签名无法验证。") from exc
        if not logistics.verify_track17_signature(raw_body, sign, key):
            raise HTTPException(status_code=401, detail="webhook 签名无效。")

    updated = 0
    ignored = 0
    for record in logistics.tracking_records_from_webhook(payload):
        number = str(record.get("number") or "").strip()
        if not number:
            ignored += 1
            continue
        orders = list(
            db.scalars(
                select(WOrder)
                .where(WOrder.tracking_number == number)
                .with_for_update()
            ).all()
        )
        if not orders:
            ignored += 1
            continue
        for order in orders:
            if logistics.apply_tracking_record(order, record, deduplicate=True):
                updated += 1
            else:
                ignored += 1
    db.commit()
    return {"updated": updated, "ignored": ignored}
