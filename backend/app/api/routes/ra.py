from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...db.session import get_db, get_read_db
from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from .rw import _target_org_for_user, require_r_series_org
from r_system_v2.ra.events import list_run_events
from r_system_v2.ra.framework import load_ra_framework_overview
from r_system_v2.ra.prescreen import prescreen_daily_stats
from r_system_v2.ra.quota_ledger import usage_today
from r_system_v2.ra.auto_profit import run_auto_profit_analysis
from r_system_v2.ra.job_queue import (
    RAJobError,
    cancel_auto_profit_job,
    create_auto_profit_job,
    get_auto_profit_job,
    get_auto_profit_job_status,
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

# 分组池短缓存:查询要解压上百份大 payload(~6s),看板刷新频繁但数据分钟级新鲜
# 足够。写操作(approve/reject/opus复核)会主动清空,避免滑掉的卡片回魂。
# 文件级实现:gunicorn 多 worker 共享同一容器文件系统,进程内 dict 会各自为政。
_GROUPS_CACHE_TTL_SECONDS = 60.0
_GROUPS_CACHE_DIR = "/tmp/ra_groups_cache"


def _groups_cache_path(key: str) -> str:
    import hashlib
    import os

    os.makedirs(_GROUPS_CACHE_DIR, exist_ok=True)
    return os.path.join(
        _GROUPS_CACHE_DIR, hashlib.sha256(key.encode()).hexdigest()[:24] + ".json"
    )


def _groups_cache_get(key: str) -> dict[str, object] | None:
    import json as _json
    import os
    import time as _time

    path = _groups_cache_path(key)
    try:
        if _time.time() - os.path.getmtime(path) > _GROUPS_CACHE_TTL_SECONDS:
            return None
        with open(path, encoding="utf-8") as fh:
            return _json.load(fh)
    except (OSError, ValueError):
        return None


def _groups_cache_put(key: str, value: dict[str, object]) -> None:
    import json as _json
    import os

    path = _groups_cache_path(key)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            _json.dump(value, fh, ensure_ascii=False, default=str)
        os.replace(tmp, path)
    except OSError:
        pass


def _groups_cache_bust() -> None:
    import glob
    import os

    for path in glob.glob(os.path.join(_GROUPS_CACHE_DIR, "*.json")):
        try:
            os.remove(path)
        except OSError:
            pass



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
            # 定向探测优先：给运行中的自动巡库发让位信号，worker 收到后
            # 保存进度回到队列，先跑手动任务，跑完自动续巡库。
            db.execute(
                text(
                    """
                    UPDATE ra_selection_runs
                    SET counts = counts || '{"yield_requested": true}'::jsonb,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE org_id = :org_id
                      AND channel = 'profit_auto'
                      AND status = 'running'
                      AND COALESCE(filters->>'auto_cruise', 'false') = 'true'
                    """
                ),
                {"org_id": target_org.org_id},
            )
            db.commit()
            return create_auto_profit_job(
                db,
                org_id=target_org.org_id,
                query=payload.query,
                asin_limit=payload.asin_limit,
                supplier_limit=payload.supplier_limit,
                min_gross_margin=decimal_value(payload.min_gross_margin),
                run_ai_chain=payload.run_ai_chain,
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


@router.get("/runs/{run_id}/status")
def ra_run_status(
    run_id: str,
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        payload = get_auto_profit_job_status(
            db,
            org_id=target_org.org_id,
            run_id=None if run_id == "latest" else run_id,
        )
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="暂无 R-A 自动利润任务。",
        )
    return payload


@router.get("/runs/{run_id}/events")
def ra_run_events(
    run_id: str,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        return list_run_events(
            db,
            org_id=target_org.org_id,
            run_id=None if run_id == "latest" else run_id,
            after_seq=after,
            limit=limit,
        )


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


class CruiseToggleRequest(BaseModel):
    paused: bool


def _cruise_today_usage(db: Session, org_id: str) -> dict[str, object]:
    """今日 R-A 烧钱概况:AI 评估次数 + 各出网 provider 台账用量。"""
    from r_system_v2.ra.quota_ledger import provider_label

    with without_org_data_isolation():
        ai_evals = db.execute(
            text(
                "SELECT COUNT(*) FROM ra_ai_evaluations "
                "WHERE created_at::date = CURRENT_DATE"
            )
        ).scalar()
        providers = db.execute(
            text(
                "SELECT provider, used FROM ra_provider_quota_usage "
                "WHERE day = CURRENT_DATE AND used > 0 ORDER BY used DESC"
            )
        ).mappings().all()
    return {
        "ai_evaluations": int(ai_evals or 0),
        "providers": [
            {
                "provider": r["provider"],
                "label": provider_label(r["provider"]),
                "used": int(r["used"]),
            }
            for r in providers
        ],
    }


def _cruise_state(db: Session, org_id: str) -> dict[str, object]:
    from r_system_v2.ra.runtime_flags import FLAG_CRUISE_PAUSED, get_flag, is_cruise_paused

    with without_org_data_isolation():
        paused = is_cruise_paused(db)
        meta = db.execute(
            text(
                "SELECT updated_at, updated_by FROM ra_runtime_flags WHERE flag = :f"
            ),
            {"f": FLAG_CRUISE_PAUSED},
        ).mappings().first()
    return {
        "paused": paused,
        "updated_at": meta["updated_at"].isoformat() if meta and meta["updated_at"] else None,
        "updated_by": meta["updated_by"] if meta else None,
        "today": _cruise_today_usage(db, org_id),
    }


@router.get("/cruise")
def ra_cruise_status(
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    """自动巡航开关状态 + 今日烧钱概况。"""
    target_org = _required_target_org(db, user)
    return _cruise_state(db, target_org.org_id)


@router.post("/cruise/toggle")
def ra_cruise_toggle(
    payload: CruiseToggleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    """一键暂停/恢复自动巡航(界面开关)。暂停即停所有按次烧钱的自动流;
    手动选品不受影响;R-W(Keepa 月付)完全不碰。"""
    from r_system_v2.ra.runtime_flags import set_cruise_paused

    target_org = _required_target_org(db, user)
    actor = getattr(user, "username", None) or getattr(user, "email", None)
    with without_org_data_isolation():
        set_cruise_paused(db, payload.paused, actor=actor)
    db.commit()
    return _cruise_state(db, target_org.org_id)


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


@router.get("/quota")
def ra_quota(
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        return {
            "providers": usage_today(db),
            "prescreen": prescreen_daily_stats(db, org_id=target_org.org_id),
        }


GROUP_CHANNELS = ("amazon", "dtc_ad", "dtc_seo")


@router.get("/groups")
def ra_groups(
    channel: str | None = Query(default=None, max_length=24),
    include_rejected: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    """三分组池：GPT 终审 pass 的产品按渠道路由分组；review 进待滑堆。"""
    target_org = _required_target_org(db, user)
    cache_key = f"{target_org.org_id}|{channel or ''}|{include_rejected}|{limit}"
    cached = _groups_cache_get(cache_key)
    if cached is not None:
        return cached
    with without_org_data_isolation():
        # 只取分组卡需要的字段，不拉整份报告（报告里含全部 AI 层审计，很重）。
        rows = db.execute(
            text(
                """
                SELECT report_id, run_id, candidate_id, asin, status,
                       title, summary, created_at, updated_at,
                       jsonb_build_object(
                         'final', payload->'final',
                         'keywords', payload->'keywords',
                         'product', payload->'product',
                         'product_image_url', payload->'product_image_url',
                         'opus_review', payload->'opus_review',
                         'route_verdicts', jsonb_build_object(
                           'amazon', payload->'channel_routes'->'routes'->'amazon'->>'verdict',
                           'dtc_ad', payload->'channel_routes'->'routes'->'dtc_ad'->>'verdict',
                           'dtc_seo', payload->'channel_routes'->'routes'->'dtc_seo'->>'verdict'
                         ),
                         'has_deep_enrichment', (payload ? 'deep_enrichment'),
                         'rereviewed', (payload ? 'rereview_20260721'),
                         'route_recommendations', (
                           SELECT l->'model_output'->'route_recommendations'
                           FROM jsonb_array_elements(payload->'layers') l
                           WHERE l->'provider'->>'role' = 'gpt'
                           LIMIT 1
                         )
                       ) AS payload
                FROM ra_reports
                WHERE org_id = :org_id
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"org_id": target_org.org_id, "limit": limit},
        ).mappings().all()

    requested = (channel or "").strip().lower() or None
    groups: dict[str, list[dict[str, object]]] = {
        "amazon": [],
        "dtc_ad": [],
        "dtc_seo": [],
        "review": [],
    }
    seen_asins: dict[str, set[str]] = {key: set() for key in groups}
    for row in rows:
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        final = payload.get("final") if isinstance(payload.get("final"), dict) else {}
        verdict = str(final.get("verdict") or "")
        report_status = str(row["status"] or "ready")
        if report_status == "rejected" and not include_rejected:
            continue
        if verdict not in {"pass", "review", "reject"}:
            continue
        item = _group_item(row, payload=payload, final=final)
        asin = str(item.get("asin") or "")
        if verdict == "reject":
            # 风险阶梯分级放行：终审一票否决只管「亚马逊备货」这一层。
            # 独立站通道路由 pass 的照样进独立站托盘——零库存自发货蹭流量，
            # 昙花就昙花，开一单赚一单；卡片带「仅自发货·勿备货」标记。
            # 门槛：必须带深挖证据（Keepa 12月+Rainforest 全量）的淘汰品才放行，
            # 早期浅证据时代的淘汰品不翻案。
            # 2026-07-21 谷歌数据复核章 = 与深挖证据同等的还魂资格:
            # 复核是在完整谷歌信号下重新判的,不属于"浅证据翻案"。
            rereviewed = bool(payload.get("rereviewed"))
            if not payload.get("has_deep_enrichment") and not rereviewed:
                continue
            route_verdicts = (
                payload.get("route_verdicts")
                if isinstance(payload.get("route_verdicts"), dict)
                else {}
            )
            for group_name in ("dtc_ad", "dtc_seo"):
                if (
                    str(route_verdicts.get(group_name) or "") == "pass"
                    and asin not in seen_asins[group_name]
                ):
                    groups[group_name].append(
                        {
                            **item,
                            "group": group_name,
                            "fulfillment_only": True,
                            "rereviewed": rereviewed,
                            "ai_route_note": _ai_route_note(payload, group_name),
                        }
                    )
                    seen_asins[group_name].add(asin)
            # 复核后路由 review 的:终审否决只管备货层,人工滑一把再定生死。
            if rereviewed and asin not in seen_asins["review"] and any(
                str(route_verdicts.get(name) or "") == "review"
                for name in ("dtc_ad", "dtc_seo")
            ):
                groups["review"].append({**item, "rereviewed": True})
                seen_asins["review"].add(asin)
            continue
        if verdict == "review" and report_status != "approved":
            # 待滑堆：GPT 拿不准的产品等你亲手左右滑。
            if asin not in seen_asins["review"]:
                groups["review"].append(item)
                seen_asins["review"].add(asin)
            continue
        pass_channels = _report_pass_channels(final)
        for group_name in pass_channels:
            if group_name in groups and asin not in seen_asins[group_name]:
                groups[group_name].append(
                    {
                        **item,
                        "group": group_name,
                        "ai_route_note": _ai_route_note(payload, group_name),
                    }
                )
                seen_asins[group_name].add(asin)

    counts = {name: len(items) for name, items in groups.items()}
    if requested and requested in groups:
        return {
            "channel": requested,
            "items": groups[requested],
            "counts": counts,
        }
    response = {"groups": groups, "counts": counts}
    _groups_cache_put(cache_key, response)
    return response


def _ai_route_note(payload: dict[str, object], group_name: str) -> str | None:
    """终审 AI（luna）对该渠道的单独意见，展示在分组卡上供人工权衡。"""
    recommendations = payload.get("route_recommendations")
    if not isinstance(recommendations, dict):
        return None
    note = recommendations.get(group_name)
    if isinstance(note, dict):
        verdict = str(note.get("verdict") or "").strip()
        reason = str(note.get("reason") or "").strip()
        note = "：".join(part for part in (verdict, reason) if part)
    text_note = str(note or "").strip()
    return text_note[:220] or None


def _report_pass_channels(final: dict[str, object]) -> list[str]:
    primary = final.get("primary_channel")
    primary = primary if isinstance(primary, dict) else {}
    channels = [
        str(name)
        for name in (primary.get("all_pass_channels") or [])
        if str(name) in GROUP_CHANNELS
    ]
    routes_block = final.get("channel_routes")
    routes_block = routes_block if isinstance(routes_block, dict) else {}
    routes = routes_block.get("routes")
    if isinstance(routes, dict):
        for name, route in routes.items():
            if (
                str(name) in GROUP_CHANNELS
                and isinstance(route, dict)
                and route.get("verdict") == "pass"
                and str(name) not in channels
            ):
                channels.append(str(name))
    if not channels:
        fallback = str(final.get("channel") or primary.get("channel") or "").strip()
        if fallback == "both":
            channels = ["amazon", "dtc_seo"]
        elif fallback in GROUP_CHANNELS:
            channels = [fallback]
    return channels


def _group_item(
    row: dict[str, object] | object,
    *,
    payload: dict[str, object],
    final: dict[str, object],
) -> dict[str, object]:
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    keywords = payload.get("keywords") if isinstance(payload.get("keywords"), dict) else {}
    primary_channel = (
        final.get("primary_channel")
        if isinstance(final.get("primary_channel"), dict)
        else {}
    )
    opus_review = (
        payload.get("opus_review") if isinstance(payload.get("opus_review"), dict) else None
    )
    return {
        "report_id": row["report_id"],
        "run_id": row["run_id"],
        "candidate_id": row["candidate_id"],
        "asin": row["asin"],
        "status": row["status"],
        "title": row["title"],
        "summary": row["summary"],
        "image_url": payload.get("product_image_url"),
        "verdict": final.get("verdict"),
        "final_score": final.get("final_score"),
        "primary_channel": primary_channel.get("channel"),
        "pass_channels": _report_pass_channels(final),
        "gross_margin": product.get("gross_margin"),
        "monthly_sales": product.get("monthly_sales"),
        "price": product.get("price"),
        "primary_keyword": keywords.get("primary"),
        "keywords": keywords,
        "opus_review": opus_review,
        "decision_reason": final.get("decision_reason"),
        "created_at": str(row["created_at"]) if row["created_at"] else None,
        "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
    }


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


@router.get("/reports/{report_id}/detail")
def ra_report_detail(
    report_id: str,
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    """产品完整数据与上下文：Keepa/竞争/AI各层理由/关键词(分渠道)/供应商。"""
    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        row = db.execute(
            text(
                """
                SELECT report_id, run_id, candidate_id, asin, status,
                       title, summary, payload, created_at, updated_at
                FROM ra_reports
                WHERE report_id = :report_id AND org_id = :org_id
                LIMIT 1
                """
            ),
            {"report_id": report_id, "org_id": target_org.org_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="R-A 报告不存在。"
            )
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        # 直接按 candidate_id 查该产品的供应商（run 级列表有 LIMIT 会漏）。
        candidate_id = str(row["candidate_id"] or "")
        supplier_rows = db.execute(
            text(
                """
                SELECT o.id AS offer_id, o.supplier_name, o.supplier_url,
                       o.unit_price_cny, o.moq, o.match_score, o.offer_status,
                       o.payload AS offer_payload
                FROM ra_supplier_offers o
                WHERE o.org_id = :org_id AND o.candidate_id = :candidate_id
                ORDER BY o.unit_price_cny ASC NULLS LAST
                LIMIT 20
                """
            ),
            {"org_id": target_org.org_id, "candidate_id": candidate_id},
        ).mappings()
        supplier_items = []
        for supplier in supplier_rows:
            offer_payload = (
                supplier["offer_payload"]
                if isinstance(supplier["offer_payload"], dict)
                else {}
            )
            supplier_items.append(
                {
                    "offer_id": supplier["offer_id"],
                    "supplier_name": supplier["supplier_name"],
                    "supplier_url": supplier["supplier_url"],
                    "unit_price_cny": float(supplier["unit_price_cny"])
                    if supplier["unit_price_cny"] is not None
                    else None,
                    "moq": supplier["moq"],
                    "match_score": supplier["match_score"],
                    "offer_status": supplier["offer_status"],
                    "image_verdict": offer_payload.get("image_verdict"),
                    "source": offer_payload.get("api_family"),
                }
            )
    keywords = payload.get("keywords") if isinstance(payload.get("keywords"), dict) else {}
    signals = (
        payload.get("channel_signals")
        if isinstance(payload.get("channel_signals"), dict)
        else {}
    )
    competition = (
        payload.get("competition") if isinstance(payload.get("competition"), dict) else {}
    )
    if not keywords:
        # 旧报告没有 keywords 块：从已存的竞争/信号数据现场组装（回填）。
        dtc_seo = signals.get("dtc_seo") if isinstance(signals.get("dtc_seo"), dict) else {}
        serp = dtc_seo.get("serp") if isinstance(dtc_seo.get("serp"), dict) else {}
        page_one_titles = [
            str(item.get("title") or "")
            for item in (competition.get("page_one_sample") or [])
            if isinstance(item, dict) and item.get("title")
        ]
        keywords = {
            "primary": competition.get("keyword") or signals.get("keyword"),
            "secondary": serp.get("related_searches") or [],
            "long_tail": serp.get("people_also_ask") or [],
            "amazon_page_one_titles": page_one_titles[:10],
            "google_ads": {"status": "pending_basic_review", "ideas": []},
            "sources": {"backfilled": True},
        }
    # 亚马逊真关键词：首次打开时由 DeepSeek 从页一标题提炼，回写缓存。
    amazon_terms = keywords.get("amazon_terms")
    if not isinstance(amazon_terms, dict) or not amazon_terms.get("core_keywords"):
        from r_system_v2.ra.ai_selection import extract_amazon_ad_keywords

        with without_org_data_isolation():
            amazon_terms = extract_amazon_ad_keywords(
                db,
                org_id=target_org.org_id,
                primary=keywords.get("primary"),
                page_one_titles=keywords.get("amazon_page_one_titles") or [],
                product_title=str(row["title"] or ""),
            )
            if amazon_terms.get("core_keywords"):
                keywords["amazon_terms"] = amazon_terms
                db.execute(
                    text(
                        """
                        UPDATE ra_reports
                        SET payload = jsonb_set(
                              payload, '{keywords}', CAST(:keywords AS jsonb), true
                            ),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE report_id = :report_id AND org_id = :org_id
                        """
                    ),
                    {
                        "report_id": report_id,
                        "org_id": target_org.org_id,
                        "keywords": json.dumps(keywords, ensure_ascii=False, default=str),
                    },
                )
                db.commit()

    # 分渠道关键词：亚马逊侧（提炼后的真词）vs Google SEO 侧，明确标注。
    keyword_channels = {
        "amazon": {
            "primary": keywords.get("primary"),
            "core_keywords": (amazon_terms or {}).get("core_keywords") or [],
            "long_tail_keywords": (amazon_terms or {}).get("long_tail_keywords") or [],
            "source": "DeepSeek 从 Rainforest 页一竞品标题提炼（可直接投广告/写文案）",
        },
        "google_seo": {
            "related_searches": keywords.get("secondary") or [],
            "people_also_ask": keywords.get("long_tail") or [],
            "google_ads": keywords.get("google_ads") or {"status": "pending"},
            "source": "Serper 相关搜索/大家也在问 + Google Ads（过审后启用）",
        },
    }
    return {
        "report_id": row["report_id"],
        "run_id": row["run_id"],
        "candidate_id": row["candidate_id"],
        "asin": row["asin"],
        "status": row["status"],
        "title": row["title"],
        "summary": row["summary"],
        "product": payload.get("product"),
        "product_image_url": payload.get("product_image_url"),
        "final": payload.get("final"),
        "layers": [
            {
                "layer": layer.get("provider", {}).get("role")
                if isinstance(layer.get("provider"), dict)
                else None,
                "model": layer.get("provider", {}).get("model")
                if isinstance(layer.get("provider"), dict)
                else None,
                "score": layer.get("score"),
                "verdict": layer.get("verdict"),
                "reason": layer.get("reason"),
                "advantages": layer.get("advantages") or [],
                "risks": layer.get("risks") or [],
                "channel_guess": layer.get("channel_guess"),
            }
            for layer in (payload.get("layers") or [])
            if isinstance(layer, dict)
        ],
        "competition": competition,
        "channel_signals": signals,
        "channel_routes": payload.get("channel_routes"),
        "primary_channel": payload.get("primary_channel"),
        "keywords": keywords,
        "keyword_channels": keyword_channels,
        "opus_review": payload.get("opus_review"),
        "deep_enrichment": payload.get("deep_enrichment")
        if isinstance(payload.get("deep_enrichment"), dict)
        else None,
        "suppliers": supplier_items,
        "created_at": str(row["created_at"]) if row["created_at"] else None,
    }


@router.post("/reports/{report_id}/opus-review")
def ra_report_opus_review(
    report_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    _groups_cache_bust()
    """手动触发 Opus 建议：打包全部上下文，返回系统性建议。"""
    from r_system_v2.ra.ai_selection import RAAISelectionError, run_opus_review_for_report

    target_org = _required_target_org(db, user)
    try:
        with without_org_data_isolation():
            return run_opus_review_for_report(
                db, org_id=target_org.org_id, report_id=report_id
            )
    except RAAISelectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/reports/{report_id}/expand")
def ra_report_expand(
    report_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    """创建 1688 类目扩品后台任务（幂等）。"""
    from r_system_v2.ra.category_expansion import RAExpansionError, create_expansion_job

    target_org = _required_target_org(db, user)
    try:
        with without_org_data_isolation():
            return create_expansion_job(db, org_id=target_org.org_id, report_id=report_id)
    except RAExpansionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/reports/{report_id}/expansion")
def ra_report_expansion(
    report_id: str,
    db: Session = Depends(get_read_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    from r_system_v2.ra.category_expansion import get_latest_expansion

    target_org = _required_target_org(db, user)
    with without_org_data_isolation():
        payload = get_latest_expansion(db, org_id=target_org.org_id, report_id=report_id)
    if payload is None:
        return {"status": "none", "report_id": report_id}
    return payload


@router.post("/reports/{report_id}/approve")
def ra_report_approve(
    report_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    _groups_cache_bust()
    return _update_report_status(db, user=user, report_id=report_id, report_status="approved")


@router.post("/reports/{report_id}/reject")
def ra_report_reject(
    report_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    _groups_cache_bust()
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
