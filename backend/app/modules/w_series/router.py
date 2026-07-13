"""W-A shipping hub API.

All endpoints are human-operated control-plane actions.  The module only
assigns WooCommerce shipping-class slugs; it never creates orders or performs
fulfilment.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.roles import is_super_admin_role
from ...db.session import get_db
from ...models.user import User
from ...services.permission_service import resolve_current_user_permission_info
from ..k_series.product_knowledge.models import KProductKnowledgeProduct
from .shipping import engine, service
from .shipping.models import WShippingClass, WShippingRule

router = APIRouter(prefix="/w", tags=["w-site-ops"])

MODULE_KEY = "w.site_ops"
PERMISSION_READ = "w.site_ops.read"
PERMISSION_MANAGE = "w.site_ops.manage"


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
        origin=row.origin,
        notes=row.notes,
        active=row.active,
        sort_order=row.sort_order,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
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
    row = service.get_shipping_class(db, class_id)
    if row is None:
        raise HTTPException(status_code=404, detail="运费模板不存在。")
    service.update_shipping_class(row, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(row)
    return _class_item(row)


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
