from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...db.session import get_db, get_read_db
from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from .rw import _target_org_for_user, require_r_series_org
from r_system_v2.ra.framework import load_ra_framework_overview
from r_system_v2.ra.auto_profit import run_auto_profit_analysis
from r_system_v2.ra.job_queue import (
    RAJobError,
    cancel_auto_profit_job,
    create_auto_profit_job,
    get_auto_profit_job,
    get_latest_auto_profit_job,
)
from r_system_v2.ra.profit_engine import decimal_value
from r_system_v2.ra.profit_service import (
    RAProfitError,
    calculate_manual_profit,
    list_profit_snapshots,
    profit_formula_config,
    run_profit_for_existing_offers,
)
from r_system_v2.ra.supplier_discovery import (
    RASupplierDiscoveryError,
    discover_1688_supplier_offers,
)


router = APIRouter(prefix="/r/analysis", tags=["r-analysis"])


class RAProfitManualRequest(BaseModel):
    asin: str = Field(min_length=10, max_length=20)
    unit_price_cny: float = Field(gt=0)
    domestic_shipping_cny: float | None = Field(default=None, ge=0)
    supplier_name: str | None = Field(default=None, max_length=200)
    supplier_url: str | None = Field(default=None, max_length=1000)
    moq: int | None = Field(default=None, ge=1)
    exchange_rate_usd_cny: float | None = Field(default=None, gt=0)
    min_gross_margin: float | None = Field(default=None, ge=0)


class RAProfitRunRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    asin: str | None = Field(default=None, min_length=10, max_length=20)
    exchange_rate_usd_cny: float | None = Field(default=None, gt=0)
    min_gross_margin: float | None = Field(default=None, ge=0)


class RASupplierSearchRequest(BaseModel):
    asin: str = Field(min_length=10, max_length=20)
    result_limit: int = Field(default=5, ge=3, le=5)
    auto_calculate: bool = True
    exchange_rate_usd_cny: float | None = Field(default=None, gt=0)
    min_gross_margin: float | None = Field(default=None, ge=0)


class RAAutoProfitRequest(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    asin_limit: int = Field(default=1, ge=1, le=20)
    supplier_limit: int = Field(default=3, ge=3, le=5)
    min_gross_margin: float | None = Field(default=None, ge=0)


class RAAutoProfitJobRequest(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    asin_limit: int = Field(default=20, ge=1, le=20)
    supplier_limit: int = Field(default=3, ge=3, le=5)
    min_gross_margin: float | None = Field(default=None, ge=0)
    run_ai_chain: bool = True
    run_ai_mock: bool | None = None
    selection_channel: str = Field(default="amazon", max_length=32)


@router.get("/status")
def ra_status(
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    return _framework_payload(db, user)


@router.get("/framework")
def ra_framework(
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    return _framework_payload(db, user)


@router.get("/overview")
def ra_overview(
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        framework = load_ra_framework_overview(db, org_id=target_org.org_id)
        latest = get_latest_auto_profit_job(db, org_id=target_org.org_id)
    return {"framework": framework, "latest_job": latest}


@router.get("/profit/config")
def ra_profit_config(
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    return profit_formula_config()


@router.get("/profit")
def ra_profit_list(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    return ra_profit_snapshots(limit=limit, db=db, user=user)


@router.get("/profit/snapshots")
def ra_profit_snapshots(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        return list_profit_snapshots(
            db,
            org_id=target_org.org_id,
            limit=limit,
        )


@router.post("/profit/manual")
def ra_profit_manual(
    payload: RAProfitManualRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    try:
        with without_org_data_isolation():
            return calculate_manual_profit(
                db,
                org_id=target_org.org_id,
                asin=payload.asin.strip().upper(),
                unit_price_cny=_required_decimal(payload.unit_price_cny),
                domestic_shipping_cny=decimal_value(payload.domestic_shipping_cny),
                supplier_name=_optional_text(payload.supplier_name),
                supplier_url=_optional_text(payload.supplier_url),
                moq=payload.moq,
                exchange_rate_usd_cny=decimal_value(payload.exchange_rate_usd_cny),
                min_gross_margin=decimal_value(payload.min_gross_margin),
            )
    except RAProfitError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/profit/run")
def ra_profit_run(
    payload: RAProfitRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        return run_profit_for_existing_offers(
            db,
            org_id=target_org.org_id,
            limit=payload.limit,
            asin=payload.asin.strip().upper() if payload.asin else None,
            exchange_rate_usd_cny=decimal_value(payload.exchange_rate_usd_cny),
            min_gross_margin=decimal_value(payload.min_gross_margin),
        )


@router.post("/profit/auto-run")
def ra_profit_auto_run(
    payload: RAAutoProfitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    try:
        with without_org_data_isolation():
            return run_auto_profit_analysis(
                db,
                org_id=target_org.org_id,
                query=payload.query,
                asin_limit=payload.asin_limit,
                supplier_limit=payload.supplier_limit,
                min_gross_margin=decimal_value(payload.min_gross_margin),
            )
    except (RAProfitError, RASupplierDiscoveryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/profit/jobs")
def ra_profit_job_create(
    payload: RAAutoProfitJobRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    try:
        with without_org_data_isolation():
            return create_auto_profit_job(
                db,
                org_id=target_org.org_id,
                query=payload.query,
                asin_limit=payload.asin_limit,
                supplier_limit=payload.supplier_limit,
                min_gross_margin=decimal_value(payload.min_gross_margin),
                run_ai_mock=payload.run_ai_chain if payload.run_ai_mock is None else payload.run_ai_mock,
                selection_channel=payload.selection_channel,
                triggered_by=str(user.id),
            )
    except RAJobError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/runs")
def ra_run_create(
    payload: RAAutoProfitJobRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    return ra_profit_job_create(payload=payload, db=db, user=user)


@router.get("/profit/jobs/latest")
def ra_profit_job_latest(
    item_page: int = Query(default=1, ge=1),
    item_page_size: int = Query(default=50, ge=1, le=50),
    item_search: str | None = Query(default=None, max_length=120),
    item_category: str | None = Query(default=None, max_length=120),
    item_verdict: str | None = Query(default=None, max_length=24),
    item_sort: str | None = Query(default=None, max_length=32),
    item_sort_direction: str | None = Query(default=None, max_length=8),
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        payload = get_latest_auto_profit_job(
            db,
            org_id=target_org.org_id,
            item_page=item_page,
            item_page_size=item_page_size,
            item_search=item_search,
            item_category=item_category,
            item_verdict=item_verdict,
            item_sort=item_sort,
            item_sort_direction=item_sort_direction,
        )
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="暂无 R-A 自动利润任务。",
        )
    return payload


@router.get("/runs/latest")
def ra_run_latest(
    item_page: int = Query(default=1, ge=1),
    item_page_size: int = Query(default=50, ge=1, le=50),
    item_search: str | None = Query(default=None, max_length=120),
    item_category: str | None = Query(default=None, max_length=120),
    item_verdict: str | None = Query(default=None, max_length=24),
    item_sort: str | None = Query(default=None, max_length=32),
    item_sort_direction: str | None = Query(default=None, max_length=8),
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    return ra_profit_job_latest(
        item_page=item_page,
        item_page_size=item_page_size,
        item_search=item_search,
        item_category=item_category,
        item_verdict=item_verdict,
        item_sort=item_sort,
        item_sort_direction=item_sort_direction,
        db=db,
        user=user,
    )


@router.get("/profit/jobs/{run_id}")
def ra_profit_job_get(
    run_id: str,
    item_page: int = Query(default=1, ge=1),
    item_page_size: int = Query(default=50, ge=1, le=50),
    item_search: str | None = Query(default=None, max_length=120),
    item_category: str | None = Query(default=None, max_length=120),
    item_verdict: str | None = Query(default=None, max_length=24),
    item_sort: str | None = Query(default=None, max_length=32),
    item_sort_direction: str | None = Query(default=None, max_length=8),
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    try:
        with without_org_data_isolation():
            return get_auto_profit_job(
                db,
                org_id=target_org.org_id,
                run_id=run_id,
                item_page=item_page,
                item_page_size=item_page_size,
                item_search=item_search,
                item_category=item_category,
                item_verdict=item_verdict,
                item_sort=item_sort,
                item_sort_direction=item_sort_direction,
            )
    except RAJobError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/runs/{run_id}")
def ra_run_get(
    run_id: str,
    item_page: int = Query(default=1, ge=1),
    item_page_size: int = Query(default=50, ge=1, le=50),
    item_search: str | None = Query(default=None, max_length=120),
    item_category: str | None = Query(default=None, max_length=120),
    item_verdict: str | None = Query(default=None, max_length=24),
    item_sort: str | None = Query(default=None, max_length=32),
    item_sort_direction: str | None = Query(default=None, max_length=8),
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    return ra_profit_job_get(
        run_id=run_id,
        item_page=item_page,
        item_page_size=item_page_size,
        item_search=item_search,
        item_category=item_category,
        item_verdict=item_verdict,
        item_sort=item_sort,
        item_sort_direction=item_sort_direction,
        db=db,
        user=user,
    )


@router.post("/runs/{run_id}/cancel")
def ra_run_cancel(
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    try:
        with without_org_data_isolation():
            return cancel_auto_profit_job(db, org_id=target_org.org_id, run_id=run_id)
    except RAJobError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/candidates")
def ra_candidates(
    run_id: str | None = Query(default=None, max_length=80),
    item_page: int = Query(default=1, ge=1),
    item_page_size: int = Query(default=50, ge=1, le=50),
    item_search: str | None = Query(default=None, max_length=120),
    item_category: str | None = Query(default=None, max_length=120),
    item_verdict: str | None = Query(default=None, max_length=24),
    item_sort: str | None = Query(default=None, max_length=32),
    item_sort_direction: str | None = Query(default=None, max_length=8),
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        payload = (
            get_auto_profit_job(
                db,
                org_id=target_org.org_id,
                run_id=run_id,
                item_page=item_page,
                item_page_size=item_page_size,
                item_search=item_search,
                item_category=item_category,
                item_verdict=item_verdict,
                item_sort=item_sort,
                item_sort_direction=item_sort_direction,
            )
            if run_id
            else get_latest_auto_profit_job(
                db,
                org_id=target_org.org_id,
                item_page=item_page,
                item_page_size=item_page_size,
                item_search=item_search,
                item_category=item_category,
                item_verdict=item_verdict,
                item_sort=item_sort,
                item_sort_direction=item_sort_direction,
            )
        )
    if payload is None:
        return {"items": [], "items_page": None, "counts": {}, "run_id": run_id}
    return {
        "run_id": payload.get("run_id"),
        "status": payload.get("status"),
        "items": payload.get("items") or [],
        "items_page": payload.get("items_page"),
        "counts": payload.get("counts") or {},
    }


@router.post("/candidates/import-from-rw")
def ra_candidates_import_from_rw(
    payload: RAAutoProfitJobRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    return ra_profit_job_create(payload=payload, db=db, user=user)


@router.post("/supplier-search")
def ra_supplier_search(
    payload: RASupplierSearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    try:
        with without_org_data_isolation():
            return discover_1688_supplier_offers(
                db,
                org_id=target_org.org_id,
                asin=payload.asin.strip().upper(),
                result_limit=payload.result_limit,
                auto_calculate=payload.auto_calculate,
                exchange_rate_usd_cny=decimal_value(payload.exchange_rate_usd_cny),
                min_gross_margin=decimal_value(payload.min_gross_margin),
            )
    except (RAProfitError, RASupplierDiscoveryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/suppliers")
def ra_suppliers(
    run_id: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        return _list_ra_suppliers(db, org_id=target_org.org_id, run_id=run_id, limit=limit)


@router.get("/reports")
def ra_reports(
    run_id: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        return _list_ra_reports(db, org_id=target_org.org_id, run_id=run_id, limit=limit)


@router.post("/reports/{report_id}/approve")
def ra_report_approve(
    report_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    return _update_report_status(db, user=user, report_id=report_id, report_status="approved")


@router.post("/reports/{report_id}/reject")
def ra_report_reject(
    report_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    return _update_report_status(db, user=user, report_id=report_id, report_status="rejected")


def _framework_payload(db: Session, user: User) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        return load_ra_framework_overview(db, org_id=target_org.org_id)


def _list_ra_suppliers(
    db: Session,
    *,
    org_id: str,
    run_id: str | None,
    limit: int,
) -> dict[str, object]:
    filters = ["o.org_id = :org_id"]
    params: dict[str, object] = {"org_id": org_id, "limit": limit}
    if run_id:
        filters.append("c.run_id = :run_id")
        params["run_id"] = run_id
    where_sql = " AND ".join(f"({item})" for item in filters)
    rows = db.execute(
        text(
            f"""
            SELECT o.id AS offer_id, o.candidate_id, c.run_id, o.asin,
                   o.supplier_name, o.supplier_url, o.unit_price_cny,
                   o.moq, o.rating, o.match_score, o.offer_status,
                   o.payload, o.created_at, o.updated_at
            FROM ra_supplier_offers o
            LEFT JOIN ra_candidates c ON c.id = o.candidate_id
            WHERE {where_sql}
            ORDER BY o.updated_at DESC NULLS LAST, o.created_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings()
    items = []
    for row in rows:
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        items.append(
            {
                "offer_id": row["offer_id"],
                "candidate_id": row["candidate_id"],
                "run_id": row["run_id"],
                "asin": row["asin"],
                "supplier_name": row["supplier_name"],
                "supplier_url": row["supplier_url"],
                "supplier_platform": payload.get("platform"),
                "supplier_platform_label": payload.get("platform_label"),
                "unit_price_cny": float(row["unit_price_cny"]) if row["unit_price_cny"] is not None else None,
                "moq": row["moq"],
                "rating": float(row["rating"]) if row["rating"] is not None else None,
                "match_score": row["match_score"],
                "offer_status": row["offer_status"],
                "one_piece_hint": bool(payload.get("one_piece_hint")),
                "created_at": str(row["created_at"]) if row["created_at"] else None,
                "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
            }
        )
    return {"items": items, "count": len(items), "run_id": run_id}


def _list_ra_reports(
    db: Session,
    *,
    org_id: str,
    run_id: str | None,
    limit: int,
) -> dict[str, object]:
    filters = ["org_id = :org_id"]
    params: dict[str, object] = {"org_id": org_id, "limit": limit}
    if run_id:
        filters.append("run_id = :run_id")
        params["run_id"] = run_id
    where_sql = " AND ".join(f"({item})" for item in filters)
    rows = db.execute(
        text(
            f"""
            SELECT report_id, run_id, candidate_id, asin, status,
                   title, summary, payload, created_at, updated_at
            FROM ra_reports
            WHERE {where_sql}
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings()
    items = []
    for row in rows:
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        final = payload.get("final") if isinstance(payload.get("final"), dict) else {}
        items.append(
            {
                "report_id": row["report_id"],
                "run_id": row["run_id"],
                "candidate_id": row["candidate_id"],
                "asin": row["asin"],
                "status": row["status"],
                "title": row["title"],
                "summary": row["summary"],
                "final_score": final.get("final_score"),
                "verdict": final.get("verdict"),
                "channel": final.get("channel"),
                "channel_routes": final.get("channel_routes"),
                "primary_channel": final.get("primary_channel"),
                "created_at": str(row["created_at"]) if row["created_at"] else None,
                "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
            }
        )
    return {"items": items, "count": len(items), "run_id": run_id}


def _update_report_status(
    db: Session,
    *,
    user: User,
    report_id: str,
    report_status: str,
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        row = db.execute(
            text(
                """
                UPDATE ra_reports
                SET status = :status, updated_at = CURRENT_TIMESTAMP
                WHERE report_id = :report_id AND org_id = :org_id
                RETURNING report_id, run_id, candidate_id, asin, status,
                          title, summary, updated_at
                """
            ),
            {
                "status": report_status,
                "report_id": report_id,
                "org_id": target_org.org_id,
            },
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="R-A 报告不存在。")
        return {
            "report_id": row["report_id"],
            "run_id": row["run_id"],
            "candidate_id": row["candidate_id"],
            "asin": row["asin"],
            "status": row["status"],
            "title": row["title"],
            "summary": row["summary"],
            "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
        }


def _required_target_org(db: Session, user: User):
    target_org = _target_org_for_user(db, user)
    if target_org is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="R-series modules are bound to the target organization only.",
        )
    return target_org


def _required_decimal(value: object):
    parsed = decimal_value(value)
    if parsed is None or parsed <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="成本必须大于 0。",
        )
    return parsed


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
