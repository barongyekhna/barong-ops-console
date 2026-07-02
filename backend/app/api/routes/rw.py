from __future__ import annotations

from fastapi import Body, APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...core.roles import is_owner_role, is_super_admin_role
from ...db.session import get_db
from ...models.org_membership import OrgMembershipRecord
from ...models.organization import OrganizationRecord
from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from ...services.rw_keepa_ingestion import keepa_ingestion_runtime_status
from ..deps import get_current_user
from r_system_v2.rw.category.category_tree import (
    load_category_tree,
    select_category,
    selected_category_ids,
)
from r_system_v2.rw.scheduler.category_rate_limiter import CategoryRateLimiter
from r_system_v2.rw.skill_metadata import load_deepseek_skill_metadata


router = APIRouter(prefix="/rw", tags=["r-warehouse"])

R_SERIES_TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"

RULES = [
    {
        "id": "price_band_filter",
        "label": "price band filter",
        "enabled": True,
        "result": "passed",
        "threshold": "25 <= price <= 70",
    },
    {
        "id": "margin_check",
        "label": "margin check",
        "enabled": True,
        "result": "passed",
        "threshold": "est_net_margin >= 0.15",
    },
    {
        "id": "competition_filter",
        "label": "competition filter",
        "enabled": True,
        "result": "passed",
        "threshold": "seller_count <= 15",
    },
    {
        "id": "brand_dominance_filter",
        "label": "brand dominance filter",
        "enabled": True,
        "result": "passed",
        "threshold": "brand_share <= 0.50",
    },
    {
        "id": "price_trend_filter",
        "label": "price trend filter",
        "enabled": True,
        "result": "passed",
        "threshold": "price_trend not declining",
    },
]


def _user_has_rw_role_access(user: User) -> bool:
    return is_owner_role(user.role) or is_super_admin_role(user.role)


def _user_has_target_org_access(db: Session, user: User) -> bool:
    return _target_org_for_user(db, user) is not None


def _target_org_for_user(db: Session, user: User) -> OrganizationRecord | None:
    if is_owner_role(user.role):
        with without_org_data_isolation():
            return db.scalar(
                select(OrganizationRecord)
                .where(
                    OrganizationRecord.org_name == R_SERIES_TARGET_ORGANIZATION_NAME,
                    OrganizationRecord.status != "deleted",
                )
                .order_by(OrganizationRecord.org_id)
                .limit(1)
            )

    org_ids: set[str] = set()
    if user.organization_id:
        org_ids.add(user.organization_id)

    with without_org_data_isolation():
        membership_org_ids = db.scalars(
            select(OrgMembershipRecord.org_id).where(
                OrgMembershipRecord.user_id == str(user.id),
                OrgMembershipRecord.status == "active",
            )
        )
        org_ids.update(membership_org_ids)

        if not org_ids:
            return None

        return db.scalar(
            select(OrganizationRecord)
            .where(
                OrganizationRecord.org_id.in_(org_ids),
                OrganizationRecord.org_name == R_SERIES_TARGET_ORGANIZATION_NAME,
                OrganizationRecord.status != "deleted",
            )
            .order_by(OrganizationRecord.org_id)
            .limit(1)
        )


def _deepseek_batch_status(db: Session) -> dict[str, object]:
    try:
        row = db.execute(
            text(
                """
                SELECT
                  COUNT(*) AS total_processed,
                  COALESCE(SUM(CASE WHEN score >= 60 OR verdict = 'hold' THEN 1 ELSE 0 END), 0) AS pass_count,
                  COALESCE(SUM(CASE WHEN score < 60 AND verdict <> 'hold' THEN 1 ELSE 0 END), 0) AS fail_count,
                  MIN(created_at) AS first_run_at,
                  MAX(created_at) AS last_run_at
                FROM ai_evaluations
                WHERE layer = 'deepseek'
                """
            )
        ).mappings().first()
    except SQLAlchemyError:
        row = None
    total_processed = int(row["total_processed"] or 0) if row else 0
    pass_count = int(row["pass_count"] or 0) if row else 0
    fail_count = int(row["fail_count"] or 0) if row else 0
    first_run_at = str(row["first_run_at"]) if row and row["first_run_at"] else None
    last_run_at = str(row["last_run_at"]) if row and row["last_run_at"] else None
    if first_run_at and last_run_at:
        run_time_range = f"{first_run_at} - {last_run_at}"
    else:
        run_time_range = "no completed batch yet"
    return {
        "mode": "batch_processor_only",
        "controls_execution": False,
        "run_time_range": run_time_range,
        "total_processed": total_processed,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "deleted_count": 0,
    }


def require_r_series_org(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    if not _user_has_rw_role_access(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="R-W requires owner or super_admin access.",
        )
    if not _user_has_target_org_access(db, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="R-series modules are bound to the target organization only.",
        )
    return user


@router.get("/status")
def rw_status(
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _target_org_for_user(db, user)
    if target_org is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="R-series modules are bound to the target organization only.",
        )
    with without_org_data_isolation():
        ingestion_status = keepa_ingestion_runtime_status(
            db,
            org_id=target_org.org_id,
        )
    keepa_bound = ingestion_status["keepa_key_bound"] is True
    category_tree = load_category_tree()
    selected_categories = selected_category_ids(category_tree)
    return {
        "module": "R-W",
        "active": True,
        "mode": "production" if keepa_bound else "production_blocked",
        "mock_mode_active": False,
        "waiting_for_keys": not keepa_bound,
        "real_keepa_api_used": keepa_bound,
        "use_real_keepa_api": True,
        "keepa_rate_limit": {
            "max_requests_per_min": 20,
            "no_burst_mode": True,
            "queue_based_ingestion": True,
            "refill_aware_scheduler": True,
        },
        "keepa_mode": {
            "continuous_ingestion": True,
            "worker_loop": "24/7",
            "only_rate_limit": "20/min",
        },
        "keepa_key_bound": keepa_bound,
        "ingestion_service_ready": ingestion_status["ingestion_service_ready"],
        "adapter": ingestion_status["adapter"],
        "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
        "pipeline": ingestion_status.get(
            "pipeline",
            "Keepa API -> ingestion service -> product DB",
        ),
        "skill": load_deepseek_skill_metadata(),
        "deepseek_batch": _deepseek_batch_status(db),
        "category_tree": {
            "selected_count": len(selected_categories),
            "selected_categories": selected_categories,
        },
        "endpoints": [
            "/api/rw/products",
            "/api/rw/status",
            "/api/rw/rules",
            "/api/rw/ingestion/status",
        ],
    }


@router.get("/ingestion/status")
def rw_ingestion_status(
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _target_org_for_user(db, user)
    if target_org is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="R-series modules are bound to the target organization only.",
        )
    with without_org_data_isolation():
        ingestion_status = keepa_ingestion_runtime_status(
            db,
            org_id=target_org.org_id,
        )
    return {
        "module": "R-W",
        "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
        **ingestion_status,
    }


@router.get("/products")
def rw_products(
    q: str | None = Query(default=None, max_length=120),
    category_id: str | None = Query(default=None, max_length=120),
    sort_by: str = Query(default="updated_at", pattern="^(updated_at|skill_score)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    storage_status = "ok"
    rows: list[dict[str, object]] = []
    order_sql = "ASC" if sort_order == "asc" else "DESC"
    order_column = "skill_score" if sort_by == "skill_score" else "updated_at"
    filters = []
    params: dict[str, object] = {}
    if q:
        filters.append("(LOWER(title) LIKE :q OR LOWER(asin) LIKE :q OR LOWER(category) LIKE :q)")
        params["q"] = f"%{q.strip().lower()}%"
    if category_id:
        filters.append("category_id = :category_id")
        params["category_id"] = category_id
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    try:
        result = db.execute(
            text(
                f"""
                SELECT asin, title, category, price, bsr, reviews, seller_count,
                       state, est_net_margin, category_id, category_path, skill_score
                FROM products_rw
                {where_sql}
                ORDER BY {order_column} {order_sql} NULLS LAST
                LIMIT 100
                """
            ),
            params,
        )
        rows = [
            {
                "asin": row.asin,
                "title": row.title,
                "category": row.category,
                "price": float(row.price) if row.price is not None else None,
                "bsr": row.bsr,
                "reviews": row.reviews,
                "seller_count": row.seller_count,
                "state": row.state,
                "rule_result": row.state,
                "margin": float(row.est_net_margin) if row.est_net_margin is not None else None,
                "category_id": row.category_id,
                "category_path": row.category_path.split(">") if row.category_path else [],
                "skill_score": row.skill_score,
                "source": "products_rw",
            }
            for row in result
        ]
    except SQLAlchemyError:
        storage_status = "products_rw_unavailable"
    return {
        "items": rows,
        "count": len(rows),
        "mode": "production",
        "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
        "storage_status": storage_status,
        "filters": {
            "q": q,
            "category_id": category_id,
            "sort_by": sort_by,
            "sort_order": sort_order,
        },
    }


@router.get("/rules")
def rw_rules(user: User = Depends(require_r_series_org)) -> dict[str, object]:
    del user
    return {
        "items": RULES,
        "count": len(RULES),
        "enabled": True,
        "mode": "production",
    }


@router.get("/category-tree")
def rw_category_tree(user: User = Depends(require_r_series_org)) -> dict[str, object]:
    del user
    payload = load_category_tree()
    payload["selected_categories"] = selected_category_ids(payload)
    return payload


@router.post("/category-tree/select")
def rw_category_select(
    payload: dict[str, object] = Body(...),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    category_id = str(payload.get("category_id", "")).strip()
    if not category_id:
        raise HTTPException(status_code=422, detail="category_id required")
    selected = bool(payload.get("selected", True))
    result = select_category(category_id, selected)
    result["selected_categories"] = selected_category_ids(result)
    return result


@router.get("/category-rate-plan")
def rw_category_rate_plan(
    window_minutes: int = Query(default=10, ge=1, le=1440),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    categories = selected_category_ids(load_category_tree())
    return CategoryRateLimiter().plan(categories, window_minutes).to_dict()


@router.delete("/products/{asin}")
def rw_delete_product(
    asin: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    clean_asin = asin.strip()
    if not clean_asin:
        raise HTTPException(status_code=422, detail="asin required")
    try:
        result = db.execute(
            text("DELETE FROM products_rw WHERE asin = :asin"),
            {"asin": clean_asin},
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="products_rw_unavailable",
        ) from exc
    return {
        "asin": clean_asin,
        "deleted": result.rowcount > 0,
        "delete_mode": "hard_delete",
        "cascade": "rule_results_and_ai_evaluations",
    }
