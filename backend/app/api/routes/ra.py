from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...db.session import get_db, get_read_db
from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from .rw import _target_org_for_user, require_r_series_org
from r_system_v2.ra.framework import load_ra_framework_overview
from r_system_v2.ra.auto_profit import run_auto_profit_analysis
from r_system_v2.ra.job_queue import (
    RAJobError,
    create_auto_profit_job,
    get_auto_profit_job,
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


@router.get("/profit/config")
def ra_profit_config(
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    del user
    return profit_formula_config()


@router.get("/profit/snapshots")
def ra_profit_snapshots(
    limit: int = 50,
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        return list_profit_snapshots(
            db,
            org_id=target_org.org_id,
            limit=max(1, min(limit, 200)),
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
                triggered_by=str(user.id),
            )
    except RAJobError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/profit/jobs/{run_id}")
def ra_profit_job_get(
    run_id: str,
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
            )
    except RAJobError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


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


def _framework_payload(db: Session, user: User) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        return load_ra_framework_overview(db, org_id=target_org.org_id)


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
