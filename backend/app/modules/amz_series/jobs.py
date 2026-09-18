"""amz-worker:按 (店铺 × 作业类型) 排队,FOR UPDATE SKIP LOCKED 领活,只在真干成活时写心跳。

作业:``rules_daily``(规则引擎 + 名册)、``sales_traffic``(销售与流量报表,每天回看三天)、``sqp_weekly``(搜索词表现,每周)。
出网作业只给**有 SP-API 凭据**的店排队——没凭据的店不排、不失败、不亮红,心跳缺席就是「未接入」。
心跳名 ``amz-worker:{store}:{job}``(String(64)),每店每种作业一条,验收只认它。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...db.session import SessionLocal
from ...services.data_isolation import SKIP_ORG_DATA_ISOLATION
from ...services.worker_heartbeat import record_failure, record_success
from . import rules
from .constants import MODULE_KEY, WORKER_NAME
from .models import AmzJob, AmzStore

logger = logging.getLogger("amz-worker")

JOB_RULES_DAILY = "rules_daily"
JOB_SALES_TRAFFIC = "sales_traffic"
JOB_SQP_WEEKLY = "sqp_weekly"
JOB_IMAGE_LOOKBACK = "image_lookback"
JOB_EXPERIENCE_WEEKLY = "experience_weekly"
JOB_LAUNCH_DAILY = "launch_daily"
JOB_FX_DAILY = "fx_daily"
JOB_COMPETITOR_DAILY = "competitor_daily"
JOB_BA_COMPETITORS = "ba_competitors"
JOB_INVENTORY_DAILY = "inventory_daily"
JOB_LISTINGS_DAILY = "listings_daily"
JOB_FINANCES_DAILY = "finances_daily"
JOB_SOLICITATIONS_DAILY = "solicitations_daily"
# 作业 → 期望间隔(秒)。心跳的 expected_interval 也用它;超过 3 倍没干成活 = stale。
JOB_INTERVALS: dict[str, int] = {JOB_RULES_DAILY: 24 * 3600, JOB_SALES_TRAFFIC: 24 * 3600, JOB_SQP_WEEKLY: 7 * 24 * 3600, JOB_IMAGE_LOOKBACK: 24 * 3600, JOB_EXPERIENCE_WEEKLY: 7 * 24 * 3600, JOB_LAUNCH_DAILY: 24 * 3600, JOB_FX_DAILY: 24 * 3600, JOB_COMPETITOR_DAILY: 24 * 3600, JOB_BA_COMPETITORS: 7 * 24 * 3600, JOB_INVENTORY_DAILY: 24 * 3600, JOB_LISTINGS_DAILY: 24 * 3600, JOB_FINANCES_DAILY: 24 * 3600, JOB_SOLICITATIONS_DAILY: 24 * 3600}
# 要出网的作业:只在店铺有 SP-API 凭据时才排。
API_JOBS: frozenset[str] = frozenset({JOB_SALES_TRAFFIC, JOB_SQP_WEEKLY, JOB_BA_COMPETITORS, JOB_INVENTORY_DAILY, JOB_LISTINGS_DAILY, JOB_FINANCES_DAILY, JOB_SOLICITATIONS_DAILY})
# 失败后的重试间隔:失败不等于「该再排一条」,否则一个坏凭据会每 15 秒失败一次刷满作业表。
FAILED_RETRY_SECONDS = 3600
_TABLE = "amz_jobs"


def poll_seconds() -> float:
    try:
        return max(2.0, float(os.getenv("AMZ_WORKER_POLL_SECONDS", "15")))
    except ValueError:
        return 15.0


def heartbeat_name(store_code: str, job_type: str) -> str:
    return f"{WORKER_NAME}:{store_code}:{job_type}"


# ---------------------------------------------------------------- 排队


def _has_keepa(db: Session, store: AmzStore) -> bool:
    from ...models.api_keys import ApiKeyModuleBindingRecord  # noqa: PLC0415
    from ...services.data_isolation import without_org_data_isolation  # noqa: PLC0415
    from .constants import KEY_ALIAS_KEEPA  # noqa: PLC0415

    with without_org_data_isolation():
        found = db.scalar(select(ApiKeyModuleBindingRecord.id).where(ApiKeyModuleBindingRecord.org_id == store.company_org_id, ApiKeyModuleBindingRecord.module_id == MODULE_KEY, ApiKeyModuleBindingRecord.key_alias == KEY_ALIAS_KEEPA, ApiKeyModuleBindingRecord.status == "active"))
    db.commit()
    return found is not None


def schedule_due_jobs(db: Session, *, now: datetime | None = None) -> int:
    """每个活跃店 × 每种作业:没有 pending/running 且距上次完成超过间隔 → 补一条 pending。"""
    now = now or datetime.now(UTC)
    created = 0
    stores = list(db.scalars(select(AmzStore).where(AmzStore.status == "active")))
    db.commit()
    # 凭据检查要解密(CPU 几秒),不能挂在排队事务里——worker 连接 8 秒 idle-in-transaction 就被掐。
    from .clients.sp_api import has_credentials  # noqa: PLC0415

    connected: dict[str, bool] = {}
    for store in stores:
        connected[store.store_code] = has_credentials(db, store)
        db.commit()
    for store in stores:
        store_code = store.store_code
        for job_type, interval in JOB_INTERVALS.items():
            if job_type in API_JOBS and not connected.get(store_code):
                continue
            if job_type == JOB_FX_DAILY and store.currency == "USD":
                continue  # 美元店不需要汇率
            if job_type == JOB_COMPETITOR_DAILY and not _has_keepa(db, store):
                continue  # 这家公司还没绑 Keepa 钥匙
            active = db.scalar(
                select(AmzJob.id).where(
                    AmzJob.store_code == store_code,
                    AmzJob.job_type == job_type,
                    AmzJob.status.in_(("pending", "running")),
                ).limit(1)
            )
            if active is not None:
                continue
            last = db.execute(
                select(AmzJob.status, AmzJob.finished_at)
                .where(AmzJob.store_code == store_code, AmzJob.job_type == job_type, AmzJob.status.in_(("done", "failed")), AmzJob.finished_at.is_not(None))
                .order_by(AmzJob.finished_at.desc())
                .limit(1)
            ).first()
            if last is not None:
                last_status, last_finished = last
                wait = interval if last_status == "done" else min(FAILED_RETRY_SECONDS, interval)
                if (now - last_finished) < timedelta(seconds=wait):
                    continue
            db.add(AmzJob(store_code=store_code, job_type=job_type, status="pending", run_after=now))
            created += 1
    db.commit()
    return created


def requeue_stale_running(db: Session, *, older_than_seconds: int = 1800) -> int:
    result = db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'pending', updated_at = now(), last_error = 'requeued: stale running'
            WHERE status = 'running' AND started_at < now() - make_interval(secs => :age)
            """
        ),
        {"age": older_than_seconds},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    db.commit()
    return int(result.rowcount or 0)


def claim(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT id, store_code, job_type
            FROM {_TABLE}
            WHERE status = 'pending' AND run_after <= now()
            ORDER BY run_after ASC
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"limit": limit},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings().all()
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'running', started_at = now(), locked_at = now(), attempts = attempts + 1, updated_at = now()
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": ids},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    db.commit()
    return [dict(r) for r in rows]


def finish(job_id: Any, status: str, *, error: str | None = None, payload: dict[str, Any] | None = None) -> None:
    with SessionLocal() as db:
        row = db.get(AmzJob, job_id)
        if row is None:
            return
        row.status = status
        row.last_error = (error or "")[:2000] or None
        row.finished_at = datetime.now(UTC)
        if payload is not None:
            row.payload_json = payload
        db.add(row)
        db.commit()


# ---------------------------------------------------------------- 执行


def run_rules_daily(store_code: str) -> dict[str, Any]:
    with SessionLocal() as db:
        store = db.get(AmzStore, store_code)
        if store is None:
            raise RuntimeError(f"store {store_code} missing")
        from . import products  # noqa: PLC0415

        roster = products.sync_from_transactions(db, store_code=store_code)
        counts = rules.run_rules_for_store(db, store_code=store_code, currency=store.currency)
        counts["roster"] = roster
        db.commit()
        return counts


def _with_client(store_code: str, fn: Callable[[Session, Any, AmzStore], dict[str, Any]]) -> dict[str, Any]:
    from .clients.sp_api import SpApiClient  # noqa: PLC0415

    with SessionLocal() as db:
        store = db.get(AmzStore, store_code)
        if store is None:
            raise RuntimeError(f"store {store_code} missing")
        client = SpApiClient.for_store(db, store)
        db.commit()  # 取凭据也是一次读,收掉
        try:
            result = fn(db, client, store)
            db.commit()
            result["api_calls"] = client.calls
            return result
        finally:
            client.close()


def run_sales_traffic(store_code: str) -> dict[str, Any]:
    from . import reports_sync  # noqa: PLC0415

    return _with_client(store_code, lambda db, client, store: reports_sync.sync_sales_traffic(db, client, store))


def run_sqp_weekly(store_code: str) -> dict[str, Any]:
    """SQP 按 ASIN 要;还没有销售数据就先拉一次销售与流量,免得第一周空跑、下一次要等七天。"""
    from . import reports_sync  # noqa: PLC0415
    from datetime import date as _date  # noqa: PLC0415

    def _run(db: Session, client: Any, store: AmzStore) -> dict[str, Any]:
        primed = None
        has_asins = bool(reports_sync.active_asins(db, store.store_code, since=_date.today() - timedelta(days=reports_sync.SQP_LOOKBACK_DAYS)))
        db.commit()  # 读完收事务,出网前不能挂着
        if not has_asins:
            primed = reports_sync.sync_sales_traffic(db, client, store)
        result = reports_sync.sync_sqp(db, client, store)
        if primed is not None:
            result["primed_sales_traffic"] = primed
        if not result.get("asins") and not result.get("skipped"):
            raise RuntimeError("sqp: no asins with sales in the lookback window, nothing fetched")
        return result

    return _with_client(store_code, _run)


def run_image_lookback(store_code: str) -> dict[str, Any]:
    """图上线 14 / 28 天回看(不出网;只看本店的 brief)。"""
    from . import images  # noqa: PLC0415

    with SessionLocal() as db:
        done = images.run_lookbacks(db)
        db.commit()
        return {"lookbacks": done}


def run_experience_weekly(store_code: str) -> dict[str, Any]:
    """经验库每周刷新:判结果(真建议 + 回测)→ 条目 → 参数漂移。不出网。"""
    from . import experience  # noqa: PLC0415

    with SessionLocal() as db:
        store = db.get(AmzStore, store_code)
        if store is None:
            raise RuntimeError(f"store {store_code} missing")
        out = experience.refresh_store(db, store)
        db.commit()
        return out


def run_launch_daily(store_code: str) -> dict[str, Any]:
    """推新蜜月期:每天重算;满 45 天判一次并落一条要人拍板的建议。不出网。"""
    from . import launches  # noqa: PLC0415

    with SessionLocal() as db:
        out = launches.run_daily(db, store_code=store_code)
        db.commit()
        return out


def run_fx_daily(store_code: str) -> dict[str, Any]:
    """欧洲央行参考汇率补齐到今天,并按当天汇率重算这家店的交易美元数。免费接口,出网前已收事务。"""
    from . import fx  # noqa: PLC0415

    with SessionLocal() as db:
        store = db.get(AmzStore, store_code)
        if store is None:
            raise RuntimeError(f"store {store_code} missing")
        out = fx.sync_store(db, store)
        db.commit()
        return out


def run_competitor_daily(store_code: str) -> dict[str, Any]:
    """补名单 → 这家店所在站点今天还没拍的 ASIN 拍 Keepa 快照(台账封顶)→ 变化规则跟着 rules_daily 出。"""
    from r_system_v2.ra.quota_ledger import PROVIDER_AMZ_KEEPA, RAQuotaExhaustedError, try_consume  # noqa: PLC0415

    from . import competitors  # noqa: PLC0415

    with SessionLocal() as db:
        store = db.get(AmzStore, store_code)
        if store is None:
            raise RuntimeError(f"store {store_code} missing")
        watch = competitors.sync_watchlist(db)
        db.commit()

        def budget(amount: int) -> bool:
            with SessionLocal() as ledger_db:
                try:
                    try_consume(ledger_db, PROVIDER_AMZ_KEEPA, amount=amount)
                    return True
                except RAQuotaExhaustedError:
                    return False

        out = competitors.snapshot_marketplace(db, store, budget=budget)
        db.commit()
        return {**out, "watchlist_added": watch["added"]}


def run_ba_competitors(store_code: str) -> dict[str, Any]:
    """品牌分析搜索词报表 → 核心词点击前三 → 竞品名单(站点级,一周一次;报表没好就 deferred,不写心跳)。"""
    from . import ba_competitors  # noqa: PLC0415

    return _with_client(store_code, lambda db, client, store: ba_competitors.run(db, client, store))


def run_inventory_daily(store_code: str) -> dict[str, Any]:
    from . import ops_sync  # noqa: PLC0415

    return _with_client(store_code, lambda db, client, store: ops_sync.sync_inventory(db, client, store))


def run_listings_daily(store_code: str) -> dict[str, Any]:
    from . import ops_sync  # noqa: PLC0415

    return _with_client(store_code, lambda db, client, store: ops_sync.sync_listings(db, client, store))


def run_finances_daily(store_code: str) -> dict[str, Any]:
    from . import ops_sync  # noqa: PLC0415

    return _with_client(store_code, lambda db, client, store: ops_sync.sync_finances(db, client, store))


def run_solicitations_daily(store_code: str) -> dict[str, Any]:
    """请求留评:影子期只查资格记 would_request;店铺总闸开了才真发。"""
    from . import ops_sync  # noqa: PLC0415

    return _with_client(store_code, lambda db, client, store: ops_sync.run_solicitations(db, client, store))


HANDLERS: dict[str, Callable[[str], dict[str, Any]]] = {
    JOB_INVENTORY_DAILY: run_inventory_daily,
    JOB_LISTINGS_DAILY: run_listings_daily,
    JOB_FINANCES_DAILY: run_finances_daily,
    JOB_SOLICITATIONS_DAILY: run_solicitations_daily,
    JOB_BA_COMPETITORS: run_ba_competitors,
    JOB_RULES_DAILY: run_rules_daily,
    JOB_COMPETITOR_DAILY: run_competitor_daily,
    JOB_FX_DAILY: run_fx_daily,
    JOB_LAUNCH_DAILY: run_launch_daily,
    JOB_EXPERIENCE_WEEKLY: run_experience_weekly,
    JOB_IMAGE_LOOKBACK: run_image_lookback,
    JOB_SALES_TRAFFIC: run_sales_traffic,
    JOB_SQP_WEEKLY: run_sqp_weekly,
}


def process_job(job: dict[str, Any]) -> bool:
    store_code, job_type = job["store_code"], job["job_type"]
    handler = HANDLERS.get(job_type)
    if handler is None:
        finish(job["id"], "failed", error=f"no handler for {job_type}")
        return False
    try:
        result = handler(store_code)
    except Exception as exc:  # noqa: BLE001 - 一条作业炸了不能拖死循环
        logger.exception("amz job failed store=%s job=%s", store_code, job_type)
        finish(job["id"], "failed", error=str(exc))
        with SessionLocal() as db:
            record_failure(db, worker_name=heartbeat_name(store_code, job_type), error=str(exc)[:500], module_key=MODULE_KEY, expected_interval_seconds=JOB_INTERVALS[job_type])
        return False
    deferred = result.get("deferred_seconds") if isinstance(result, dict) else None
    if deferred:
        # 还没干成(比如报表还在生成):放回队列过一会再来,不写心跳——心跳只记真干成的活
        with SessionLocal() as db:
            row = db.get(AmzJob, job["id"])
            if row is not None:
                row.status = "pending"
                row.run_after = datetime.now(UTC) + timedelta(seconds=float(deferred))
                row.payload_json = result
                db.add(row)
                db.commit()
        logger.info("amz job deferred store=%s job=%s result=%s", store_code, job_type, result)
        return True
    finish(job["id"], "done", payload=result)
    with SessionLocal() as db:
        record_success(db, worker_name=heartbeat_name(store_code, job_type), module_key=MODULE_KEY, expected_interval_seconds=JOB_INTERVALS[job_type])
    logger.info("amz job done store=%s job=%s result=%s", store_code, job_type, result)
    return True


class AmzWorker:
    def __init__(self, *, session_factory: Callable[[], Session] = SessionLocal, poll: float | None = None, concurrency: int = 2) -> None:
        self.session_factory = session_factory
        self.poll = poll or poll_seconds()
        self.concurrency = concurrency

    def run_once(self, *, log: Callable[[str], None] | None = None) -> bool:
        did_work = False
        with self.session_factory() as db:
            created = schedule_due_jobs(db)
            if created and log:
                log(f"scheduled {created} amz jobs")
            jobs = claim(db, self.concurrency)
        for job in jobs:
            process_job(job)
            did_work = True
        return did_work

    def run_forever(self, *, should_stop: Callable[[], bool], log: Callable[[str], None] | None = None) -> None:
        if log:
            log(f"amz worker started poll={self.poll:g}s concurrency={self.concurrency}")
        # 起步只写一次「进程活着」的总心跳;每店每种作业的心跳只在真干成活时写。
        with self.session_factory() as db:
            record_success(db, worker_name=WORKER_NAME, module_key=MODULE_KEY, expected_interval_seconds=JOB_INTERVALS[JOB_RULES_DAILY])
        while not should_stop():
            try:
                did_work = self.run_once(log=log)
            except Exception as exc:  # noqa: BLE001
                logger.exception("amz worker loop error")
                with self.session_factory() as db:
                    record_failure(db, worker_name=WORKER_NAME, error=str(exc)[:500], module_key=MODULE_KEY, expected_interval_seconds=JOB_INTERVALS[JOB_RULES_DAILY])
                did_work = False
            if not did_work:
                time.sleep(self.poll)


__all__ = ["AmzWorker", "JOB_INTERVALS", "JOB_RULES_DAILY", "claim", "finish", "heartbeat_name", "process_job", "requeue_stale_running", "schedule_due_jobs"]
