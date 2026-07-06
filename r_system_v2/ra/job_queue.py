"""Background R-A profit job queue backed by ra_selection_runs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import Decimal
import json
import os
import re
import time
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from r_system_v2.ra.auto_profit import (
    DEFAULT_SUPPLIER_LIMIT,
    MAX_ASIN_LIMIT,
    MAX_SUPPLIER_LIMIT,
    match_rw_products_for_query,
)
from r_system_v2.ra.exchange_rate import get_usd_cny_quote
from r_system_v2.ra.profit_engine import decimal_value
from r_system_v2.ra.profit_service import _json_bind
from r_system_v2.ra.profit_service import profit_formula_config
from r_system_v2.ra.relevance import classify_product_relevance
from r_system_v2.ra.supplier_discovery import discover_1688_supplier_offers
from r_system_v2.rw.product_images import primary_product_image_url, product_image_candidates


DEFAULT_JOB_ASIN_LIMIT = 20
DEFAULT_WORKER_CONCURRENCY = 3
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
    triggered_by: str | None = None,
) -> dict[str, object]:
    cleaned_query = str(query or "").strip()
    if not cleaned_query:
        raise RAJobError("请输入关键词或类目。")

    run_id = str(uuid4())
    filters = {
        "query": cleaned_query[:120],
        "asin_limit": _bounded_asin_limit(asin_limit),
        "supplier_limit": _bounded_supplier_limit(supplier_limit),
        "min_gross_margin": _number(min_gross_margin),
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
) -> dict[str, object]:
    row = _load_job_row(db, org_id=org_id, run_id=run_id)
    if row is None:
        raise RAJobError("R-A 任务不存在。")
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
        quote = get_usd_cny_quote()

        with self.session_factory() as db:
            with _without_org_data_isolation():
                products = match_rw_products_for_query(
                    db,
                    org_id=org_id,
                    query=query,
                    limit=asin_limit,
                )
                counts = _dict_value(job.get("counts"))
                counts.update(
                    {
                        "matched_products": len(products),
                        "processed_products": 0,
                        "candidate_offers": 0,
                        "priced_offers": 0,
                        "profit_snapshots": 0,
                        "profit_pass": 0,
                        "profit_reject": 0,
                        "profit_blocked": 0,
                        "warnings": [],
                    }
                )
                _update_job(db, run_id=run_id, status="running", counts=counts)

        if not products:
            with self.session_factory() as db:
                with _without_org_data_isolation():
                    counts = _dict_value(_load_job_row(db, org_id=org_id, run_id=run_id)["counts"])
                    _update_job(db, run_id=run_id, status="completed", counts=counts, finish=True)
            return

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = [
                executor.submit(
                    _process_product_for_job,
                    self.session_factory,
                    org_id,
                    run_id,
                    str(product["asin"]),
                    supplier_limit,
                    quote.rate,
                    min_gross_margin,
                )
                for product in products
            ]
            for future in as_completed(futures):
                result = future.result()
                with self.session_factory() as db:
                    with _without_org_data_isolation():
                        row = _load_job_row(db, org_id=org_id, run_id=run_id)
                        counts = _dict_value(row.get("counts") if row else {})
                        counts["processed_products"] = int(
                            counts.get("processed_products") or 0
                        ) + 1
                        if result.get("error"):
                            warnings = list(counts.get("warnings") or [])
                            warnings.append(f"{result.get('asin')}: {result.get('error')}")
                            counts["warnings"] = warnings[-10:]
                        elif result.get("warnings"):
                            warnings = list(counts.get("warnings") or [])
                            for warning in result.get("warnings") or []:
                                warnings.append(str(warning))
                            counts["warnings"] = warnings[-10:]
                        live_counts = _live_counts(db, org_id=org_id, run_id=run_id)
                        counts.update(live_counts)
                        _update_job(db, run_id=run_id, status="running", counts=counts)
                if log:
                    log(
                        "R-A job progress "
                        f"run_id={run_id} asin={result.get('asin')} "
                        f"error={result.get('error') or ''}"
                    )

        with self.session_factory() as db:
            with _without_org_data_isolation():
                row = _load_job_row(db, org_id=org_id, run_id=run_id)
                counts = _dict_value(row.get("counts") if row else {})
                counts.update(_live_counts(db, org_id=org_id, run_id=run_id))
                final_status = "completed" if not counts.get("warnings") else "partial"
                _update_job(db, run_id=run_id, status=final_status, counts=counts, finish=True)
        if log:
            log(f"R-A job finished run_id={run_id}")


def _process_product_for_job(
    session_factory: sessionmaker[Session],
    org_id: str,
    run_id: str,
    asin: str,
    supplier_limit: int,
    exchange_rate: Decimal,
    min_gross_margin: Decimal | None,
) -> dict[str, object]:
    try:
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
        return {
            "asin": asin,
            "counts": discovery.get("counts"),
            "warnings": discovery.get("warnings") or [],
        }
    except Exception as exc:  # pragma: no cover - external provider dependent.
        return {"asin": asin, "error": str(exc)}


def _claim_next_job(db: Session) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT run_id, org_id, filters, counts
            FROM ra_selection_runs
            WHERE channel = 'profit_auto' AND status = 'queued'
            ORDER BY created_at ASC
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


def _update_job(
    db: Session,
    *,
    run_id: str,
    status: str,
    counts: dict[str, Any],
    finish: bool = False,
) -> None:
    finish_sql = ", finished_at = CURRENT_TIMESTAMP" if finish else ""
    db.execute(
        text(
            f"""
            UPDATE ra_selection_runs
            SET status = :status,
                counts = {_json_bind(db, "counts")},
                updated_at = CURRENT_TIMESTAMP
                {finish_sql}
            WHERE run_id = :run_id
            """
        ),
        {
            "run_id": run_id,
            "status": status,
            "counts": json.dumps(counts, ensure_ascii=False),
        },
    )
    db.commit()


def _job_payload(db: Session, row: dict[str, Any]) -> dict[str, object]:
    org_id = str(row["org_id"])
    run_id = str(row["run_id"])
    filters = _dict_value(row.get("filters"))
    counts = _dict_value(row.get("counts"))
    live_counts = _live_counts(db, org_id=org_id, run_id=run_id)
    counts.update({key: value for key, value in live_counts.items() if value is not None})
    items = _job_items(db, org_id=org_id, run_id=run_id, query=str(filters.get("query") or ""))
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
        "counts": counts,
        "formula": profit_formula_config(),
        "warnings": counts.get("warnings") or [],
        "created_at": _iso(row.get("created_at")),
        "started_at": _iso(row.get("started_at")),
        "finished_at": _iso(row.get("finished_at")),
    }


def _job_items(db: Session, *, org_id: str, run_id: str, query: str) -> list[dict[str, object]]:
    suppliers_by_candidate = _supplier_options_by_candidate(db, org_id=org_id, run_id=run_id)
    snapshot_rows = db.execute(
        text(
            """
            SELECT c.id AS candidate_id,
                   s.id AS snapshot_id, s.asin, s.net_profit_usd, s.net_margin,
                   s.payload, s.created_at,
                   p.title, p.title_zh, p.image_url, p.category, p.source_query,
                   p.price, p.fulfillment_method, p.lithium_battery_warning,
                   p.features
            FROM ra_profit_snapshots s
            JOIN ra_candidates c ON c.id = s.candidate_id
            LEFT JOIN products_rw p ON p.asin = s.asin
            WHERE c.org_id = :org_id AND c.run_id = :run_id
            ORDER BY s.created_at DESC
            LIMIT 500
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings()
    items = [
        _snapshot_item_from_row(
            dict(row),
            query=query,
            suppliers=suppliers_by_candidate.get(str(row["candidate_id"]), []),
        )
        for row in snapshot_rows
    ]

    pending_rows = db.execute(
        text(
            """
            SELECT c.id AS candidate_id,
                   o.id AS offer_id, COALESCE(o.asin, c.source_asin) AS asin,
                   o.supplier_name, o.supplier_url,
                   o.unit_price_cny, o.moq, o.offer_status, o.payload,
                   p.title, p.title_zh, p.image_url, p.category, p.source_query,
                   p.price, p.fulfillment_method, p.lithium_battery_warning,
                   p.features
            FROM ra_supplier_offers o
            JOIN ra_candidates c ON c.id = o.candidate_id
            LEFT JOIN products_rw p ON p.asin = COALESCE(o.asin, c.source_asin)
            WHERE c.org_id = :org_id
              AND c.run_id = :run_id
              AND NOT EXISTS (
                SELECT 1 FROM ra_profit_snapshots s
                WHERE s.candidate_id = c.id
              )
            ORDER BY o.updated_at DESC
            LIMIT 500
            """
        ),
        {"org_id": org_id, "run_id": run_id},
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
            )
        )
    empty_candidate_rows = db.execute(
        text(
            """
            SELECT c.id AS candidate_id, c.source_asin AS asin, c.snapshot,
                   p.title, p.title_zh, p.image_url, p.category, p.source_query,
                   p.price, p.fulfillment_method, p.lithium_battery_warning,
                   p.features
            FROM ra_candidates c
            LEFT JOIN products_rw p ON p.asin = c.source_asin
            WHERE c.org_id = :org_id
              AND c.run_id = :run_id
              AND NOT EXISTS (
                SELECT 1 FROM ra_supplier_offers o
                WHERE o.candidate_id = c.id
              )
              AND NOT EXISTS (
                SELECT 1 FROM ra_profit_snapshots s
                WHERE s.candidate_id = c.id
              )
            ORDER BY c.created_at DESC
            LIMIT 500
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings()
    for row in empty_candidate_rows:
        items.append(_supplier_not_found_item_from_row(dict(row), query=query))
    return items


def _snapshot_item_from_row(
    row: dict[str, Any],
    *,
    query: str,
    suppliers: list[dict[str, object]],
) -> dict[str, object]:
    payload = _dict_value(row.get("payload"))
    supplier = _dict_value(payload.get("supplier"))
    product = _dict_value(payload.get("product"))
    item = {
        "status": "profit_calculated",
        "asin": row.get("asin"),
        "keyword": query,
        "matched_source_query": row.get("source_query"),
        "title": row.get("title") or product.get("title"),
        "title_zh": row.get("title_zh") or product.get("title_zh"),
        "category": row.get("category") or product.get("category"),
        "supplier_name": supplier.get("supplier_name"),
        "supplier_url": supplier.get("supplier_url"),
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
    }
    item.update(_product_fields(row, product=product, query=query))
    return item


def _pending_item_from_row(
    row: dict[str, Any],
    *,
    query: str,
    suppliers: list[dict[str, object]],
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
        "asin": row.get("asin"),
        "keyword": query,
        "matched_source_query": row.get("source_query"),
        "title": row.get("title"),
        "title_zh": row.get("title_zh"),
        "category": row.get("category"),
        "supplier_name": row.get("supplier_name"),
        "supplier_url": row.get("supplier_url"),
        "unit_price_cny": unit_price,
        "domestic_shipping_cny": shipping,
        "supplier_total_cny": _sum_optional(unit_price, shipping),
        "moq": row.get("moq"),
        "one_piece_hint": bool(payload.get("one_piece_hint")),
        "gross_profit_usd": None,
        "gross_profit_cny": None,
        "gross_margin": None,
        "verdict": "pending",
        "warnings": [payload.get("crawler_warning") or "1688 成本暂未抓到，利润率未计算。"],
        "blocked_reasons": [],
        "snapshot_id": None,
        "suppliers": suppliers,
    }
    item.update(_product_fields(row, product={}, query=query))
    return item


def _supplier_not_found_item_from_row(row: dict[str, Any], *, query: str) -> dict[str, object]:
    product = _dict_value(row.get("snapshot"))
    item = {
        "status": "supplier_not_found",
        "asin": row.get("asin"),
        "keyword": query,
        "matched_source_query": row.get("source_query") or product.get("source_query"),
        "title": row.get("title") or product.get("title"),
        "title_zh": row.get("title_zh") or product.get("title_zh"),
        "category": row.get("category") or product.get("category"),
        "supplier_name": None,
        "supplier_url": None,
        "unit_price_cny": None,
        "domestic_shipping_cny": None,
        "supplier_total_cny": None,
        "moq": None,
        "one_piece_hint": False,
        "gross_profit_usd": None,
        "gross_profit_cny": None,
        "gross_margin": None,
        "verdict": "pending",
        "warnings": ["未找到可打开的 1688 详情页供应商链接。"],
        "blocked_reasons": [],
        "snapshot_id": None,
        "suppliers": [],
    }
    item.update(_product_fields(row, product=product, query=query))
    return item


def _supplier_options_by_candidate(
    db: Session,
    *,
    org_id: str,
    run_id: str,
) -> dict[str, list[dict[str, object]]]:
    rows = db.execute(
        text(
            """
            SELECT o.candidate_id, o.supplier_name, o.supplier_url,
                   o.unit_price_cny, o.moq, o.rating, o.match_score,
                   o.offer_status, o.payload
            FROM ra_supplier_offers o
            JOIN ra_candidates c ON c.id = o.candidate_id
            WHERE c.org_id = :org_id AND c.run_id = :run_id
            ORDER BY o.candidate_id ASC,
                     o.unit_price_cny ASC NULLS LAST,
                     o.match_score DESC NULLS LAST,
                     o.created_at ASC
            LIMIT 1000
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings()
    output: dict[str, list[dict[str, object]]] = {}
    seen_links: dict[str, set[str]] = {}
    for row in rows:
        candidate_id = str(row["candidate_id"])
        current = output.setdefault(candidate_id, [])
        if len(current) >= MAX_SUPPLIER_LIMIT:
            continue
        supplier = _supplier_option_from_row(dict(row))
        link = str(supplier.get("supplier_url") or "")
        seen = seen_links.setdefault(candidate_id, set())
        if link and link in seen:
            continue
        if link:
            seen.add(link)
        current.append(supplier)
    return output


def _supplier_option_from_row(row: dict[str, Any]) -> dict[str, object]:
    payload = _dict_value(row.get("payload"))
    unit_price = _number(row.get("unit_price_cny"))
    shipping = _number(
        payload.get("domestic_shipping_cny")
        or payload.get("shipping_fee_cny")
        or payload.get("freight_cny")
    )
    return {
        "supplier_name": row.get("supplier_name"),
        "supplier_url": _canonical_1688_url(row.get("supplier_url")),
        "unit_price_cny": unit_price,
        "domestic_shipping_cny": shipping,
        "supplier_total_cny": _sum_optional(unit_price, shipping),
        "moq": row.get("moq"),
        "rating": _number(row.get("rating")),
        "match_score": row.get("match_score"),
        "offer_status": row.get("offer_status"),
        "crawler_status": payload.get("crawler_status"),
        "one_piece_hint": bool(payload.get("one_piece_hint")),
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
    return {
        "image_url": primary_product_image_url(
            asin=str(asin or ""),
            image_url=str(image_url) if image_url else None,
            features=features,
        ),
        "image_candidates": candidates,
        "product_keyword": _keyword_from_original_title(title),
        "sell_price_usd": _number(row.get("price") or product.get("price")),
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
        **relevance.to_product_fields(),
    }


def _canonical_1688_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if "login.taobao.com" in lowered or "login.1688.com" in lowered:
        return None
    match = re.search(r"/offer/([0-9]{6,})", cleaned)
    if not match:
        match = re.search(r"(?:offerId|offer_id|id)=([0-9]{6,})", cleaned)
    if match:
        return f"https://detail.1688.com/offer/{match.group(1)}.html"
    if "1688.com" in lowered and "/offer/" in lowered:
        return cleaned
    return None


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
              COUNT(DISTINCT s.id) AS profit_snapshots
            FROM ra_candidates c
            LEFT JOIN ra_supplier_offers o ON o.candidate_id = c.id
            LEFT JOIN ra_profit_snapshots s ON s.candidate_id = c.id
            WHERE c.org_id = :org_id AND c.run_id = :run_id
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings().first()
    verdict_rows = db.execute(
        text(
            """
            SELECT s.payload
            FROM ra_profit_snapshots s
            JOIN ra_candidates c ON c.id = s.candidate_id
            WHERE c.org_id = :org_id AND c.run_id = :run_id
            """
        ),
        {"org_id": org_id, "run_id": run_id},
    ).mappings()
    verdict_counts = {"profit_pass": 0, "profit_reject": 0, "profit_blocked": 0}
    for verdict_row in verdict_rows:
        verdict = _dict_value(verdict_row.get("payload")).get("verdict")
        if verdict == "pass":
            verdict_counts["profit_pass"] += 1
        elif verdict == "reject":
            verdict_counts["profit_reject"] += 1
        elif verdict == "blocked":
            verdict_counts["profit_blocked"] += 1
    return {
        "candidate_products": int(row["candidate_products"] or 0) if row else 0,
        "candidate_offers": int(row["candidate_offers"] or 0) if row else 0,
        "priced_offers": int(row["priced_offers"] or 0) if row else 0,
        "profit_snapshots": int(row["profit_snapshots"] or 0) if row else 0,
        **verdict_counts,
    }


def _initial_counts(filters: dict[str, Any]) -> dict[str, object]:
    return {
        "requested_asin_limit": filters.get("asin_limit"),
        "supplier_limit": filters.get("supplier_limit"),
        "matched_products": 0,
        "processed_products": 0,
        "candidate_offers": 0,
        "priced_offers": 0,
        "profit_snapshots": 0,
        "profit_pass": 0,
        "profit_reject": 0,
        "profit_blocked": 0,
        "warnings": [],
    }


def _bounded_asin_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_JOB_ASIN_LIMIT
    return max(1, min(parsed, MAX_ASIN_LIMIT))


def _bounded_supplier_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_SUPPLIER_LIMIT
    return max(3, min(parsed, MAX_SUPPLIER_LIMIT))


def _worker_concurrency(value: int | None) -> int:
    configured = value or _int_env("RA_WORKER_PRODUCT_CONCURRENCY") or DEFAULT_WORKER_CONCURRENCY
    return max(1, min(configured, 6))


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
