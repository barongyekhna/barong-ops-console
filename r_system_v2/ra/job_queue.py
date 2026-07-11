"""Background R-A profit job queue backed by ra_selection_runs."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from decimal import Decimal
import json
import os
import re
import time
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from r_system_v2.ra.ai_selection import (
    load_ai_selection_by_candidate,
    load_ai_selection_for_run,
    run_ai_selection_for_candidate,
)
from r_system_v2.ra.ai_selection_mock import run_mock_ai_selection_for_candidate
from r_system_v2.ra.auto_profit import (
    DEFAULT_SUPPLIER_LIMIT,
    MAX_ASIN_LIMIT,
    MAX_SUPPLIER_LIMIT,
    match_rw_products_for_query,
    select_auto_candidates,
)
from r_system_v2.ra.exchange_rate import get_usd_cny_quote
from r_system_v2.ra.profit_engine import decimal_value
from r_system_v2.ra.profit_service import _json_bind
from r_system_v2.ra.profit_service import profit_formula_config
from r_system_v2.ra.events import emit_event
from r_system_v2.ra.prescreen import (
    load_prescreen_scores,
    prescreen_mode,
    run_prescreen_for_product,
)
from r_system_v2.ra.quota_ledger import (
    PROVIDER_1688_CPS_IMAGE_SEARCH,
    PROVIDER_1688_IMAGE_SEARCH,
    RAQuotaExhaustedError,
)
from r_system_v2.ra.relevance import classify_product_relevance
from r_system_v2.ra.supplier_discovery import discover_1688_supplier_offers
from r_system_v2.rw.product_images import primary_product_image_url, product_image_candidates


DEFAULT_JOB_ASIN_LIMIT = 20
DEFAULT_TARGET_PROFIT_PASS = 10
DEFAULT_MAX_PRODUCTS_PER_JOB = 240
DEFAULT_WORKER_CONCURRENCY = 3
DEFAULT_AI_WORKER_CONCURRENCY = 2
DEFAULT_POLL_SECONDS = 3.0


class RAJobError(RuntimeError):
    pass


def create_auto_profit_job(
    db: Session,
    *,
    org_id: str,
    query: str,
    asin_limit: int = DEFAULT_JOB_ASIN_LIMIT,
    supplier_limit: int = DEFAULT_SUPPLIER_LIMIT,
    min_gross_margin: Decimal | None = None,
    run_ai_chain: bool = True,
    selection_channel: str = "amazon",
    triggered_by: str | None = None,
    auto_cruise: bool = False,
    target_profit_pass: int | None = None,
    max_products_per_job: int | None = None,
) -> dict[str, object]:
    cleaned_query = str(query or "").strip()
    if not cleaned_query and not auto_cruise:
        raise RAJobError("请输入关键词或类目。")

    run_id = str(uuid4())
    filters = {
        "query": cleaned_query[:120],
        "asin_limit": _bounded_asin_limit(asin_limit),
        "supplier_limit": _bounded_supplier_limit(supplier_limit),
        "target_profit_pass": _target_profit_pass(target_profit_pass),
        "max_products_per_job": _max_products_per_job(max_products_per_job),
        "min_gross_margin": _number(min_gross_margin),
        "run_ai_chain": bool(run_ai_chain),
        "run_ai_mock": False,
        "selection_channel": _selection_channel(selection_channel),
        "auto_cruise": bool(auto_cruise),
    }
    counts = _initial_counts(filters)
    db.execute(
        text(
            f"""
            INSERT INTO ra_selection_runs (
              run_id, org_id, channel, status, triggered_by, filters,
              counts, runtime_mode
            )
            VALUES (
              :run_id, :org_id, 'profit_auto', 'queued', :triggered_by,
              {_json_bind(db, "filters")}, {_json_bind(db, "counts")},
              'background_profit_queue'
            )
            """
        ),
        {
            "run_id": run_id,
            "org_id": org_id,
            "triggered_by": triggered_by,
            "filters": json.dumps(filters, ensure_ascii=False),
            "counts": json.dumps(counts, ensure_ascii=False),
        },
    )
    db.commit()
    return get_auto_profit_job(db, org_id=org_id, run_id=run_id)


def get_auto_profit_job(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    item_page: int = 1,
    item_page_size: int = 50,
    item_search: str | None = None,
    item_category: str | None = None,
    item_verdict: str | None = None,
    item_sort: str | None = None,
    item_sort_direction: str | None = None,
) -> dict[str, object]:
    row = _load_job_row(db, org_id=org_id, run_id=run_id)
    if row is None:
        raise RAJobError("R-A 任务不存在。")
    return _job_payload(
        db,
        row,
        item_page=item_page,
        item_page_size=item_page_size,
        item_search=item_search,
        item_category=item_category,
        item_verdict=item_verdict,
        item_sort=item_sort,
        item_sort_direction=item_sort_direction,
    )


def get_latest_auto_profit_job(
    db: Session,
    *,
    org_id: str,
    item_page: int = 1,
    item_page_size: int = 50,
    item_search: str | None = None,
    item_category: str | None = None,
    item_verdict: str | None = None,
    item_sort: str | None = None,
    item_sort_direction: str | None = None,
) -> dict[str, object] | None:
    row = _load_latest_job_row(db, org_id=org_id)
    if row is None:
        return None
    return _job_payload(
        db,
        row,
        item_page=item_page,
        item_page_size=item_page_size,
        item_search=item_search,
        item_category=item_category,
        item_verdict=item_verdict,
        item_sort=item_sort,
        item_sort_direction=item_sort_direction,
    )


def get_auto_profit_job_status(
    db: Session,
    *,
    org_id: str,
    run_id: str | None = None,
) -> dict[str, object] | None:
    """Lightweight run status for frontend polling: row + counts only, no items."""
    row = (
        _load_job_row(db, org_id=org_id, run_id=run_id)
        if run_id
        else _load_latest_job_row(db, org_id=org_id)
    )
    if row is None:
        return None
    counts = _dict_value(row.get("counts"))
    if str(row.get("status") or "") in {"queued", "running"}:
        counts.update(
            _live_counts(db, org_id=str(row["org_id"]), run_id=str(row["run_id"]))
        )
    db.rollback()
    filters = _dict_value(row.get("filters"))
    return {
        "run_id": str(row["run_id"]),
        "status": row.get("status"),
        "runtime_mode": row.get("runtime_mode"),
        "query": filters.get("query"),
        "counts": counts,
        "warnings": counts.get("warnings") or [],
        "created_at": _iso(row.get("created_at")),
        "started_at": _iso(row.get("started_at")),
        "finished_at": _iso(row.get("finished_at")),
    }


def cancel_auto_profit_job(
    db: Session,
    *,
    org_id: str,
    run_id: str,
) -> dict[str, object]:
    row = _load_job_row(db, org_id=org_id, run_id=run_id)
    if row is None:
        raise RAJobError("R-A 任务不存在。")
    counts = _dict_value(row.get("counts"))
    warnings = list(counts.get("warnings") or [])
    if str(row.get("status") or "") not in {"completed", "partial", "failed", "cancelled"}:
        warnings.append("用户已取消任务，worker 会停止继续拉取新候选。")
        counts["warnings"] = warnings[-10:]
        _update_job(db, run_id=run_id, status="cancelled", counts=counts, finish=True)
        row = _load_job_row(db, org_id=org_id, run_id=run_id) or row
    return _job_payload(db, row)


class RaProfitJobWorker:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        concurrency: int | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.poll_seconds = max(1.0, poll_seconds)
        self.concurrency = _worker_concurrency(concurrency)

    def run_forever(self, *, should_stop: Callable[[], bool], log: Callable[[str], None]) -> None:
        log(
            "R-A profit job worker started "
            f"concurrency={self.concurrency} poll_seconds={self.poll_seconds:g}"
        )
        while not should_stop():
            try:
                ran = self.run_once(log=log)
            except Exception as exc:  # pragma: no cover - production guardrail.
                log(f"R-A profit job worker error={exc}")
                ran = False
            if not ran:
                time.sleep(self.poll_seconds)

    def run_once(self, *, log: Callable[[str], None] | None = None) -> bool:
        with self.session_factory() as db:
            with _without_org_data_isolation():
                job = _claim_next_job(db)
        if job is None:
            return False

        run_id = str(job["run_id"])
        org_id = str(job["org_id"])
        if log:
            log(f"R-A job claimed run_id={run_id}")
        try:
            self._process_job(job, log=log)
        except Exception as exc:
            with self.session_factory() as db:
                with _without_org_data_isolation():
                    row = _load_job_row(db, org_id=org_id, run_id=run_id)
                    counts = _dict_value(row.get("counts") if row else {})
                    warnings = list(counts.get("warnings") or [])
                    warnings.append(str(exc))
                    counts["warnings"] = warnings[-10:]
                    _update_job(db, run_id=run_id, status="failed", counts=counts, finish=True)
            if log:
                log(f"R-A job failed run_id={run_id} error={exc}")
        return True

    def _process_job(self, job: dict[str, Any], *, log: Callable[[str], None] | None) -> None:
        run_id = str(job["run_id"])
        org_id = str(job["org_id"])
        filters = _dict_value(job.get("filters"))
        query = str(filters.get("query") or "").strip()
        asin_limit = _bounded_asin_limit(filters.get("asin_limit") or DEFAULT_JOB_ASIN_LIMIT)
        supplier_limit = _bounded_supplier_limit(
            filters.get("supplier_limit") or DEFAULT_SUPPLIER_LIMIT
        )
        min_gross_margin = decimal_value(filters.get("min_gross_margin"))
        run_ai_chain = filters.get("run_ai_chain", filters.get("run_ai_mock")) is not False
        selection_channel = _selection_channel(filters.get("selection_channel") or "amazon")
        auto_cruise = bool(filters.get("auto_cruise"))
        quote = get_usd_cny_quote()
        target_profit_pass = _target_profit_pass(filters.get("target_profit_pass"))
        max_products_per_job = _max_products_per_job(filters.get("max_products_per_job"))
        attempted_asins: set[str] = set()

        with self.session_factory() as db:
            with _without_org_data_isolation():
                counts = _dict_value(job.get("counts"))
                counts.pop("yield_requested", None)
                counts.update(
                    {
                        "target_profit_pass": target_profit_pass,
                        "max_products_per_job": max_products_per_job,
                        "worker_concurrency": self.concurrency,
                        "matched_products": 0,
                        "selected_products": 0,
                        "processed_products": 0,
                        "candidate_offers": 0,
                        "priced_offers": 0,
                        "profit_snapshots": 0,
                        "profit_pass": 0,
                        "profit_reject": 0,
                        "profit_blocked": 0,
                        "profit_quantity_pending": 0,
                        "warnings": [],
                    }
                )
                _update_job(db, run_id=run_id, status="running", counts=counts)

        while True:
            with self.session_factory() as db:
                with _without_org_data_isolation():
                    row = _load_job_row(db, org_id=org_id, run_id=run_id)
                    counts = _dict_value(row.get("counts") if row else {})
                    if row and str(row.get("status") or "") == "cancelled":
                        counts["cancelled"] = True
                        _update_job(db, run_id=run_id, status="cancelled", counts=counts, finish=True)
                        return
                    live_counts = _live_counts(db, org_id=org_id, run_id=run_id)
                    counts.update(live_counts)
                    current_pass = int(counts.get("profit_pass") or 0)
                    processed = int(counts.get("processed_products") or 0)
                    if (
                        current_pass >= target_profit_pass
                        or processed >= max_products_per_job
                        or counts.get("fatal_provider_error")
                        or counts.get("quota_exhausted")
                        or counts.get("yield_requested")
                    ):
                        _update_job(db, run_id=run_id, status="running", counts=counts)
                        break
                    # 当天已「顺延」的产品不再重选，防止图搜额度耗尽时循环空转。
                    deferred_today = _deferred_asins_today(db, org_id=org_id)
                    excluded_asins = attempted_asins | deferred_today
                    if auto_cruise:
                        products = select_auto_candidates(
                            db,
                            org_id=org_id,
                            limit=asin_limit,
                            exclude_asins=excluded_asins,
                        )
                        products = _order_by_prescreen_score(
                            db, org_id=org_id, products=products
                        )
                    else:
                        products = match_rw_products_for_query(
                            db,
                            org_id=org_id,
                            query=query,
                            limit=asin_limit,
                            exclude_asins=excluded_asins,
                        )
                    fresh_products = [
                        product
                        for product in products
                        if str(product.get("asin") or "").upper() not in excluded_asins
                    ]
                    counts["matched_products"] = int(counts.get("matched_products") or 0) + len(
                        fresh_products
                    )
                    _update_job(db, run_id=run_id, status="running", counts=counts)
                    db.rollback()

            if not fresh_products:
                with self.session_factory() as db:
                    with _without_org_data_isolation():
                        row = _load_job_row(db, org_id=org_id, run_id=run_id)
                        counts = _dict_value(row.get("counts") if row else {})
                        if auto_cruise:
                            warnings = list(counts.get("warnings") or [])
                            warnings.append(
                                "自动巡库：当前没有更多未处理的 R-W 产品，等待新品入库。"
                            )
                            counts["warnings"] = warnings[-10:]
                            _update_job(db, run_id=run_id, status="running", counts=counts)
                        elif int(counts.get("processed_products") or 0) == 0:
                            notice = _no_rw_product_notice(query)
                            warnings = list(counts.get("warnings") or [])
                            warnings.append(notice["message"])
                            counts.update(
                                {
                                    "rw_empty_result": True,
                                    "empty_reason": notice["reason"],
                                    "empty_recommendation": notice["recommendation"],
                                    "warnings": warnings[-10:],
                                }
                            )
                        else:
                            warnings = list(counts.get("warnings") or [])
                            warnings.append(
                                "本次可匹配的 R-W 产品已经全部尝试，利润通过数未达到目标。"
                            )
                            counts["warnings"] = warnings[-10:]
                        _update_job(db, run_id=run_id, status="running", counts=counts)
                break

            batch_result = self._process_product_batch(
                products=fresh_products,
                attempted_asins=attempted_asins,
                org_id=org_id,
                run_id=run_id,
                supplier_limit=supplier_limit,
                exchange_rate=quote.rate,
                min_gross_margin=min_gross_margin,
                target_profit_pass=target_profit_pass,
                run_ai_chain=run_ai_chain,
                selection_channel=selection_channel,
                allow_mock_fallback=not auto_cruise,
                log=log,
            )
            if batch_result.get("yielded"):
                break
            if not batch_result["processed"]:
                break

        with self.session_factory() as db:
            with _without_org_data_isolation():
                row = _load_job_row(db, org_id=org_id, run_id=run_id)
                counts = _dict_value(row.get("counts") if row else {})
                counts.update(_live_counts(db, org_id=org_id, run_id=run_id))
                if counts.pop("yield_requested", None):
                    # 让位给定向探测：保存进度回队列，手动任务跑完自动续。
                    warnings = list(counts.get("warnings") or [])
                    warnings.append("巡库暂让：定向探测优先，完成后自动继续。")
                    counts["warnings"] = warnings[-10:]
                    _update_job(db, run_id=run_id, status="queued", counts=counts, finish=False)
                    if log:
                        log(f"R-A job yielded to manual probe run_id={run_id}")
                    return
                if run_ai_chain:
                    ai_result = load_ai_selection_for_run(
                        db,
                        org_id=org_id,
                        run_id=run_id,
                    )
                    counts.update(_dict_value(ai_result.get("counts")))
                if int(counts.get("profit_pass") or 0) >= target_profit_pass:
                    final_status = "completed"
                elif counts.get("quota_exhausted"):
                    # 日预算用完不算失败：暂停，worker 明天自动重新认领续跑。
                    final_status = "paused"
                    counts["quota_exhausted"] = False
                elif counts.get("fatal_provider_error"):
                    final_status = "failed"
                elif counts.get("warnings"):
                    final_status = "partial"
                else:
                    final_status = "completed"
                _update_job(
                    db,
                    run_id=run_id,
                    status=final_status,
                    counts=counts,
                    finish=final_status != "paused",
                )
        if log:
            log(f"R-A job finished run_id={run_id}")

    def _process_product_batch(
        self,
        *,
        products: list[dict[str, Any]],
        attempted_asins: set[str],
        org_id: str,
        run_id: str,
        supplier_limit: int,
        exchange_rate: Decimal,
        min_gross_margin: Decimal | None,
        target_profit_pass: int,
        run_ai_chain: bool,
        selection_channel: str,
        allow_mock_fallback: bool = True,
        log: Callable[[str], None] | None = None,
    ) -> dict[str, int]:
        processed = 0
        product_index = 0
        was_yielded = False
        ai_workers = _ai_worker_concurrency(None) if run_ai_chain else 0
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            ai_executor = ThreadPoolExecutor(max_workers=ai_workers) if ai_workers > 0 else None
            pending: set[Any] = set()
            pending_ai: set[Any] = set()
            try:
                while product_index < len(products) or pending:
                    self._record_finished_ai_jobs(
                        org_id=org_id,
                        run_id=run_id,
                        pending_ai=pending_ai,
                        log=log,
                    )
                    with self.session_factory() as db:
                        with _without_org_data_isolation():
                            row = _load_job_row(db, org_id=org_id, run_id=run_id)
                            counts = _dict_value(row.get("counts") if row else {})
                            if row and str(row.get("status") or "") == "cancelled":
                                counts["cancelled"] = True
                                _update_job(db, run_id=run_id, status="cancelled", counts=counts, finish=True)
                                return {"processed": processed}
                            counts.update(_live_counts(db, org_id=org_id, run_id=run_id))
                            current_pass = int(counts.get("profit_pass") or 0)
                            quota_exhausted = bool(counts.get("quota_exhausted"))
                            if counts.get("yield_requested"):
                                was_yielded = True
                    if quota_exhausted or was_yielded:
                        # 停止投放新产品，只把在途的跑完。
                        product_index = len(products)
                    if current_pass >= target_profit_pass and not pending:
                        break
                    if (quota_exhausted or was_yielded) and not pending:
                        break

                    max_pending = self.concurrency
                    while (
                        len(pending) < max_pending
                        and product_index < len(products)
                        and current_pass < target_profit_pass
                    ):
                        product = products[product_index]
                        product_index += 1
                        asin = str(product.get("asin") or "").upper()
                        if not asin or asin in attempted_asins:
                            continue
                        attempted_asins.add(asin)
                        pending.add(
                            executor.submit(
                                _process_product_for_job,
                                self.session_factory,
                                org_id,
                                run_id,
                                asin,
                                supplier_limit,
                                exchange_rate,
                                min_gross_margin,
                                product,
                            )
                        )
                        with self.session_factory() as db:
                            with _without_org_data_isolation():
                                row = _load_job_row(db, org_id=org_id, run_id=run_id)
                                counts = _dict_value(row.get("counts") if row else {})
                                counts["selected_products"] = int(
                                    counts.get("selected_products") or 0
                                ) + 1
                                _update_job(db, run_id=run_id, status="running", counts=counts)
                                emit_event(
                                    db,
                                    org_id=org_id,
                                    run_id=run_id,
                                    stage="selected",
                                    asin=asin,
                                    detail={
                                        "title": product.get("title"),
                                        "title_zh": product.get("title_zh"),
                                        "image_url": product.get("image_url"),
                                        "price": _number(product.get("price")),
                                        "category": product.get("category"),
                                        "prescreen_score": product.get("prescreen_score"),
                                    },
                                )

                    if not pending:
                        break
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        result = future.result()
                        processed += 1
                        self._record_product_result(
                            org_id=org_id,
                            run_id=run_id,
                            result=result,
                        )
                        if (
                            ai_executor is not None
                            and result.get("verdict") == "pass"
                            and result.get("candidate_id")
                        ):
                            pending_ai.add(
                                ai_executor.submit(
                                    _process_candidate_ai_for_job,
                                    self.session_factory,
                                    org_id,
                                    run_id,
                                    str(result["candidate_id"]),
                                    selection_channel,
                                    allow_mock_fallback,
                                )
                            )
                        if log:
                            log(
                                "R-A job progress "
                                f"run_id={run_id} asin={result.get('asin')} "
                                f"verdict={result.get('verdict') or ''} "
                                f"candidate_id={result.get('candidate_id') or ''} "
                                f"error={result.get('error') or ''}"
                            )
                while pending_ai:
                    self._record_finished_ai_jobs(
                        org_id=org_id,
                        run_id=run_id,
                        pending_ai=pending_ai,
                        log=log,
                        block=True,
                    )
            finally:
                if ai_executor is not None:
                    ai_executor.shutdown(wait=True)
        return {"processed": processed, "yielded": was_yielded}

    def _record_product_result(
        self,
        *,
        org_id: str,
        run_id: str,
        result: dict[str, object],
    ) -> None:
        with self.session_factory() as db:
            with _without_org_data_isolation():
                row = _load_job_row(db, org_id=org_id, run_id=run_id)
                counts = _dict_value(row.get("counts") if row else {})
                if result.get("deferred"):
                    # 顺延产品不计入 processed：让"全员顺延"的空转 run 触发冷却。
                    counts["image_deferred"] = int(counts.get("image_deferred") or 0) + 1
                    if int(counts["image_deferred"]) >= _max_deferred_per_run():
                        # 顺延成灾 = 词搜和图搜今天都指望不上，整体歇到明天。
                        counts["quota_exhausted"] = True
                        warnings = list(counts.get("warnings") or [])
                        warnings.append(
                            "顺延产品过多：今日图搜额度已尽且词搜不可用，任务暂停到明天。"
                        )
                        counts["warnings"] = warnings[-10:]
                else:
                    counts["processed_products"] = int(counts.get("processed_products") or 0) + 1
                if result.get("verdict") == "prescreen_cut":
                    counts["prescreen_cut"] = int(counts.get("prescreen_cut") or 0) + 1
                elif result.get("prescreen_verdict") in {"keep", "hold"}:
                    counts["prescreen_pass"] = int(counts.get("prescreen_pass") or 0) + 1
                if result.get("error"):
                    warnings = list(counts.get("warnings") or [])
                    warnings.append(f"{result.get('asin')}: {result.get('error')}")
                    counts["warnings"] = warnings[-10:]
                    if result.get("fatal"):
                        counts["fatal_provider_error"] = True
                    if result.get("quota_exhausted"):
                        counts["quota_exhausted"] = True
                elif result.get("warnings"):
                    warnings = list(counts.get("warnings") or [])
                    for warning in result.get("warnings") or []:
                        warnings.append(str(warning))
                    counts["warnings"] = warnings[-10:]
                live_counts = _live_counts(db, org_id=org_id, run_id=run_id)
                counts.update(live_counts)
                _update_job(db, run_id=run_id, status="running", counts=counts)

    def _record_finished_ai_jobs(
        self,
        *,
        org_id: str,
        run_id: str,
        pending_ai: set[Any],
        log: Callable[[str], None] | None,
        block: bool = False,
    ) -> None:
        if not pending_ai:
            return
        timeout = None if block else 0
        done, remaining = wait(
            pending_ai,
            timeout=timeout,
            return_when=FIRST_COMPLETED,
        )
        if not done:
            return
        pending_ai.clear()
        pending_ai.update(remaining)
        for future in done:
            result = future.result()
            self._record_ai_result(org_id=org_id, run_id=run_id, result=result)
            if log:
                log(
                    "R-A AI progress "
                    f"run_id={run_id} candidate_id={result.get('candidate_id') or ''} "
                    f"error={result.get('error') or ''}"
                )

    def _record_ai_result(
        self,
        *,
        org_id: str,
        run_id: str,
        result: dict[str, object],
    ) -> None:
        with self.session_factory() as db:
            with _without_org_data_isolation():
                row = _load_job_row(db, org_id=org_id, run_id=run_id)
                counts = _dict_value(row.get("counts") if row else {})
                if result.get("error"):
                    warnings = list(counts.get("warnings") or [])
                    warnings.append(
                        f"AI {result.get('candidate_id') or ''}: {result.get('error')}"
                    )
                    counts["warnings"] = warnings[-10:]
                    if result.get("fatal"):
                        counts["fatal_provider_error"] = True
                else:
                    counts.update(_dict_value(result.get("counts")))
                counts.update(_live_counts(db, org_id=org_id, run_id=run_id))
                _update_job(db, run_id=run_id, status="running", counts=counts)


def _deferred_asins_today(db: Session, *, org_id: str) -> set[str]:
    """今天因图搜额度耗尽而顺延的 ASIN（明天预算刷新后自动重新入场）。"""
    try:
        rows = db.execute(
            text(
                """
                SELECT DISTINCT UPPER(asin) AS asin
                FROM ra_run_events
                WHERE org_id = :org_id
                  AND verdict = 'deferred'
                  AND created_at::date = CURRENT_DATE
                  AND asin IS NOT NULL
                """
            ),
            {"org_id": org_id},
        ).mappings()
        return {str(row["asin"]) for row in rows}
    except Exception:
        db.rollback()
        return set()


def _order_by_prescreen_score(
    db: Session,
    *,
    org_id: str,
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """存量夜扫打好的分数用于排队：好产品优先花今天的付费额度。"""
    if not products:
        return products
    try:
        scores = load_prescreen_scores(
            db,
            org_id=org_id,
            asins=[str(product.get("asin") or "") for product in products],
        )
    except Exception:
        db.rollback()
        return products
    for product in products:
        asin = str(product.get("asin") or "").strip().upper()
        row = scores.get(asin) or {}
        product["prescreen_score"] = row.get("score")
        product["prescreen_verdict"] = row.get("verdict")
    return sorted(
        products,
        key=lambda product: (
            int(product.get("prescreen_score") or -1),
            int(product.get("match_score") or 0),
        ),
        reverse=True,
    )


def _process_product_for_job(
    session_factory: sessionmaker[Session],
    org_id: str,
    run_id: str,
    asin: str,
    supplier_limit: int,
    exchange_rate: Decimal,
    min_gross_margin: Decimal | None,
    product: dict[str, Any] | None = None,
) -> dict[str, object]:
    try:
        # ① DeepSeek 量化初筛：便宜的第一道闸，先于任何付费调用。
        mode = prescreen_mode()
        prescreen_result: dict[str, Any] | None = None
        if mode != "off" and product:
            try:
                with session_factory() as db:
                    with _without_org_data_isolation():
                        prescreen_result = run_prescreen_for_product(
                            db,
                            org_id=org_id,
                            product=product,
                            run_id=run_id,
                        )
                        emit_event(
                            db,
                            org_id=org_id,
                            run_id=run_id,
                            stage="prescreen",
                            asin=asin,
                            verdict=str(prescreen_result.get("verdict") or ""),
                            detail={
                                "score": prescreen_result.get("score"),
                                "reason": prescreen_result.get("reason"),
                                "channel_guess": prescreen_result.get("channel_guess"),
                                "cached": bool(prescreen_result.get("cached")),
                                "mode": mode,
                            },
                        )
                        if (
                            mode == "enforce"
                            and str(prescreen_result.get("verdict") or "") == "cut"
                        ):
                            _mark_rw_profit_status(
                                db,
                                asin=asin,
                                status="prescreen_cut",
                                run_id=run_id,
                                candidate_id="",
                                reason=str(prescreen_result.get("reason") or ""),
                                snapshot=None,
                            )
                            return {
                                "asin": asin,
                                "verdict": "prescreen_cut",
                                "prescreen_verdict": "cut",
                                "warnings": [],
                            }
            except Exception as prescreen_exc:  # 初筛失败绝不拦截产品。
                prescreen_result = {
                    "verdict": "hold",
                    "reason": f"初筛异常，按放行处理：{prescreen_exc}",
                }

        # ② 1688 图搜（花额度）→ ③ 利润硬门。
        with session_factory() as db:
            with _without_org_data_isolation():
                discovery = discover_1688_supplier_offers(
                    db,
                    org_id=org_id,
                    run_id=run_id,
                    asin=asin,
                    result_limit=supplier_limit,
                    auto_calculate=True,
                    exchange_rate_usd_cny=exchange_rate,
                    min_gross_margin=min_gross_margin,
                )
                verdict = _profit_verdict_from_discovery(discovery)
                discovery_counts = _dict_value(discovery.get("counts"))
                emit_event(
                    db,
                    org_id=org_id,
                    run_id=run_id,
                    stage="supplier_search",
                    asin=asin,
                    candidate_id=str(discovery.get("candidate_id") or "") or None,
                    verdict="complete",
                    detail={
                        "candidate_offers": discovery_counts.get("candidate_offers"),
                        "priced_offers": discovery_counts.get("priced_offers"),
                        "searches": discovery_counts.get("searches"),
                        "search_strategy": discovery_counts.get("search_strategy"),
                    },
                )
                if verdict.get("status"):
                    snapshot = verdict.get("snapshot") or {}
                    emit_event(
                        db,
                        org_id=org_id,
                        run_id=run_id,
                        stage="profit_gate",
                        asin=asin,
                        candidate_id=str(discovery.get("candidate_id") or "") or None,
                        verdict=str(verdict["status"]),
                        detail={
                            "reason": verdict.get("reason"),
                            "gross_margin": _number(
                                snapshot.get("gross_margin")
                                if isinstance(snapshot, dict)
                                else None
                            ),
                        },
                    )
                    _mark_rw_profit_status(
                        db,
                        asin=asin,
                        status=str(verdict["status"]),
                        run_id=run_id,
                        candidate_id=str(discovery.get("candidate_id") or ""),
                        reason=str(verdict.get("reason") or ""),
                        snapshot=verdict.get("snapshot"),
                    )
        warnings = list(discovery.get("warnings") or [])
        if verdict.get("status") == "quantity_pending" and verdict.get("reason"):
            warnings.append(str(verdict.get("reason")))
        return {
            "asin": asin,
            "candidate_id": str(discovery.get("candidate_id") or ""),
            "counts": discovery.get("counts"),
            "verdict": verdict.get("status"),
            "prescreen_verdict": (
                str(prescreen_result.get("verdict") or "") if prescreen_result else None
            ),
            "warnings": warnings,
        }
    except RAQuotaExhaustedError as exc:
        from r_system_v2.ra.supplier_discovery import _supplier_search_strategy

        if (
            getattr(exc, "provider", "")
            in {PROVIDER_1688_IMAGE_SEARCH, PROVIDER_1688_CPS_IMAGE_SEARCH}
            and _supplier_search_strategy() == "keyword_first"
        ):
            # 词搜优先时代：图搜额度尽只影响"词搜确认不了"的产品——
            # 该产品顺延明天（不标记 ra_profit 状态），流水线继续跑其它产品。
            try:
                with session_factory() as db:
                    with _without_org_data_isolation():
                        emit_event(
                            db,
                            org_id=org_id,
                            run_id=run_id,
                            stage="profit_gate",
                            asin=asin,
                            verdict="deferred",
                            detail={"reason": "词搜未确认同款且今日图搜额度已尽，顺延明天重试。"},
                        )
            except Exception:
                pass
            return {
                "asin": asin,
                "verdict": "image_budget_deferred",
                "deferred": True,
                "warnings": [],
            }
        return {"asin": asin, "error": str(exc), "quota_exhausted": True}
    except Exception as exc:  # pragma: no cover - external provider dependent.
        message = str(exc)
        return {"asin": asin, "error": message, "fatal": _is_fatal_supplier_error(message)}


def _process_candidate_ai_for_job(
    session_factory: sessionmaker[Session],
    org_id: str,
    run_id: str,
    candidate_id: str,
    selection_channel: str,
    allow_mock_fallback: bool = True,
) -> dict[str, object]:
    try:
        with session_factory() as db:
            with _without_org_data_isolation():
                result = run_ai_selection_for_candidate(
                    db,
                    org_id=org_id,
                    run_id=run_id,
                    candidate_id=candidate_id,
                    channel=selection_channel,
                )
        return {
            "candidate_id": candidate_id,
            "counts": result.get("counts"),
        }
    except Exception as exc:  # pragma: no cover - external provider dependent.
        message = str(exc)
        # 自动巡库模式禁止 mock 静默降级：假结论混进分组比停下来更糟。
        if allow_mock_fallback and _should_fallback_to_mock_ai(message):
            try:
                with session_factory() as db:
                    with _without_org_data_isolation():
                        result = run_mock_ai_selection_for_candidate(
                            db,
                            org_id=org_id,
                            run_id=run_id,
                            candidate_id=candidate_id,
                            channel=selection_channel,
                        )
                counts = _dict_value(result.get("counts"))
                warnings = list(counts.get("warnings") or [])
                warnings.append(f"真实 AI 不可用，已对 {candidate_id} 使用 mock：{message[:180]}")
                counts["warnings"] = warnings[-10:]
                return {
                    "candidate_id": candidate_id,
                    "counts": counts,
                    "mock_fallback": True,
                }
            except Exception as mock_exc:  # pragma: no cover - fallback guardrail.
                message = f"{message}; mock fallback failed: {mock_exc}"
        return {
            "candidate_id": candidate_id,
            "error": message,
            "fatal": _is_fatal_ai_error(message),
        }


def _profit_verdict_from_discovery(discovery: dict[str, object]) -> dict[str, object]:
    profit_run = _dict_value(discovery.get("profit_run"))
    items = profit_run.get("items")
    if isinstance(items, list) and items:
        normalized_items = [_dict_value(item) for item in items if isinstance(item, dict)]
        pass_items = [item for item in normalized_items if item.get("verdict") == "pass"]
        if pass_items:
            best = _best_profit_item(pass_items)
            return {
                "status": "pass",
                "reason": "利润率达到 R-A 当前最低毛利率要求。",
                "snapshot": best,
            }
        reject_items = [item for item in normalized_items if item.get("verdict") == "reject"]
        if reject_items:
            best = _best_profit_item(reject_items)
            margin = _number(best.get("gross_margin"))
            return {
                "status": "reject",
                "reason": (
                    f"利润率 {margin:.2%} 未达到最低要求。"
                    if margin is not None
                    else "利润率未达到最低要求。"
                ),
                "snapshot": best,
            }
        blocked_items = [item for item in normalized_items if item.get("verdict") == "blocked"]
        if blocked_items:
            blocked = blocked_items[0]
            reasons = blocked.get("blocked_reasons") or []
            reason = "；".join(str(item) for item in reasons if item) or "利润计算缺少必要字段。"
            return {"status": "blocked", "reason": reason, "snapshot": blocked}

    counts = _dict_value(discovery.get("counts"))
    candidate_offers = int(counts.get("candidate_offers") or 0)
    priced_offers = int(counts.get("priced_offers") or 0)
    if candidate_offers <= 0:
        return {
            "status": "reject",
            "reason": "1688 图搜未找到可用于利润计算的同款/同类供应商。",
            "snapshot": None,
        }
    quantity_pending_reason = _quantity_pending_reason(discovery)
    if quantity_pending_reason:
        return {
            "status": "quantity_pending",
            "reason": quantity_pending_reason,
            "snapshot": None,
        }
    if priced_offers <= 0:
        return {
            "status": "reject",
            "reason": "1688 图搜找到了供应商，但没有可用成本价格。",
            "snapshot": None,
        }
    return {
        "status": "reject",
        "reason": f"可靠可定价供应商仅 {priced_offers} 条，不足正式利润计算要求。",
        "snapshot": None,
    }


def _best_profit_item(items: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(
        items,
        key=lambda item: (
            _number(item.get("gross_margin")) if _number(item.get("gross_margin")) is not None else -999,
            _number(item.get("gross_profit_usd")) if _number(item.get("gross_profit_usd")) is not None else -999,
        ),
        reverse=True,
    )[0]


def _quantity_pending_reason(discovery: dict[str, object]) -> str | None:
    offers = discovery.get("offers")
    if not isinstance(offers, list):
        return None
    reasons: list[str] = []
    for offer in offers:
        offer_dict = _dict_value(offer)
        alignment = _dict_value(offer_dict.get("supplier_alignment"))
        if str(alignment.get("match_status") or "").strip().lower() == "mismatch":
            continue
        quantity = _dict_value(alignment.get("quantity"))
        if str(quantity.get("status") or "").strip().lower() != "needs_review":
            continue
        pending_kind = str(quantity.get("pending_kind") or "").strip().lower()
        reason = str(quantity.get("reason") or alignment.get("match_reason") or "").strip()
        quantity_missing = (
            "数量" in reason
            and any(marker in reason for marker in ("未明确", "未知", "待确认", "缺少"))
            and not any(marker in reason for marker in ("不匹配", "不同", "错配", "无需"))
        )
        if pending_kind in {"amazon_quantity", "supplier_quantity"} or quantity_missing:
            if reason and reason not in reasons:
                reasons.append(reason)
    if not reasons:
        return None
    return "；".join(reasons[:3])


def _mark_rw_profit_status(
    db: Session,
    *,
    asin: str,
    status: str,
    run_id: str,
    candidate_id: str,
    reason: str,
    snapshot: object,
) -> None:
    normalized_status = (
        status
        if status in {"pass", "reject", "blocked", "quantity_pending", "prescreen_cut"}
        else "failed"
    )
    row = db.execute(
        text(
            """
            SELECT features
            FROM products_rw
            WHERE asin = :asin
            LIMIT 1
            """
        ),
        {"asin": asin},
    ).mappings().first()
    if row is None:
        return
    features = _dict_value(row.get("features"))
    snapshot_payload = _dict_value(snapshot)
    features["ra_profit"] = {
        "status": normalized_status,
        "run_id": run_id,
        "candidate_id": candidate_id or None,
        "reason": reason,
        "snapshot_id": snapshot_payload.get("snapshot_id"),
        "gross_margin": _number(snapshot_payload.get("gross_margin")),
        "gross_profit_usd": _number(snapshot_payload.get("gross_profit_usd")),
        "gross_profit_cny": _number(snapshot_payload.get("gross_profit_cny")),
        "calculated_at": datetime.now(UTC).isoformat(),
    }
    params = {
        "asin": asin,
        "features": json.dumps(features, ensure_ascii=False),
        "reason": f"R-A利润{_rw_profit_label(normalized_status)}：{reason}"[:500],
    }
    if normalized_status in {"pass", "quantity_pending"}:
        db.execute(
            text(
                f"""
                UPDATE products_rw
                SET features = {_json_bind(db, "features")},
                    updated_at = CURRENT_TIMESTAMP
                WHERE asin = :asin
                """
            ),
            params,
        )
    else:
        reason_sql = (
            ", rule_reject_reason = :reason"
            if _products_rw_has_column(db, "rule_reject_reason")
            else ""
        )
        db.execute(
            text(
                f"""
                UPDATE products_rw
                SET features = {_json_bind(db, "features")},
                    state = 'rejected',
                    updated_at = CURRENT_TIMESTAMP
                    {reason_sql}
                WHERE asin = :asin
                """
            ),
            params,
        )
    if candidate_id:
        candidate_status = {
            "pass": "profit_passed",
            "reject": "profit_rejected",
            "blocked": "profit_blocked",
            "quantity_pending": "profit_quantity_pending",
        }.get(normalized_status, "profit_pending")
        db.execute(
            text(
                """
                UPDATE ra_candidates
                SET candidate_status = :candidate_status,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :candidate_id
                """
            ),
            {"candidate_id": candidate_id, "candidate_status": candidate_status},
        )
    db.commit()


def _rw_profit_label(status: str) -> str:
    if status == "pass":
        return "通过"
    if status == "quantity_pending":
        return "数量待确认"
    if status == "blocked":
        return "阻塞"
    return "不通过"


def _is_fatal_supplier_error(message: str) -> bool:
    lowered = str(message or "").lower()
    fatal_markers = (
        "apiunsupported",
        "unsupport api",
        "signature invalid",
        "图搜 api 方法名未配置",
        "密钥尚未完整绑定",
        "缺少 app_key",
        "缺少 app_secret",
        "access_token",
    )
    return any(marker in lowered for marker in fatal_markers)


def _is_fatal_ai_error(message: str) -> bool:
    lowered = str(message or "").lower()
    fatal_markers = (
        "r-a ai key 未完整绑定",
        "key 未完整绑定",
        "密钥",
        "api key",
        "unauthorized",
        "forbidden",
        "signature",
        "401",
        "403",
    )
    return any(marker in lowered for marker in fatal_markers)


def _should_fallback_to_mock_ai(message: str) -> bool:
    lowered = str(message or "").lower()
    markers = (
        "r-a ai key 未完整绑定",
        "key 未完整绑定",
        "key 未绑定",
        "没有绑定",
        "未绑定",
        "missing api key",
        "not configured",
    )
    return any(marker in lowered for marker in markers)


def _is_idle_transaction_timeout(exc: Exception) -> bool:
    text_value = str(exc).lower()
    return (
        "idle-in-transaction timeout" in text_value
        or "idle_in_transaction_session_timeout" in text_value
    )


def _products_rw_has_column(db: Session, column_name: str) -> bool:
    try:
        dialect = db.get_bind().dialect.name
    except Exception:
        dialect = "postgresql"
    if dialect == "postgresql":
        row = db.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'products_rw' AND column_name = :column_name
                LIMIT 1
                """
            ),
            {"column_name": column_name},
        ).first()
        return row is not None
    rows = db.execute(text("PRAGMA table_info(products_rw)")).mappings().all()
    return any(str(row.get("name")) == column_name for row in rows)


def _claim_next_job(db: Session) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT run_id, org_id, filters, counts
            FROM ra_selection_runs
            WHERE channel = 'profit_auto'
              AND (
                status = 'queued'
                OR (status = 'paused' AND updated_at::date < CURRENT_DATE)
                -- worker 重启/崩溃留下的孤儿任务：10 分钟无心跳即回收续跑。
                OR (
                  status = 'running'
                  AND updated_at < CURRENT_TIMESTAMP - INTERVAL '10 minutes'
                )
              )
            -- 定向探测（手动任务）永远排在自动巡库前面。
            ORDER BY
              CASE WHEN COALESCE(filters->>'auto_cruise', 'false') = 'true'
                   THEN 1 ELSE 0 END,
              created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
    ).mappings().first()
    if row is None:
        db.rollback()
        return None
    db.execute(
        text(
            """
            UPDATE ra_selection_runs
            SET status = 'running',
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE run_id = :run_id
            """
        ),
        {"run_id": row["run_id"]},
    )
    db.commit()
    return dict(row)


def _load_job_row(db: Session, *, org_id: str, run_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT run_id, org_id, channel, status, triggered_by, filters,
                   counts, runtime_mode, started_at, finished_at, created_at, updated_at
            FROM ra_selection_runs
            WHERE org_id = :org_id AND run_id = :run_id AND channel = 'profit_auto'
            LIMIT 1
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings().first()
    return dict(row) if row is not None else None


def _load_latest_job_row(db: Session, *, org_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT run_id, org_id, channel, status, triggered_by, filters,
                   counts, runtime_mode, started_at, finished_at, created_at, updated_at
            FROM ra_selection_runs
            WHERE org_id = :org_id AND channel = 'profit_auto'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"org_id": org_id},
    ).mappings().first()
    return dict(row) if row is not None else None


def _update_job(
    db: Session,
    *,
    run_id: str,
    status: str,
    counts: dict[str, Any],
    finish: bool = False,
) -> None:
    finish_sql = ", finished_at = CURRENT_TIMESTAMP" if finish else ""
    statement = text(
        f"""
        UPDATE ra_selection_runs
        SET status = :status,
            counts = {_json_bind(db, "counts")},
            updated_at = CURRENT_TIMESTAMP
            {finish_sql}
        WHERE run_id = :run_id
        """
    )
    params = {
        "run_id": run_id,
        "status": status,
        "counts": json.dumps(counts, ensure_ascii=False),
    }
    try:
        db.execute(statement, params)
        db.commit()
    except Exception as exc:
        if not _is_idle_transaction_timeout(exc):
            raise
        db.rollback()
        db.execute(statement, params)
        db.commit()


def _job_payload(
    db: Session,
    row: dict[str, Any],
    *,
    item_page: int = 1,
    item_page_size: int = 50,
    item_search: str | None = None,
    item_category: str | None = None,
    item_verdict: str | None = None,
    item_sort: str | None = None,
    item_sort_direction: str | None = None,
) -> dict[str, object]:
    org_id = str(row["org_id"])
    run_id = str(row["run_id"])
    filters = _dict_value(row.get("filters"))
    counts = _dict_value(row.get("counts"))
    live_counts = _live_counts(db, org_id=org_id, run_id=run_id)
    counts.update({key: value for key, value in live_counts.items() if value is not None})
    items, items_page = _job_items(
        db,
        org_id=org_id,
        run_id=run_id,
        query=str(filters.get("query") or ""),
        page=item_page,
        page_size=item_page_size,
        search=item_search,
        category=item_category,
        verdict=item_verdict,
        sort=item_sort,
        sort_direction=item_sort_direction,
    )
    ai_summary = load_ai_selection_for_run(db, org_id=org_id, run_id=run_id)
    # 明细已合并进每个 item.ai_selection；顶层只保留计数，避免载荷翻倍。
    ai_selection = {
        "run_id": ai_summary.get("run_id"),
        "runtime_mode": ai_summary.get("runtime_mode"),
        "mock": ai_summary.get("mock"),
        "ai_pipeline_version": ai_summary.get("ai_pipeline_version"),
        "items": [],
        "counts": ai_summary.get("counts") or {},
    }
    db.rollback()
    quote = get_usd_cny_quote()
    return {
        "run_id": run_id,
        "status": row.get("status"),
        "runtime_mode": row.get("runtime_mode"),
        "query": filters.get("query"),
        "asin_limit": filters.get("asin_limit"),
        "supplier_limit": filters.get("supplier_limit"),
        "exchange_rate": {
            "usd_cny": float(quote.rate),
            "source": quote.source,
            "live": quote.live,
            "fetched_at": quote.fetched_at,
            "warning": quote.warning,
        },
        "matched_products": [],
        "supplier_runs": [],
        "items": items,
        "items_page": items_page,
        "counts": counts,
        "ai_selection": ai_selection,
        "formula": profit_formula_config(),
        "warnings": counts.get("warnings") or [],
        "created_at": _iso(row.get("created_at")),
        "started_at": _iso(row.get("started_at")),
        "finished_at": _iso(row.get("finished_at")),
    }


def _job_items(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    query: str,
    page: int = 1,
    page_size: int = 50,
    search: str | None = None,
    category: str | None = None,
    verdict: str | None = None,
    sort: str | None = None,
    sort_direction: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    item_page = max(1, int(page or 1))
    bounded_page_size = max(1, min(int(page_size or 50), 50))
    offset = (item_page - 1) * bounded_page_size
    candidate_page = _job_candidate_page(
        db,
        org_id=org_id,
        run_id=run_id,
        page=item_page,
        page_size=bounded_page_size,
        offset=offset,
        search=search,
        category=category,
        verdict=verdict,
        sort=sort,
        sort_direction=sort_direction,
    )
    candidate_ids = [str(row["candidate_id"]) for row in candidate_page["rows"]]
    total_items = int(candidate_page["total_items"])
    total_pages = max(1, (total_items + bounded_page_size - 1) // bounded_page_size)
    page_meta = {
        "page": item_page,
        "page_size": bounded_page_size,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_previous": item_page > 1,
        "has_next": item_page < total_pages,
        "search": candidate_page["search"],
        "category": candidate_page["category"],
        "verdict": candidate_page["verdict"],
        "sort": candidate_page["sort"],
        "sort_direction": candidate_page["sort_direction"],
    }
    if not candidate_ids:
        return [], page_meta

    suppliers_by_candidate = _supplier_options_by_candidate(
        db,
        org_id=org_id,
        run_id=run_id,
        candidate_ids=candidate_ids,
    )
    search_pages_by_candidate = _supplier_search_pages_by_candidate(
        db,
        org_id=org_id,
        run_id=run_id,
        candidate_ids=candidate_ids,
    )
    ai_by_candidate = load_ai_selection_by_candidate(db, org_id=org_id, run_id=run_id)
    snapshot_statement = (
        text(
            """
            SELECT c.id AS candidate_id,
                   s.id AS snapshot_id, s.asin, s.net_profit_usd, s.net_margin,
                   s.payload, s.created_at,
                   p.title, p.title_zh, p.image_url, p.category, p.source_query,
                   p.price, p.bsr, p.reviews, p.seller_count,
                   p.fulfillment_method, p.lithium_battery_warning,
                   p.features
            FROM ra_profit_snapshots s
            JOIN ra_candidates c ON c.id = s.candidate_id
            LEFT JOIN products_rw p ON p.asin = s.asin
            WHERE c.org_id = :org_id AND c.run_id = :run_id
              AND c.id IN :candidate_ids
            ORDER BY s.created_at DESC
            """
        )
        .bindparams(bindparam("candidate_ids", expanding=True))
    )
    snapshot_rows = list(
        db.execute(
            snapshot_statement,
            {"org_id": org_id, "run_id": run_id, "candidate_ids": candidate_ids},
        ).mappings()
    )
    snapshot_items_by_candidate: dict[str, dict[str, object]] = {}
    for row in snapshot_rows:
        candidate_id = str(row["candidate_id"])
        item = _snapshot_item_from_row(
            dict(row),
            query=query,
            suppliers=suppliers_by_candidate.get(candidate_id, []),
            supplier_search_pages=search_pages_by_candidate.get(candidate_id, []),
            ai_selection=ai_by_candidate.get(candidate_id),
        )
        existing = snapshot_items_by_candidate.get(candidate_id)
        snapshot_items_by_candidate[candidate_id] = _merge_candidate_snapshot_item(
            existing,
            item,
        )
    items = list(snapshot_items_by_candidate.values())

    pending_statement = (
        text(
            """
            SELECT c.id AS candidate_id,
                   o.id AS offer_id, COALESCE(o.asin, c.source_asin) AS asin,
                   o.supplier_name, o.supplier_url,
                   o.unit_price_cny, o.moq, o.offer_status, o.payload,
                   p.title, p.title_zh, p.image_url, p.category, p.source_query,
                   p.price, p.bsr, p.reviews, p.seller_count,
                   p.fulfillment_method, p.lithium_battery_warning,
                   p.features
            FROM ra_supplier_offers o
            JOIN ra_candidates c ON c.id = o.candidate_id
            LEFT JOIN products_rw p ON p.asin = COALESCE(o.asin, c.source_asin)
            WHERE c.org_id = :org_id
              AND c.run_id = :run_id
              AND c.id IN :candidate_ids
              AND NOT EXISTS (
                SELECT 1 FROM ra_profit_snapshots s
                WHERE s.candidate_id = c.id
              )
            ORDER BY o.updated_at DESC
            """
        )
        .bindparams(bindparam("candidate_ids", expanding=True))
    )
    pending_rows = db.execute(
        pending_statement,
        {"org_id": org_id, "run_id": run_id, "candidate_ids": candidate_ids},
    ).mappings()
    seen_pending_candidates: set[str] = set()
    for row in pending_rows:
        candidate_id = str(row["candidate_id"])
        if candidate_id in seen_pending_candidates:
            continue
        seen_pending_candidates.add(candidate_id)
        items.append(
            _pending_item_from_row(
                dict(row),
                query=query,
                suppliers=suppliers_by_candidate.get(candidate_id, []),
                supplier_search_pages=search_pages_by_candidate.get(candidate_id, []),
                ai_selection=ai_by_candidate.get(candidate_id),
            )
        )
    empty_statement = (
        text(
            """
            SELECT c.id AS candidate_id, c.source_asin AS asin, c.snapshot,
                   p.title, p.title_zh, p.image_url, p.category, p.source_query,
                   p.price, p.bsr, p.reviews, p.seller_count,
                   p.fulfillment_method, p.lithium_battery_warning,
                   p.features
            FROM ra_candidates c
            LEFT JOIN products_rw p ON p.asin = c.source_asin
            WHERE c.org_id = :org_id
              AND c.run_id = :run_id
              AND c.id IN :candidate_ids
              AND NOT EXISTS (
                SELECT 1 FROM ra_supplier_offers o
                WHERE o.candidate_id = c.id
              )
              AND NOT EXISTS (
                SELECT 1 FROM ra_profit_snapshots s
                WHERE s.candidate_id = c.id
              )
            ORDER BY c.created_at DESC
            """
        )
        .bindparams(bindparam("candidate_ids", expanding=True))
    )
    empty_candidate_rows = db.execute(
        empty_statement,
        {"org_id": org_id, "run_id": run_id, "candidate_ids": candidate_ids},
    ).mappings()
    for row in empty_candidate_rows:
        candidate_id = str(row["candidate_id"])
        items.append(
            _supplier_not_found_item_from_row(
                dict(row),
                query=query,
                supplier_search_pages=search_pages_by_candidate.get(candidate_id, []),
                ai_selection=ai_by_candidate.get(candidate_id),
            )
        )
    order = {candidate_id: index for index, candidate_id in enumerate(candidate_ids)}
    items.sort(key=lambda item: order.get(str(item.get("candidate_id") or ""), 999999))
    return items, page_meta


def _job_candidate_page(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    page: int,
    page_size: int,
    offset: int,
    search: str | None,
    category: str | None,
    verdict: str | None,
    sort: str | None,
    sort_direction: str | None,
) -> dict[str, object]:
    cleaned_search = _clean_item_filter(search)
    cleaned_category = _clean_item_filter(category)
    cleaned_verdict = _clean_verdict_filter(verdict)
    cleaned_sort = "gross_margin" if sort == "gross_margin" else "created_at"
    cleaned_direction = "asc" if sort_direction == "asc" else "desc"
    clauses = ["c.org_id = :org_id", "c.run_id = :run_id"]
    params: dict[str, object] = {
        "org_id": org_id,
        "run_id": run_id,
        "limit": page_size,
        "offset": offset,
    }
    if cleaned_search:
        params["search"] = f"%{cleaned_search.lower()}%"
        clauses.append(
            """(
              LOWER(COALESCE(c.source_asin, '')) LIKE :search OR
              LOWER(COALESCE(c.title, '')) LIKE :search OR
              LOWER(COALESCE(c.title_zh, '')) LIKE :search OR
              LOWER(COALESCE(CAST(c.snapshot AS TEXT), '')) LIKE :search OR
              LOWER(COALESCE(p.title, '')) LIKE :search OR
              LOWER(COALESCE(p.title_zh, '')) LIKE :search OR
              LOWER(COALESCE(p.source_query, '')) LIKE :search OR
              LOWER(COALESCE(p.category, '')) LIKE :search OR
              LOWER(COALESCE(p.category_path, '')) LIKE :search
            )"""
        )
    if cleaned_category:
        params["category"] = f"%{cleaned_category.lower()}%"
        clauses.append(
            """(
              LOWER(COALESCE(p.category, '')) LIKE :category OR
              LOWER(COALESCE(p.category_path, '')) LIKE :category OR
              LOWER(COALESCE(CAST(c.snapshot AS TEXT), '')) LIKE :category
            )"""
        )
    if cleaned_verdict == "pass":
        clauses.append(
            """c.candidate_status IN (
              'profit_passed',
              'ai_passed',
              'ai_rejected',
              'ai_review',
              'ai_mock_passed',
              'ai_mock_rejected',
              'ai_mock_review'
            )"""
        )
    elif cleaned_verdict == "profit_pass":
        clauses.append("c.candidate_status = 'profit_passed'")
    elif cleaned_verdict == "profit_reject":
        clauses.append(
            "c.candidate_status IN ('profit_rejected', 'profit_blocked', 'profit_quantity_pending')"
        )
    elif cleaned_verdict == "ai_pass":
        clauses.append("c.candidate_status IN ('ai_passed', 'ai_mock_passed')")
    elif cleaned_verdict == "ai_reject":
        clauses.append(
            """c.candidate_status IN (
              'ai_rejected',
              'ai_review',
              'ai_mock_rejected',
              'ai_mock_review'
            )"""
        )
    elif cleaned_verdict == "reject":
        clauses.append("c.candidate_status = 'profit_rejected'")
    elif cleaned_verdict == "pending":
        clauses.append(
            """c.candidate_status NOT IN (
              'profit_passed',
              'profit_rejected',
              'ai_passed',
              'ai_rejected',
              'ai_review',
              'ai_mock_passed',
              'ai_mock_rejected',
              'ai_mock_review'
            )"""
        )

    where_sql = " AND ".join(f"({clause})" for clause in clauses)
    margin_direction = "ASC" if cleaned_direction == "asc" else "DESC"
    created_direction = "ASC" if cleaned_direction == "asc" else "DESC"
    if cleaned_sort == "gross_margin":
        order_sql = (
            f"gross_margin_value {margin_direction} NULLS LAST, "
            "latest_activity_at DESC NULLS LAST, candidate_id ASC"
        )
    else:
        order_sql = f"latest_activity_at {created_direction} NULLS LAST, candidate_id ASC"

    rows = list(
        db.execute(
            text(
                f"""
                WITH candidate_base AS (
                  SELECT c.id AS candidate_id,
                         c.created_at,
                         GREATEST(
                           COALESCE(c.updated_at, c.created_at),
                           COALESCE(MAX(o.updated_at), c.created_at),
                           COALESCE(MAX(s.created_at), c.created_at)
                         ) AS latest_activity_at,
                         MAX(
                           COALESCE(
                             NULLIF(s.payload->>'gross_margin', '')::numeric,
                             s.net_margin
                           )
                         ) AS gross_margin_value
                  FROM ra_candidates c
                  LEFT JOIN products_rw p ON p.asin = c.source_asin
                  LEFT JOIN ra_supplier_offers o ON o.candidate_id = c.id
                  LEFT JOIN ra_profit_snapshots s ON s.candidate_id = c.id
                  WHERE {where_sql}
                  GROUP BY c.id, c.created_at, c.updated_at
                ),
                counted AS (
                  SELECT candidate_id, latest_activity_at, gross_margin_value,
                         COUNT(*) OVER () AS total_items
                  FROM candidate_base
                )
                SELECT candidate_id, latest_activity_at, gross_margin_value, total_items
                FROM counted
                ORDER BY {order_sql}
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings()
    )
    return {
        "rows": rows,
        "total_items": int(rows[0]["total_items"] or 0) if rows else 0,
        "page": page,
        "page_size": page_size,
        "search": cleaned_search,
        "category": cleaned_category,
        "verdict": cleaned_verdict,
        "sort": cleaned_sort,
        "sort_direction": cleaned_direction,
    }


def _clean_item_filter(value: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    return cleaned[:120]


def _clean_verdict_filter(value: str | None) -> str:
    cleaned = str(value or "").strip().lower()
    valid = {
        "pass",
        "reject",
        "pending",
        "profit_pass",
        "profit_reject",
        "ai_pass",
        "ai_reject",
    }
    return cleaned if cleaned in valid else "all"


def _snapshot_item_from_row(
    row: dict[str, Any],
    *,
    query: str,
    suppliers: list[dict[str, object]],
    supplier_search_pages: list[dict[str, object]],
    ai_selection: dict[str, object] | None,
) -> dict[str, object]:
    payload = _dict_value(row.get("payload"))
    supplier = _dict_value(payload.get("supplier"))
    product = _dict_value(payload.get("product"))
    item = {
        "status": "profit_calculated",
        "candidate_id": row.get("candidate_id"),
        "asin": row.get("asin"),
        "keyword": query,
        "matched_source_query": row.get("source_query"),
        "title": row.get("title") or product.get("title"),
        "title_zh": row.get("title_zh") or product.get("title_zh"),
        "category": row.get("category") or product.get("category"),
        "supplier_name": supplier.get("supplier_name"),
        "supplier_url": supplier.get("supplier_url"),
        "supplier_platform": supplier.get("supplier_platform"),
        "supplier_platform_label": supplier.get("supplier_platform_label"),
        "supplier_url_type": supplier.get("supplier_url_type"),
        "supplier_detail_url": supplier.get("supplier_detail_url") or supplier.get("supplier_url"),
        "supplier_search_url": supplier.get("supplier_search_url"),
        "unit_price_cny": _number(supplier.get("unit_price_cny")),
        "domestic_shipping_cny": _number(supplier.get("domestic_shipping_cny")),
        "supplier_total_cny": _sum_optional(
            _number(supplier.get("unit_price_cny")),
            _number(supplier.get("domestic_shipping_cny")),
        ),
        "moq": supplier.get("moq"),
        "one_piece_hint": bool(supplier.get("one_piece_hint")),
        "gross_profit_usd": _number(payload.get("gross_profit_usd") or row.get("net_profit_usd")),
        "gross_profit_cny": _number(payload.get("gross_profit_cny")),
        "gross_margin": _number(payload.get("gross_margin") or row.get("net_margin")),
        "verdict": payload.get("verdict"),
        "warnings": payload.get("warnings") or [],
        "blocked_reasons": payload.get("blocked_reasons") or [],
        "snapshot_id": row.get("snapshot_id"),
        "suppliers": suppliers,
        "supplier_search_pages": supplier_search_pages,
        "supplier_alignment": supplier.get("supplier_alignment"),
        "ai_selection": ai_selection,
    }
    item.update(_product_fields(row, product=product, query=query))
    _apply_ai_market_fields(item, ai_selection=ai_selection)
    return _apply_supplier_profit_ranges(item)


def _merge_candidate_snapshot_item(
    existing: dict[str, object] | None,
    incoming: dict[str, object],
) -> dict[str, object]:
    if existing is None:
        return _apply_supplier_profit_ranges(incoming)
    chosen = incoming if _job_item_rank(incoming) > _job_item_rank(existing) else existing
    chosen["suppliers"] = existing.get("suppliers") or incoming.get("suppliers") or []
    chosen["supplier_search_pages"] = (
        existing.get("supplier_search_pages") or incoming.get("supplier_search_pages") or []
    )
    chosen["ai_selection"] = existing.get("ai_selection") or incoming.get("ai_selection")
    return _apply_supplier_profit_ranges(chosen)


def _job_item_rank(item: dict[str, object]) -> tuple[int, float, float]:
    verdict_rank = {"pass": 3, "reject": 2, "blocked": 1}.get(
        str(item.get("verdict") or ""),
        0,
    )
    return (
        verdict_rank,
        _number(item.get("gross_margin")) or -999.0,
        _number(item.get("gross_profit_usd")) or -999.0,
    )


def _apply_supplier_profit_ranges(item: dict[str, object]) -> dict[str, object]:
    suppliers = [
        supplier
        for supplier in (item.get("suppliers") or [])
        if isinstance(supplier, dict)
    ]
    _apply_pack_badge(item, suppliers=suppliers)
    priced = [
        supplier
        for supplier in suppliers
        if _number(supplier.get("gross_margin")) is not None
    ]
    if not priced:
        return item
    margins = [_number(supplier.get("gross_margin")) for supplier in priced]
    profits_usd = [_number(supplier.get("gross_profit_usd")) for supplier in priced]
    profits_cny = [_number(supplier.get("gross_profit_cny")) for supplier in priced]
    totals = [_number(supplier.get("supplier_total_cny")) for supplier in priced]
    margins = [value for value in margins if value is not None]
    profits_usd = [value for value in profits_usd if value is not None]
    profits_cny = [value for value in profits_cny if value is not None]
    totals = [value for value in totals if value is not None]
    if margins:
        item["gross_margin_min"] = min(margins)
        item["gross_margin_max"] = max(margins)
    if profits_usd:
        item["gross_profit_usd_min"] = min(profits_usd)
        item["gross_profit_usd_max"] = max(profits_usd)
    if profits_cny:
        item["gross_profit_cny_min"] = min(profits_cny)
        item["gross_profit_cny_max"] = max(profits_cny)
    if totals:
        item["supplier_total_cny_min"] = min(totals)
        item["supplier_total_cny_max"] = max(totals)
    supplier_verdicts = {str(supplier.get("verdict") or "") for supplier in priced}
    if "pass" in supplier_verdicts:
        item["verdict"] = "pass"
    elif "reject" in supplier_verdicts:
        item["verdict"] = "reject"
    elif "blocked" in supplier_verdicts:
        item["verdict"] = "blocked"
    return item


def _apply_pack_badge(
    item: dict[str, object],
    *,
    suppliers: list[dict[str, object]],
) -> None:
    alignments: list[dict[str, Any]] = []
    item_alignment = _dict_value(item.get("supplier_alignment"))
    if item_alignment:
        alignments.append(item_alignment)
    for supplier in suppliers:
        alignment = _dict_value(supplier.get("supplier_alignment"))
        if alignment:
            alignments.append(alignment)
    for alignment in alignments:
        quantity = _dict_value(alignment.get("quantity"))
        amazon_count = _number(quantity.get("amazon_pack_count"))
        amazon_label = str(quantity.get("amazon_pack_label") or "").strip()
        supplier_label = str(quantity.get("supplier_pack_label") or "").strip()
        status = str(quantity.get("status") or "").strip().lower()
        if amazon_count and amazon_count > 1:
            item["pack_label"] = amazon_label or f"{int(amazon_count)}件装"
            item["pack_quantity"] = amazon_count
            item["supplier_pack_label"] = supplier_label or None
            item["quantity_cost_multiplier"] = _number(
                quantity.get("cost_multiplier") or alignment.get("cost_multiplier")
            )
            item["quantity_alignment_status"] = status or None
            item["quantity_alignment_reason"] = quantity.get("reason") or alignment.get("match_reason")
            return
        if status == "needs_review" and quantity.get("pending_kind") == "amazon_quantity":
            item["pack_label"] = str(quantity.get("amazon_pack_label") or "多件装待确认")
            item["pack_quantity"] = None
            item["supplier_pack_label"] = supplier_label or None
            item["quantity_cost_multiplier"] = None
            item["quantity_alignment_status"] = status
            item["quantity_alignment_reason"] = quantity.get("reason") or alignment.get("match_reason")
            return


def _pending_item_from_row(
    row: dict[str, Any],
    *,
    query: str,
    suppliers: list[dict[str, object]],
    supplier_search_pages: list[dict[str, object]],
    ai_selection: dict[str, object] | None,
) -> dict[str, object]:
    payload = _dict_value(row.get("payload"))
    unit_price = _number(row.get("unit_price_cny"))
    shipping = _number(
        payload.get("domestic_shipping_cny")
        or payload.get("shipping_fee_cny")
        or payload.get("freight_cny")
    )
    item = {
        "status": "cost_pending",
        "candidate_id": row.get("candidate_id"),
        "asin": row.get("asin"),
        "keyword": query,
        "matched_source_query": row.get("source_query"),
        "title": row.get("title"),
        "title_zh": row.get("title_zh"),
        "category": row.get("category"),
        "supplier_name": row.get("supplier_name"),
        "supplier_url": row.get("supplier_url"),
        "supplier_platform": payload.get("platform"),
        "supplier_platform_label": payload.get("platform_label"),
        "supplier_url_type": payload.get("supplier_url_type"),
        "supplier_detail_url": payload.get("supplier_detail_url") or row.get("supplier_url"),
        "supplier_search_url": payload.get("supplier_search_url")
        or payload.get("search_url")
        or payload.get("choice_page_url"),
        "unit_price_cny": unit_price,
        "domestic_shipping_cny": shipping,
        "supplier_total_cny": _sum_optional(unit_price, shipping),
        "moq": row.get("moq"),
        "one_piece_hint": bool(payload.get("one_piece_hint")),
        "gross_profit_usd": None,
        "gross_profit_cny": None,
        "gross_margin": None,
        "verdict": "pending",
        "warnings": [payload.get("crawler_warning") or "供应商成本暂未抓到，利润率未计算。"],
        "blocked_reasons": [],
        "snapshot_id": None,
        "suppliers": suppliers,
        "supplier_search_pages": supplier_search_pages,
        "supplier_alignment": payload.get("supplier_alignment"),
        "ai_selection": ai_selection,
    }
    item.update(_product_fields(row, product={}, query=query))
    _apply_ai_market_fields(item, ai_selection=ai_selection)
    _apply_pack_badge(item, suppliers=suppliers)
    return item


def _supplier_not_found_item_from_row(
    row: dict[str, Any],
    *,
    query: str,
    supplier_search_pages: list[dict[str, object]],
    ai_selection: dict[str, object] | None,
) -> dict[str, object]:
    product = _dict_value(row.get("snapshot"))
    item = {
        "status": "supplier_not_found",
        "candidate_id": row.get("candidate_id"),
        "asin": row.get("asin"),
        "keyword": query,
        "matched_source_query": row.get("source_query") or product.get("source_query"),
        "title": row.get("title") or product.get("title"),
        "title_zh": row.get("title_zh") or product.get("title_zh"),
        "category": row.get("category") or product.get("category"),
        "supplier_name": None,
        "supplier_url": None,
        "supplier_platform": None,
        "supplier_platform_label": None,
        "supplier_url_type": None,
        "supplier_detail_url": None,
        "supplier_search_url": None,
        "unit_price_cny": None,
        "domestic_shipping_cny": None,
        "supplier_total_cny": None,
        "moq": None,
        "one_piece_hint": False,
        "gross_profit_usd": None,
        "gross_profit_cny": None,
        "gross_margin": None,
        "verdict": "pending",
        "warnings": ["未找到可打开的供应商详情页链接。"],
        "blocked_reasons": [],
        "snapshot_id": None,
        "suppliers": [],
        "supplier_search_pages": supplier_search_pages,
        "ai_selection": ai_selection,
    }
    item.update(_product_fields(row, product=product, query=query))
    _apply_ai_market_fields(item, ai_selection=ai_selection)
    return item


def _supplier_options_by_candidate(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    candidate_ids: list[str] | None = None,
) -> dict[str, list[dict[str, object]]]:
    if candidate_ids is not None and not candidate_ids:
        return {}
    profit_by_offer = _profit_by_offer_id(
        db,
        org_id=org_id,
        run_id=run_id,
        candidate_ids=candidate_ids,
    )
    candidate_filter = "AND c.id IN :candidate_ids" if candidate_ids is not None else ""
    statement = text(
        f"""
        SELECT o.id AS offer_id, o.candidate_id, o.supplier_name, o.supplier_url,
               o.unit_price_cny, o.moq, o.rating, o.match_score,
               o.offer_status, o.payload
        FROM ra_supplier_offers o
        JOIN ra_candidates c ON c.id = o.candidate_id
        WHERE c.org_id = :org_id AND c.run_id = :run_id
          {candidate_filter}
        ORDER BY o.candidate_id ASC,
                 o.unit_price_cny ASC NULLS LAST,
                 o.match_score DESC NULLS LAST,
                 o.created_at ASC
        LIMIT 1000
        """
    )
    if candidate_ids is not None:
        statement = statement.bindparams(bindparam("candidate_ids", expanding=True))
    params: dict[str, object] = {"org_id": org_id, "run_id": run_id}
    if candidate_ids is not None:
        params["candidate_ids"] = candidate_ids
    rows = db.execute(statement, params).mappings()
    output: dict[str, list[dict[str, object]]] = {}
    seen_links: dict[str, set[str]] = {}
    for row in rows:
        candidate_id = str(row["candidate_id"])
        current = output.setdefault(candidate_id, [])
        if len(current) >= MAX_SUPPLIER_LIMIT:
            continue
        row_dict = dict(row)
        supplier = _supplier_option_from_row(
            row_dict,
            profit=profit_by_offer.get(str(row_dict.get("offer_id"))),
        )
        link = str(supplier.get("supplier_url") or "")
        seen = seen_links.setdefault(candidate_id, set())
        if link and link in seen:
            continue
        if link:
            seen.add(link)
        current.append(supplier)
    for suppliers in output.values():
        _mark_lowest_supplier(suppliers)
    return output


def _profit_by_offer_id(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    candidate_ids: list[str] | None = None,
) -> dict[str, dict[str, object]]:
    if candidate_ids is not None and not candidate_ids:
        return {}
    candidate_filter = "AND c.id IN :candidate_ids" if candidate_ids is not None else ""
    statement = text(
        f"""
        SELECT s.id AS snapshot_id, s.payload, s.net_profit_usd, s.net_margin
        FROM ra_profit_snapshots s
        JOIN ra_candidates c ON c.id = s.candidate_id
        WHERE c.org_id = :org_id AND c.run_id = :run_id
          {candidate_filter}
        ORDER BY s.created_at DESC
        LIMIT 1000
        """
    )
    if candidate_ids is not None:
        statement = statement.bindparams(bindparam("candidate_ids", expanding=True))
    params: dict[str, object] = {"org_id": org_id, "run_id": run_id}
    if candidate_ids is not None:
        params["candidate_ids"] = candidate_ids
    rows = db.execute(statement, params).mappings()
    output: dict[str, dict[str, object]] = {}
    for row in rows:
        payload = _dict_value(row.get("payload"))
        supplier = _dict_value(payload.get("supplier"))
        offer_id = str(supplier.get("offer_id") or "")
        if not offer_id or offer_id in output:
            continue
        output[offer_id] = {
            "snapshot_id": row.get("snapshot_id"),
            "gross_margin": _number(payload.get("gross_margin") or row.get("net_margin")),
            "gross_profit_usd": _number(
                payload.get("gross_profit_usd") or row.get("net_profit_usd")
            ),
            "gross_profit_cny": _number(payload.get("gross_profit_cny")),
            "verdict": payload.get("verdict"),
            "warnings": payload.get("warnings") or [],
            "blocked_reasons": payload.get("blocked_reasons") or [],
        }
    return output


def _mark_lowest_supplier(suppliers: list[dict[str, object]]) -> None:
    priced = [
        (index, _number(supplier.get("supplier_total_cny")) or _number(supplier.get("unit_price_cny")))
        for index, supplier in enumerate(suppliers)
    ]
    priced = [(index, value) for index, value in priced if value is not None]
    if not priced:
        return
    lowest_index = min(priced, key=lambda item: item[1])[0]
    for index, supplier in enumerate(suppliers):
        supplier["is_lowest_price"] = index == lowest_index


def _supplier_search_pages_by_candidate(
    db: Session,
    *,
    org_id: str,
    run_id: str,
    candidate_ids: list[str] | None = None,
) -> dict[str, list[dict[str, object]]]:
    if candidate_ids is not None and not candidate_ids:
        return {}
    candidate_filter = "AND c.id IN :candidate_ids" if candidate_ids is not None else ""
    statement = text(
        f"""
        SELECT s.candidate_id, s.query, s.status, s.result_count, s.payload
        FROM ra_supplier_searches s
        JOIN ra_candidates c ON c.id = s.candidate_id
        WHERE c.org_id = :org_id AND c.run_id = :run_id
          {candidate_filter}
        ORDER BY s.created_at ASC
        LIMIT 2000
        """
    )
    if candidate_ids is not None:
        statement = statement.bindparams(bindparam("candidate_ids", expanding=True))
    params: dict[str, object] = {"org_id": org_id, "run_id": run_id}
    if candidate_ids is not None:
        params["candidate_ids"] = candidate_ids
    rows = db.execute(statement, params).mappings()
    output: dict[str, list[dict[str, object]]] = {}
    seen: dict[str, set[str]] = {}
    for row in rows:
        candidate_id = str(row["candidate_id"])
        payload = _dict_value(row.get("payload"))
        search_url = payload.get("search_url")
        if not search_url:
            continue
        key = f"{payload.get('platform')}::{search_url}"
        candidate_seen = seen.setdefault(candidate_id, set())
        if key in candidate_seen:
            continue
        candidate_seen.add(key)
        pages = output.setdefault(candidate_id, [])
        if len(pages) >= 12:
            continue
        pages.append(
            {
                "query": row.get("query"),
                "platform": payload.get("platform"),
                "platform_label": payload.get("platform_label"),
                "search_url": search_url,
                "status": row.get("status"),
                "result_count": row.get("result_count"),
            }
        )
    return output


def _supplier_option_from_row(
    row: dict[str, Any],
    *,
    profit: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = _dict_value(row.get("payload"))
    unit_price = _number(row.get("unit_price_cny"))
    shipping = _number(
        payload.get("domestic_shipping_cny")
        or payload.get("shipping_fee_cny")
        or payload.get("freight_cny")
    )
    profit = profit or {}
    return {
        "offer_id": row.get("offer_id"),
        "supplier_name": row.get("supplier_name"),
        "supplier_title": payload.get("title"),
        "supplier_url": _canonical_supplier_url(
            row.get("supplier_url"),
            platform=str(payload.get("platform") or ""),
        ),
        "supplier_platform": payload.get("platform"),
        "supplier_platform_label": payload.get("platform_label"),
        "supplier_url_type": payload.get("supplier_url_type"),
        "supplier_detail_url": _canonical_supplier_url(
            payload.get("supplier_detail_url") or row.get("supplier_url"),
            platform=str(payload.get("platform") or ""),
        ),
        "supplier_search_url": payload.get("supplier_search_url")
        or payload.get("search_url")
        or payload.get("choice_page_url"),
        "unit_price_cny": unit_price,
        "domestic_shipping_cny": shipping,
        "supplier_total_cny": _sum_optional(unit_price, shipping),
        "moq": row.get("moq"),
        "rating": _number(row.get("rating")),
        "match_score": row.get("match_score"),
        "offer_status": row.get("offer_status"),
        "verdict": profit.get("verdict"),
        "gross_margin": profit.get("gross_margin"),
        "gross_profit_usd": profit.get("gross_profit_usd"),
        "gross_profit_cny": profit.get("gross_profit_cny"),
        "snapshot_id": profit.get("snapshot_id"),
        "profit_warnings": profit.get("warnings") or [],
        "profit_blocked_reasons": profit.get("blocked_reasons") or [],
        "is_lowest_price": False,
        "crawler_status": payload.get("crawler_status"),
        "one_piece_hint": bool(payload.get("one_piece_hint")),
        "supplier_alignment": payload.get("supplier_alignment"),
        "match_reason": _dict_value(payload.get("supplier_alignment")).get("match_reason"),
        "shipping_notice": payload.get("shipping_notice")
        or payload.get("freight_notice")
        or payload.get("shipping_text"),
    }


def _product_fields(
    row: dict[str, Any],
    *,
    product: dict[str, Any],
    query: str,
) -> dict[str, object]:
    asin = row.get("asin") or product.get("asin")
    features = _dict_value(row.get("features") or product.get("features"))
    image_url = row.get("image_url") or product.get("image_url")
    candidates = product_image_candidates(
        asin=str(asin or ""),
        image_url=str(image_url) if image_url else None,
        features=features,
    )
    title = row.get("title") or product.get("title")
    relevance = classify_product_relevance(query, {**product, **row})
    lithium_value = row.get("lithium_battery_warning")
    if lithium_value is None:
        lithium_value = features.get("lithium_battery_warning")
    amazon_price = _number(
        row.get("price")
        or product.get("price")
        or product.get("amazon_price_usd")
        or product.get("sell_price_usd")
    )
    monthly_sales = _number(features.get("monthly_sales_value") or features.get("monthly_sales"))
    monthly_sales_estimate = _number(features.get("monthly_sales_estimate"))
    amazon_pack_count = _number(features.get("amazon_pack_count"))
    amazon_pack_label = str(features.get("amazon_pack_label") or "").strip() or None
    amazon_pack_requires_alignment = bool(features.get("amazon_pack_requires_alignment"))
    return {
        "image_url": primary_product_image_url(
            asin=str(asin or ""),
            image_url=str(image_url) if image_url else None,
            features=features,
        ),
        "image_candidates": candidates,
        "product_keyword": _keyword_from_original_title(title),
        "amazon_price_usd": amazon_price,
        "sell_price_usd": amazon_price,
        "monthly_sales": monthly_sales,
        "monthly_sales_estimate": monthly_sales_estimate,
        "monthly_sales_estimate_min": _number(features.get("monthly_sales_estimate_min")),
        "monthly_sales_estimate_max": _number(features.get("monthly_sales_estimate_max")),
        "monthly_sales_confidence": features.get("monthly_sales_confidence"),
        "monthly_sales_source": features.get("monthly_sales_value_source")
        or features.get("monthly_sales_source")
        or features.get("monthly_sales_estimate_source"),
        "monthly_sales_raw": _number(features.get("monthly_sales_raw") or features.get("monthly_sales")),
        "monthly_sales_data_conflict": bool(features.get("monthly_sales_data_conflict")),
        "bsr": _number(row.get("bsr") or product.get("bsr")),
        "reviews": _number(row.get("reviews") or product.get("reviews")),
        "seller_count": None,
        "market_seller_count_est": None,
        "market_brand_count_est": None,
        "fulfillment_method": row.get("fulfillment_method")
        or features.get("fulfillment_method"),
        "lithium_battery_warning": bool(lithium_value),
        "fba_fee_usd": _number(features.get("fba_fee_usd")),
        "package_weight_g": _number(
            features.get("package_weight_g") or features.get("item_weight_g")
        ),
        "package_length_mm": _number(
            features.get("package_length_mm") or features.get("item_length_mm")
        ),
        "package_width_mm": _number(
            features.get("package_width_mm") or features.get("item_width_mm")
        ),
        "package_height_mm": _number(
            features.get("package_height_mm") or features.get("item_height_mm")
        ),
        "weight_label": _weight_label(features),
        "dimensions_label": _dimensions_label(features),
        "pack_label": amazon_pack_label
        if amazon_pack_count and amazon_pack_count > 1
        else ("多件装待确认" if amazon_pack_requires_alignment else None),
        "pack_quantity": amazon_pack_count if amazon_pack_count and amazon_pack_count > 1 else None,
        "quantity_alignment_status": "amazon_pack_resolved"
        if amazon_pack_count and amazon_pack_count > 1
        else ("needs_review" if amazon_pack_requires_alignment else None),
        "quantity_alignment_reason": (
            f"亚马逊包装数量来自 {features.get('amazon_pack_source') or 'R-W Keepa 结构化字段'}。"
            if amazon_pack_count and amazon_pack_count > 1
            else None
        ),
        **relevance.to_product_fields(),
    }


def _apply_ai_market_fields(
    item: dict[str, object],
    *,
    ai_selection: dict[str, object] | None,
) -> None:
    """Expose Rainforest market-level competition fields; never use ASIN offer count."""
    if not ai_selection:
        return
    competition = _dict_value(ai_selection.get("competition"))
    market_seller_count = _number(competition.get("market_seller_count_est"))
    market_brand_count = _number(competition.get("market_brand_count_est"))
    if market_seller_count is not None:
        item["market_seller_count_est"] = market_seller_count
        item["seller_count"] = market_seller_count
    if market_brand_count is not None:
        item["market_brand_count_est"] = market_brand_count
    if "competition_data_valid" in competition:
        item["competition_data_valid"] = bool(competition.get("competition_data_valid"))
    if competition.get("competition_invalid_reason"):
        item["competition_invalid_reason"] = competition.get("competition_invalid_reason")
    if competition.get("keyword"):
        item["competition_keyword"] = competition.get("keyword")
    if competition.get("keyword_source"):
        item["competition_keyword_source"] = competition.get("keyword_source")


def _canonical_1688_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if "login.1688.com" in lowered:
        return None
    match = re.search(r"/offer/([0-9]{6,})", cleaned)
    if not match:
        match = re.search(r"(?:offerId|offer_id|id)=([0-9]{6,})", cleaned)
    if match:
        return f"https://detail.1688.com/offer/{match.group(1)}.html"
    if "1688.com" in lowered and "/offer/" in lowered:
        return cleaned
    return None


def _canonical_supplier_url(value: Any, *, platform: str) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if platform == "1688" or not platform:
        canonical_1688 = _canonical_1688_url(cleaned)
        if canonical_1688:
            return canonical_1688
    lowered = cleaned.lower()
    if "login.1688.com" in lowered:
        return None
    if not cleaned.startswith(("http://", "https://")):
        return None
    return cleaned


def _keyword_from_original_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return None
    first_phrase = re.split(r"[,，|;/]", cleaned, maxsplit=1)[0].strip()
    words = first_phrase.split()
    if len(words) > 10:
        first_phrase = " ".join(words[:10])
    return first_phrase[:120] or None


def _weight_label(features: dict[str, Any]) -> str | None:
    grams = _number(features.get("package_weight_g") or features.get("item_weight_g"))
    if grams is None:
        kilograms = _number(features.get("package_weight_kg") or features.get("item_weight_kg"))
        return f"{kilograms:.2f} kg" if kilograms is not None else None
    if grams >= 1000:
        return f"{grams / 1000:.2f} kg"
    return f"{grams:.0f} g"


def _dimensions_label(features: dict[str, Any]) -> str | None:
    values = [
        _dimension_cm(features, "length"),
        _dimension_cm(features, "width"),
        _dimension_cm(features, "height"),
    ]
    if any(value is None for value in values):
        return None
    return " x ".join(f"{value:.1f}" for value in values if value is not None) + " cm"


def _dimension_cm(features: dict[str, Any], dimension: str) -> float | None:
    mm = _number(
        features.get(f"package_{dimension}_mm")
        or features.get(f"item_{dimension}_mm")
    )
    if mm is not None:
        return mm / 10
    return _number(
        features.get(f"package_{dimension}_cm")
        or features.get(f"item_{dimension}_cm")
    )


def _live_counts(db: Session, *, org_id: str, run_id: str) -> dict[str, int]:
    row = db.execute(
        text(
            """
            SELECT
              COUNT(DISTINCT c.source_asin) AS candidate_products,
              COUNT(DISTINCT o.id) AS candidate_offers,
              COUNT(DISTINCT o.id) FILTER (WHERE o.unit_price_cny IS NOT NULL) AS priced_offers,
              COUNT(DISTINCT s.id) AS profit_snapshots,
              COUNT(DISTINCT c.source_asin) FILTER (
                WHERE c.candidate_status IN (
                  'profit_passed',
                  'ai_passed',
                  'ai_rejected',
                  'ai_review',
                  'ai_mock_passed',
                  'ai_mock_rejected',
                  'ai_mock_review'
                )
              ) AS profit_pass,
              COUNT(DISTINCT c.source_asin) FILTER (WHERE c.candidate_status = 'profit_rejected') AS profit_reject,
              COUNT(DISTINCT c.source_asin) FILTER (WHERE c.candidate_status = 'profit_blocked') AS profit_blocked,
              COUNT(DISTINCT c.source_asin) FILTER (WHERE c.candidate_status = 'profit_quantity_pending') AS profit_quantity_pending
            FROM ra_candidates c
            LEFT JOIN ra_supplier_offers o ON o.candidate_id = c.id
            LEFT JOIN ra_profit_snapshots s ON s.candidate_id = c.id
            WHERE c.org_id = :org_id AND c.run_id = :run_id
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings().first()
    return {
        "candidate_products": int(row["candidate_products"] or 0) if row else 0,
        "candidate_offers": int(row["candidate_offers"] or 0) if row else 0,
        "priced_offers": int(row["priced_offers"] or 0) if row else 0,
        "profit_snapshots": int(row["profit_snapshots"] or 0) if row else 0,
        "profit_pass": int(row["profit_pass"] or 0) if row else 0,
        "profit_reject": int(row["profit_reject"] or 0) if row else 0,
        "profit_blocked": int(row["profit_blocked"] or 0) if row else 0,
        "profit_quantity_pending": int(row["profit_quantity_pending"] or 0) if row else 0,
    }


def _initial_counts(filters: dict[str, Any]) -> dict[str, object]:
    return {
        "requested_asin_limit": filters.get("asin_limit"),
        "supplier_limit": filters.get("supplier_limit"),
        "target_profit_pass": filters.get("target_profit_pass") or _target_profit_pass(),
        "max_products_per_job": filters.get("max_products_per_job") or _max_products_per_job(),
        "worker_concurrency": _worker_concurrency(None),
        "matched_products": 0,
        "selected_products": 0,
        "processed_products": 0,
        "candidate_offers": 0,
        "priced_offers": 0,
        "profit_snapshots": 0,
        "profit_pass": 0,
        "profit_reject": 0,
        "profit_blocked": 0,
        "profit_quantity_pending": 0,
        "ai_candidates": 0,
        "ai_evaluations": 0,
        "ai_pass": 0,
        "ai_reject": 0,
        "ai_review": 0,
        "final_decisions": 0,
        "reports": 0,
        "real_ai_enabled": bool(filters.get("run_ai_chain", filters.get("run_ai_mock")) is not False),
        "ai_pipeline_version": None,
        "rw_empty_result": False,
        "empty_reason": None,
        "empty_recommendation": None,
        "fatal_provider_error": False,
        "warnings": [],
    }


def _no_rw_product_notice(query: str) -> dict[str, str]:
    cleaned_query = str(query or "").strip() or "该关键词/类目"
    reason = f"R-W 仓库中暂无“{cleaned_query}”相关产品。"
    recommendation = (
        "请先到 R-W 仓库的类目设置中选择相关类目，等待 Keepa 自动抓取后，"
        "再回到 R-A 重新开始利润分析。"
    )
    return {
        "reason": reason,
        "recommendation": recommendation,
        "message": f"{reason}{recommendation}",
    }


def _bounded_asin_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_JOB_ASIN_LIMIT
    return max(1, min(parsed, MAX_ASIN_LIMIT))


def _target_profit_pass(value: Any | None = None) -> int:
    if value is None:
        value = os.getenv("RA_AUTO_PROFIT_TARGET_PASS")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_TARGET_PROFIT_PASS
    return max(1, min(parsed, 50))


def _max_deferred_per_run() -> int:
    try:
        return max(5, min(int(os.getenv("RA_MAX_DEFERRED_PER_RUN", "40")), 500))
    except ValueError:
        return 40


def _max_products_per_job(value: Any | None = None) -> int:
    if value is None:
        value = os.getenv("RA_AUTO_PROFIT_MAX_PRODUCTS")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_MAX_PRODUCTS_PER_JOB
    return max(DEFAULT_JOB_ASIN_LIMIT, min(parsed, 2000))


def _bounded_supplier_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_SUPPLIER_LIMIT
    return max(3, min(parsed, MAX_SUPPLIER_LIMIT))


def _selection_channel(value: Any) -> str:
    normalized = str(value or "amazon").strip().lower().replace("-", "_")
    if normalized in {"amazon", "dtc_seo", "dtc_ad", "both"}:
        return normalized
    return "amazon"


def _worker_concurrency(value: int | None) -> int:
    configured = value or _int_env("RA_WORKER_PRODUCT_CONCURRENCY") or DEFAULT_WORKER_CONCURRENCY
    return max(1, min(configured, 8))


def _ai_worker_concurrency(value: int | None) -> int:
    configured = value or _int_env("RA_WORKER_AI_CONCURRENCY") or DEFAULT_AI_WORKER_CONCURRENCY
    return max(1, min(configured, 4))


def _int_env(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _number(value: Any) -> float | None:
    parsed = decimal_value(value)
    return float(parsed) if parsed is not None else None


def _sum_optional(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return round((left or 0) + (right or 0), 2)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return str(value)


def _without_org_data_isolation():
    from backend.app.services.data_isolation import without_org_data_isolation

    return without_org_data_isolation()
