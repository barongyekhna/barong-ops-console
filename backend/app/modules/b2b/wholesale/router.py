"""FastAPI endpoints for the B2B wholesale catalogue."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ....api.deps import get_current_user
from ....core.roles import is_super_admin_role
from ....core.target_org_guard import (
    INTERNATIONAL_TRADE_ORG_NAME,
    enforce_caller_is_target_org,
)
from ....db.session import get_db
from ....models.user import User
from ....services.permission_service import (
    resolve_current_user_permission_info,
)
from ..linesheet.render_csv import render_csv
from ..linesheet.render_pdf import render_pdf
from ..widget import service as widget_service
from . import service
from .ingest_from_k import backfill_uploaded_products
from .schemas import (
    CATEGORY_PROSPECTING_MIN_READY_ITEMS,
    CategoryReadinessResponse,
    IngestResult,
    LineSheetExportRequest,
    PriceTier,
    WholesaleItemBatchPatch,
    WholesaleItemListResponse,
    WholesaleItemPatch,
    WholesaleItemRead,
)

PERMISSION_READ = "b2b.wholesale.read"
PERMISSION_MANAGE = "b2b.wholesale.manage"
PERMISSION_EXPORT = "b2b.wholesale.export"


def _public_base() -> str:
    import os

    return os.getenv(
        "PUBLIC_BASE_URL", "https://ops.barongyekhna.com"
    ).rstrip("/")

router = APIRouter(prefix="/b2b", tags=["b2b-wholesale"])


def _require_b2b_permission(permission_key: str):
    """Owner and super-admin bypass; manage/export implicitly grant read."""

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(
            db,
            user,
            request=request,
        )
        # H1: B2B prospects/wholesale/templates have no org_id column; enforce
        # cross-org isolation at the gate (owner exempt). Blocks another org's
        # super_admin from reading this org's customer leads (business secret).
        enforce_caller_is_target_org(
            request,
            db,
            user,
            target_name=INTERNATIONAL_TRADE_ORG_NAME,
            detail="You do not have access to wholesale tools.",
        )
        allowed_keys = {permission_key}
        if permission_key == PERMISSION_READ:
            allowed_keys.update({PERMISSION_MANAGE, PERMISSION_EXPORT})
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


def _to_read(item) -> WholesaleItemRead:
    tiers = [
        PriceTier(min_qty=int(raw["min_qty"]), unit_price=raw["unit_price"])
        for raw in (item.price_tiers_json or [])
        if isinstance(raw, dict) and raw.get("min_qty") is not None
    ]
    return WholesaleItemRead(
        id=item.id,
        k_product_id=item.k_product_id,
        woo_product_id=item.woo_product_id,
        sku=item.sku,
        product_name=item.product_name,
        category_path=list(item.category_path or []),
        image_url=item.image_url,
        msrp=item.msrp,
        wholesale_price=item.wholesale_price,
        price_tiers=tiers,
        case_pack=item.case_pack,
        moq_units=item.moq_units,
        lead_time_days=item.lead_time_days,
        variant_note=item.variant_note,
        notes=item.notes,
        status=item.status,
        needs_review=item.needs_review,
        review_reason=item.review_reason,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/wholesale/items", response_model=WholesaleItemListResponse)
def list_wholesale_items(
    status_filter: str | None = Query(default=None, alias="status"),
    needs_review: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> WholesaleItemListResponse:
    del user
    rows, counts = service.list_items(
        db,
        status=status_filter,
        needs_review=needs_review,
        search=search,
        limit=limit,
        offset=offset,
    )
    return WholesaleItemListResponse(
        items=[_to_read(row) for row in rows],
        count=len(rows),
        **counts,
    )


@router.patch(
    "/wholesale/items/{item_id}",
    response_model=WholesaleItemRead,
)
def patch_wholesale_item(
    item_id: UUID,
    payload: WholesaleItemPatch,
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> WholesaleItemRead:
    del user
    try:
        item = service.update_item(db, item_id=item_id, patch=payload)
    except service.WholesaleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.WholesaleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # 批发信息一变就把产品页小窗推一次(填全了出现，清空了消失)。
    # 包在 safely 里：小窗推送出问题绝不能把保存带崩。
    widget_service.dispatch_safely(
        db, item_ids=[item.id], public_base=_public_base()
    )
    return _to_read(item)


@router.patch("/wholesale/items", response_model=WholesaleItemListResponse)
def batch_patch_wholesale_items(
    payload: WholesaleItemBatchPatch,
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> WholesaleItemListResponse:
    del user
    try:
        rows = service.batch_update(db, payload=payload)
    except service.WholesaleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.WholesaleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    widget_service.dispatch_safely(
        db, item_ids=[row.id for row in rows], public_base=_public_base()
    )
    return WholesaleItemListResponse(
        items=[_to_read(row) for row in rows],
        count=len(rows),
    )


@router.get(
    "/wholesale/category-readiness",
    response_model=CategoryReadinessResponse,
)
def get_category_readiness(
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> CategoryReadinessResponse:
    del user
    return CategoryReadinessResponse(
        categories=service.category_readiness(db),
        min_ready_items=CATEGORY_PROSPECTING_MIN_READY_ITEMS,
    )


@router.post("/wholesale/line-sheet")
def export_line_sheet(
    payload: LineSheetExportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_EXPORT)),
) -> Response:
    del user
    with service.make_image_dir() as image_dir:
        try:
            request_model = service.build_line_sheet_request(
                db,
                payload=payload,
                image_dir=Path(image_dir),
            )
        except service.WholesaleValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if payload.fmt == "csv":
            body = render_csv(request_model)
            media_type = "text/csv; charset=utf-8"
            extension = "csv"
        else:
            body = render_pdf(request_model)
            media_type = "application/pdf"
            extension = "pdf"

    slug = "-".join(payload.category_prefix or ["full-catalog"])
    safe_slug = (
        "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in slug.lower())
        .strip("-")
        or "catalogue"
    )
    filename = f"barong-yekhna-{safe_slug}.{extension}"
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/wholesale/ingest", response_model=IngestResult)
def ingest_wholesale_items(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> IngestResult:
    """手动补灌。正常路径是 P 上架成功后自动调 service.ingest_products。"""
    del user
    products = payload.get("products")
    if not isinstance(products, list):
        raise HTTPException(
            status_code=422,
            detail="Body must contain a 'products' array.",
        )
    return service.ingest_products(db, products=products)


@router.post("/wholesale/backfill", response_model=IngestResult)
def backfill_wholesale_items(
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> IngestResult:
    """把钩子上线之前就已上架的产品补灌进批发目录(幂等)。"""
    del user
    return backfill_uploaded_products(db)


@router.post("/widget-push")
def push_widget(
    db: Session = Depends(get_db),
    user: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> dict:
    """把全部产品的小窗重推一遍。政策文案改了之后用这个。"""
    try:
        job = widget_service.dispatch(
            db, user=user, public_base=_public_base()
        )
    except widget_service.WidgetError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "job_id": job.job_id,
        "status": job.status,
        "targets": len(job.targets_json or []),
    }


@router.get("/widget-jobs")
def list_widget_jobs(
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> list[dict]:
    from ..widget.jobs import jobs_recent

    return [
        {
            "job_id": row.job_id,
            "status": row.status,
            "targets": len(row.targets_json or []),
            "error": row.error,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }
        for row in jobs_recent(db, limit=10)
    ]


@router.post("/website/publish")
def publish_wholesale_site(
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> dict:
    """生成 /wholesale/ 主页和全部店型子页。幂等，重复跑不会多建页面。"""
    from ..website import publisher

    try:
        return publisher.publish(db)
    except publisher.PublishError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/website/status")
def wholesale_site_status(
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> dict:
    from ..website import publisher

    return publisher.status(db)
