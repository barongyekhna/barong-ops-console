from __future__ import annotations

from fastapi import Body, APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...core.roles import is_owner_role, is_super_admin_role
from ...db.session import MAX_OVERFLOW, POOL_SIZE, STATEMENT_TIMEOUT_MS
from ...db.session import get_db
from ...models.org_membership import OrgMembershipRecord
from ...models.organization import OrganizationRecord
from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from ...services.rw_keepa_ingestion import keepa_ingestion_runtime_status
from ..deps import get_current_user
from r_system_v2.rw.category.category_tree import (
    apply_selected_categories,
    load_category_tree,
    select_category_in_payload,
    selected_category_ids,
)
from r_system_v2.rw.scheduler.category_rate_limiter import CategoryRateLimiter
from r_system_v2.rw.skill_metadata import load_deepseek_skill_metadata
from r_system_v2.rw.storage.pipeline_events import runtime_overview
from r_system_v2.rw.storage.runtime_settings import (
    load_runtime_settings,
    save_runtime_settings,
)


router = APIRouter(prefix="/rw", tags=["r-warehouse"])

R_SERIES_TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"

RULES = [
    {
        "id": "price_band_filter",
        "label": "价格带过滤",
        "enabled": True,
        "result": "已启用",
        "threshold": "售价 25-70 美元",
    },
    {
        "id": "margin_check",
        "label": "净利率检查",
        "enabled": True,
        "result": "已启用",
        "threshold": "预估净利率不低于 15%",
    },
    {
        "id": "competition_filter",
        "label": "卖家数量过滤",
        "enabled": True,
        "result": "已启用",
        "threshold": "卖家数不超过 15",
    },
    {
        "id": "brand_dominance_filter",
        "label": "品牌垄断过滤",
        "enabled": True,
        "result": "已启用",
        "threshold": "单品牌占比不超过 50%",
    },
    {
        "id": "price_trend_filter",
        "label": "价格趋势过滤",
        "enabled": True,
        "result": "已启用",
        "threshold": "价格趋势不得持续下行",
    },
    {
        "id": "review_wall_filter",
        "label": "评论壁垒过滤",
        "enabled": True,
        "result": "已启用",
        "threshold": "可取数时前三评论数不超过 500",
    },
    {
        "id": "redline_filter",
        "label": "红线类目过滤",
        "enabled": True,
        "result": "已启用",
        "threshold": "锂电/液体/强认证/IP/易碎重货直接剔除",
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
    settings = load_runtime_settings(db)
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
        run_time_range = "暂无已完成批次"
    return {
        "mode": "batch_processor_only",
        "controls_execution": False,
        "run_time_range": run_time_range,
        "total_processed": total_processed,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "deleted_count": 0,
        "interval_seconds": settings.deepseek_interval_seconds,
        "batch_size": settings.deepseek_batch_size,
        "max_runtime_seconds": settings.deepseek_max_runtime_seconds,
        "stopped_by_deadline": False,
    }


def _decision_from_state(state: str, features: object) -> str:
    if isinstance(features, dict) and isinstance(features.get("score_action"), str):
        return str(features["score_action"])
    if state == "ai1_passed":
        return "pass"
    if state in {"ai1_rejected", "rejected"}:
        return "reject"
    return "pending_review"


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
    settings = load_runtime_settings(db)
    category_tree = apply_selected_categories(
        load_category_tree(),
        settings.selected_categories,
    )
    selected_categories = selected_category_ids(category_tree)
    runtime = runtime_overview(db, event_limit=10)
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
            "async_fetch": True,
            "result_buffer": "in_memory",
            "batch_write": True,
        },
        "db_write_path": {
            "mode": ingestion_status.get("db_write_mode", "buffered_batch"),
            "batch_size_range": [100, 500],
            "flush_interval_seconds_range": [5, 10],
            "single_transaction_per_batch": True,
            "per_request_sql_update": False,
            "api_key_usage_mode": ingestion_status.get(
                "api_key_usage_mode",
                "in_memory_aggregate_60s",
            ),
            "connection_pool": {
                "enabled": True,
                "pool_size": POOL_SIZE,
                "max_overflow": MAX_OVERFLOW,
                "statement_timeout_ms": STATEMENT_TIMEOUT_MS,
            },
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
        "runtime": runtime,
        "category_tree": {
            "selected_count": len(selected_categories),
            "selected_categories": selected_categories,
        },
        "endpoints": [
            "/api/rw/products",
            "/api/rw/status",
            "/api/rw/rules",
            "/api/rw/ingestion/status",
            "/api/rw/pipeline",
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
                SELECT asin, marketplace, source_query, title, image_url, brand,
                       category, price, bsr, reviews, seller_count, landed_cost,
                       est_net_margin, brand_share, price_trend, rating, state,
                       rule_reject_reason, category_id, category_path, skill_score,
                       features, last_keepa_pull, updated_at
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
                "marketplace": row.marketplace,
                "source_query": row.source_query,
                "title": row.title,
                "image_url": row.image_url,
                "brand": row.brand,
                "category": row.category,
                "price": float(row.price) if row.price is not None else None,
                "bsr": row.bsr,
                "reviews": row.reviews,
                "seller_count": row.seller_count,
                "landed_cost": float(row.landed_cost) if row.landed_cost is not None else None,
                "brand_share": float(row.brand_share) if row.brand_share is not None else None,
                "price_trend": row.price_trend,
                "rating": float(row.rating) if row.rating is not None else None,
                "state": row.state,
                "rule_result": row.state,
                "rule_reject_reason": row.rule_reject_reason,
                "margin": float(row.est_net_margin) if row.est_net_margin is not None else None,
                "category_id": row.category_id,
                "category_path": row.category_path.split(">") if row.category_path else [],
                "skill_score": row.skill_score,
                "features": row.features if isinstance(row.features, dict) else {},
                "pipeline_decision": _decision_from_state(row.state, row.features),
                "last_keepa_pull": str(row.last_keepa_pull) if row.last_keepa_pull else None,
                "updated_at": str(row.updated_at) if row.updated_at else None,
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


@router.get("/pipeline")
def rw_pipeline(
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    return {
        "module": "R-W",
        "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
        "refresh_seconds": 5,
        "runtime": runtime_overview(db, event_limit=100),
        "mode": "production",
    }


@router.get("/settings")
def rw_settings(
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    settings = load_runtime_settings(db)
    return {
        "module": "R-W",
        "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
        "settings": settings.to_dict(),
        "mode": "production",
    }


@router.post("/settings")
def rw_update_settings(
    payload: dict[str, object] = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    try:
        settings = save_runtime_settings(db, payload)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="rw_runtime_settings_unavailable",
        ) from exc
    return {
        "module": "R-W",
        "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
        "settings": settings.to_dict(),
        "mode": "production",
    }


@router.get("/category-tree")
def rw_category_tree(
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    settings = load_runtime_settings(db)
    payload = apply_selected_categories(
        load_category_tree(),
        settings.selected_categories,
    )
    payload["selected_categories"] = selected_category_ids(payload)
    return payload


@router.post("/category-tree/select")
def rw_category_select(
    payload: dict[str, object] = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    category_id = str(payload.get("category_id", "")).strip()
    if not category_id:
        raise HTTPException(status_code=422, detail="category_id required")
    selected = bool(payload.get("selected", True))
    settings = load_runtime_settings(db)
    current_tree = apply_selected_categories(
        load_category_tree(),
        settings.selected_categories,
    )
    result = select_category_in_payload(current_tree, category_id, selected)
    selected_categories = selected_category_ids(result)
    try:
        save_runtime_settings(db, {"selected_categories": selected_categories})
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="rw_category_settings_unavailable",
        ) from exc
    result["selected_categories"] = selected_categories
    return result


@router.get("/category-rate-plan")
def rw_category_rate_plan(
    window_minutes: int = Query(default=10, ge=1, le=1440),
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    settings = load_runtime_settings(db)
    payload = apply_selected_categories(
        load_category_tree(),
        settings.selected_categories,
    )
    categories = selected_category_ids(payload)
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
