"""Automatic R-A profit workflow driven by a keyword or category request."""

from __future__ import annotations

from decimal import Decimal
import json
import os
import re
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from r_system_v2.ra.exchange_rate import get_usd_cny_quote
from r_system_v2.ra.profit_engine import decimal_value
from r_system_v2.ra.profit_service import RAProfitError, profit_formula_config
from r_system_v2.ra.relevance import classify_product_relevance
from r_system_v2.ra.supplier_discovery import (
    RASupplierDiscoveryError,
    discover_1688_supplier_offers,
)
from r_system_v2.rw.product_images import product_image_candidates


DEFAULT_ASIN_LIMIT = 1
MAX_ASIN_LIMIT = 20
DEFAULT_SUPPLIER_LIMIT = 3
MAX_SUPPLIER_LIMIT = 5
DEFAULT_REQUEST_BUDGET_SECONDS = 70.0


def run_auto_profit_analysis(
    db: Session,
    *,
    org_id: str,
    query: str,
    asin_limit: int = DEFAULT_ASIN_LIMIT,
    supplier_limit: int = DEFAULT_SUPPLIER_LIMIT,
    min_gross_margin: Decimal | None = None,
) -> dict[str, object]:
    cleaned_query = _clean_user_query(query)
    if not cleaned_query:
        raise RAProfitError("请输入关键词或类目。")

    requested_asin_limit = max(1, min(int(asin_limit), MAX_ASIN_LIMIT))
    sync_limit = _sync_asin_limit()
    bounded_asin_limit = min(requested_asin_limit, sync_limit)
    bounded_supplier_limit = max(3, min(int(supplier_limit), MAX_SUPPLIER_LIMIT))
    deadline = time.monotonic() + _request_budget_seconds()
    quote = get_usd_cny_quote()
    products = match_rw_products_for_query(
        db,
        org_id=org_id,
        query=cleaned_query,
        limit=bounded_asin_limit,
    )
    items: list[dict[str, object]] = []
    supplier_runs: list[dict[str, object]] = []
    warnings: list[str] = []
    counts = {
        "matched_products": len(products),
        "processed_products": 0,
        "candidate_offers": 0,
        "priced_offers": 0,
        "profit_snapshots": 0,
        "profit_pass": 0,
        "profit_reject": 0,
        "profit_blocked": 0,
    }
    if requested_asin_limit > bounded_asin_limit:
        warnings.append(
            f"为避免前端请求超时，本次先处理前 {bounded_asin_limit} 个匹配 ASIN。"
        )

    for index, product in enumerate(products):
        if index > 0 and time.monotonic() >= deadline:
            warnings.append("本次自动分析达到时间预算，已返回已完成结果。")
            break
        counts["processed_products"] += 1
        asin = str(product["asin"])
        try:
            discovery = discover_1688_supplier_offers(
                db,
                org_id=org_id,
                asin=asin,
                result_limit=bounded_supplier_limit,
                auto_calculate=True,
                exchange_rate_usd_cny=quote.rate,
                min_gross_margin=min_gross_margin,
            )
        except (RAProfitError, RASupplierDiscoveryError) as exc:
            warnings.append(f"{asin}: {exc}")
            items.append(_error_item(product, keyword=cleaned_query, error=str(exc)))
            continue

        supplier_runs.append(
            {
                "asin": asin,
                "candidate_id": discovery.get("candidate_id"),
                "counts": discovery.get("counts"),
                "warnings": discovery.get("warnings") or [],
            }
        )
        discovery_counts = discovery.get("counts") or {}
        counts["candidate_offers"] += int(discovery_counts.get("candidate_offers") or 0)
        counts["priced_offers"] += int(discovery_counts.get("priced_offers") or 0)

        profit_run = discovery.get("profit_run")
        profit_items = (
            profit_run.get("items") if isinstance(profit_run, dict) else None
        )
        supplier_search_pages = _supplier_search_pages(discovery.get("searches"))
        if profit_items:
            for snapshot in profit_items:
                if not isinstance(snapshot, dict):
                    continue
                counts["profit_snapshots"] += 1
                verdict = snapshot.get("verdict")
                if verdict == "pass":
                    counts["profit_pass"] += 1
                elif verdict == "reject":
                    counts["profit_reject"] += 1
                elif verdict == "blocked":
                    counts["profit_blocked"] += 1
                items.append(
                    _snapshot_item(
                        snapshot,
                        product=product,
                        keyword=cleaned_query,
                        exchange_rate=float(quote.rate),
                        supplier_search_pages=supplier_search_pages,
                    )
                )
            continue

        offers = discovery.get("offers")
        if isinstance(offers, list) and offers:
            for offer in offers[:bounded_supplier_limit]:
                if isinstance(offer, dict):
                    items.append(
                        _pending_offer_item(
                            product,
                            offer=offer,
                            keyword=cleaned_query,
                            exchange_rate=float(quote.rate),
                            supplier_search_pages=supplier_search_pages,
                        )
                    )
        else:
            items.append(
                _no_supplier_item(
                    product,
                    keyword=cleaned_query,
                    supplier_search_pages=supplier_search_pages,
                )
            )

    return {
        "query": cleaned_query,
        "asin_limit": bounded_asin_limit,
        "supplier_limit": bounded_supplier_limit,
        "exchange_rate": {
            "usd_cny": float(quote.rate),
            "source": quote.source,
            "live": quote.live,
            "fetched_at": quote.fetched_at,
            "warning": quote.warning,
        },
        "matched_products": [
            {
                "asin": product.get("asin"),
                "title": product.get("title"),
                "title_zh": product.get("title_zh"),
                "image_url": product.get("image_url"),
                "category": product.get("category"),
                "source_query": product.get("source_query"),
                "match_score": product.get("match_score"),
                "relevance_status": product.get("relevance_status"),
                "relevance_score": product.get("relevance_score"),
                "relevance_reason": product.get("relevance_reason"),
            }
            for product in products
        ],
        "supplier_runs": supplier_runs,
        "items": items,
        "counts": counts,
        "formula": profit_formula_config(),
        "warnings": warnings,
    }


def match_rw_products_for_query(
    db: Session,
    *,
    query: str,
    limit: int,
    org_id: str | None = None,
    exclude_asins: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    cleaned_query = _clean_user_query(query)
    terms = _query_terms(cleaned_query)
    if not terms:
        return []

    search_values = _dedupe_preserve_order([cleaned_query, *terms])
    excluded = _normalized_asin_list(exclude_asins)
    params: dict[str, object] = {"scan_limit": _rw_scan_limit(limit, len(excluded))}
    if org_id:
        params["org_id"] = org_id
    excluded_set = set(excluded)
    exclude_sql = ""
    if excluded:
        placeholders: list[str] = []
        for index, asin in enumerate(excluded[:300]):
            key = f"exclude_asin_{index}"
            params[key] = asin
            placeholders.append(f":{key}")
        exclude_sql = (
            "AND UPPER(COALESCE(CAST(asin AS TEXT), '')) "
            f"NOT IN ({', '.join(placeholders)})"
        )
    clauses: list[str] = []
    for index, value in enumerate(search_values):
        key = f"q{index}"
        params[key] = f"%{value.lower()}%"
        clauses.append(
            " OR ".join(
                [
                    f"LOWER(COALESCE(CAST(source_query AS TEXT), '')) LIKE :{key}",
                    f"LOWER(COALESCE(CAST(title AS TEXT), '')) LIKE :{key}",
                    f"LOWER(COALESCE(CAST(title_zh AS TEXT), '')) LIKE :{key}",
                    f"LOWER(COALESCE(CAST(category AS TEXT), '')) LIKE :{key}",
                    f"LOWER(COALESCE(CAST(category_id AS TEXT), '')) LIKE :{key}",
                    f"LOWER(COALESCE(CAST(category_path AS TEXT), '')) LIKE :{key}",
                    f"LOWER(COALESCE(CAST(brand AS TEXT), '')) LIKE :{key}",
                ]
            )
        )

    rows = db.execute(
        text(
            f"""
            SELECT asin, marketplace, source_query, title, title_zh, image_url,
                   brand, category, category_id, category_path, price, state,
                   skill_score, features, updated_at,
                   {_last_profit_sql(org_id)}
            FROM products_rw
            WHERE COALESCE(LOWER(CAST(state AS TEXT)), '') NOT LIKE '%reject%'
              AND {_ra_profit_not_processed_sql(db)}
              {exclude_sql}
              AND ({' OR '.join(f'({clause})' for clause in clauses)})
            ORDER BY last_profit_at ASC NULLS FIRST, updated_at DESC NULLS LAST, asin ASC
            LIMIT :scan_limit
            """
        ),
        params,
    ).mappings()

    scored: list[dict[str, Any]] = []
    for row in rows:
        product = dict(row)
        asin = str(product.get("asin") or "").strip().upper()
        if asin in excluded_set:
            continue
        features = _dict_value(product.get("features"))
        if not product_image_candidates(
            asin=str(product.get("asin") or ""),
            image_url=str(product.get("image_url")) if product.get("image_url") else None,
            features=features,
        ):
            continue
        relevance = classify_product_relevance(cleaned_query, product)
        if not relevance.should_process:
            continue
        score = _product_match_score(product, cleaned_query, terms)
        if score <= 0 and relevance.score <= 0:
            continue
        product["match_score"] = score + relevance.score
        product.update(relevance.to_product_fields())
        scored.append(product)

    scored.sort(
        key=lambda product: (
            int(product.get("match_score") or 0),
            int(product.get("skill_score") or 0),
            str(product.get("updated_at") or ""),
        ),
        reverse=True,
    )
    return scored[: max(1, min(int(limit), MAX_ASIN_LIMIT))]


def select_auto_candidates(
    db: Session,
    *,
    org_id: str | None = None,
    limit: int,
    exclude_asins: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """自动巡库候选：无需关键词，直接取尚未被 R-A 处理的 R-W 产品。

    排序交给调用方（job_queue 会按 prescreen 分数二次排序），这里先按
    R-W skill 分 + 新鲜度粗排并保证有可用图片。
    """
    del org_id  # products_rw 为单组织表，保留参数以对齐调用约定。
    excluded = _normalized_asin_list(exclude_asins)
    params: dict[str, object] = {"scan_limit": _rw_scan_limit(limit, len(excluded))}
    exclude_sql = ""
    if excluded:
        placeholders: list[str] = []
        for index, asin in enumerate(excluded[:600]):
            key = f"exclude_asin_{index}"
            params[key] = asin
            placeholders.append(f":{key}")
        exclude_sql = (
            "AND UPPER(COALESCE(CAST(asin AS TEXT), '')) "
            f"NOT IN ({', '.join(placeholders)})"
        )
    rows = db.execute(
        text(
            f"""
            SELECT asin, marketplace, source_query, title, title_zh, image_url,
                   brand, category, category_id, category_path, price, state,
                   skill_score, features, updated_at,
                   {_last_profit_sql(None)}
            FROM products_rw
            WHERE COALESCE(LOWER(CAST(state AS TEXT)), '') NOT LIKE '%reject%'
              AND {_ra_profit_not_processed_sql(db)}
              {exclude_sql}
            ORDER BY skill_score DESC NULLS LAST, updated_at DESC NULLS LAST, asin ASC
            LIMIT :scan_limit
            """
        ),
        params,
    ).mappings()
    excluded_set = set(excluded)
    selected: list[dict[str, Any]] = []
    for row in rows:
        product = dict(row)
        asin = str(product.get("asin") or "").strip().upper()
        if not asin or asin in excluded_set:
            continue
        features = _dict_value(product.get("features"))
        if not product_image_candidates(
            asin=asin,
            image_url=str(product.get("image_url")) if product.get("image_url") else None,
            features=features,
        ):
            continue
        product["match_score"] = int(product.get("skill_score") or 0)
        selected.append(product)
        if len(selected) >= max(1, min(int(limit), MAX_ASIN_LIMIT)):
            break
    return selected


def _normalized_asin_list(values: set[str] | list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        asin = str(value or "").strip().upper()
        if not asin or asin in seen:
            continue
        seen.add(asin)
        normalized.append(asin)
    return normalized


def _rw_scan_limit(limit: int, excluded_count: int) -> int:
    base = max(100, min(int(limit) * 30, 300))
    if excluded_count <= 0:
        return base
    return max(base, min(base + excluded_count, 500))


def _ra_profit_not_processed_sql(db: Session) -> str:
    try:
        dialect = db.get_bind().dialect.name
    except Exception:
        dialect = "postgresql"
    if dialect == "postgresql":
        # prescreen_cut 不是死刑：30 天后允许重新进入匹配池重打分。
        # CASE 短路：绝大多数行 status 为空，直接命中 ELSE，不做时间戳转换。
        return (
            "CASE COALESCE(features->'ra_profit'->>'status', '') "
            "WHEN 'pass' THEN false "
            "WHEN 'reject' THEN false "
            "WHEN 'blocked' THEN false "
            "WHEN 'failed' THEN false "
            "WHEN 'quantity_pending' THEN false "
            "WHEN 'prescreen_cut' THEN COALESCE("
            "(features->'ra_profit'->>'calculated_at')::timestamptz, "
            "TIMESTAMPTZ 'epoch'"
            ") <= CURRENT_TIMESTAMP - INTERVAL '30 days' "
            "ELSE true "
            "END"
        )
    return (
        "COALESCE(json_extract(features, '$.ra_profit.status'), '') "
        "NOT IN ('pass', 'reject', 'blocked', 'failed', 'quantity_pending', 'prescreen_cut')"
    )


def _snapshot_item(
    snapshot: dict[str, Any],
    *,
    product: dict[str, Any],
    keyword: str,
    exchange_rate: float,
    supplier_search_pages: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    supplier = snapshot.get("supplier") if isinstance(snapshot.get("supplier"), dict) else {}
    unit_price = _float_value(supplier.get("unit_price_cny"))
    shipping = _float_value(supplier.get("domestic_shipping_cny"))
    amazon_price = _float_value(
        snapshot.get("amazon_price_usd")
        or snapshot.get("sell_price_usd")
        or product.get("price")
    )
    return {
        "status": "profit_calculated",
        "asin": snapshot.get("asin") or product.get("asin"),
        "image_url": snapshot.get("image_url") or product.get("image_url"),
        "amazon_price_usd": amazon_price,
        "sell_price_usd": amazon_price,
        "keyword": keyword,
        "matched_source_query": product.get("source_query"),
        "title": snapshot.get("title") or product.get("title"),
        "title_zh": snapshot.get("title_zh") or product.get("title_zh"),
        "category": snapshot.get("category") or product.get("category"),
        "supplier_name": supplier.get("supplier_name"),
        "supplier_url": supplier.get("supplier_url"),
        "supplier_platform": supplier.get("supplier_platform"),
        "supplier_platform_label": supplier.get("supplier_platform_label"),
        "supplier_url_type": supplier.get("supplier_url_type"),
        "supplier_detail_url": supplier.get("supplier_detail_url") or supplier.get("supplier_url"),
        "supplier_search_url": supplier.get("supplier_search_url"),
        "unit_price_cny": unit_price,
        "domestic_shipping_cny": shipping,
        "supplier_total_cny": _sum_optional(unit_price, shipping),
        "moq": supplier.get("moq"),
        "one_piece_hint": bool(supplier.get("one_piece_hint")),
        "gross_profit_usd": snapshot.get("gross_profit_usd"),
        "gross_profit_cny": snapshot.get("gross_profit_cny"),
        "gross_margin": snapshot.get("gross_margin"),
        "verdict": snapshot.get("verdict"),
        "warnings": snapshot.get("warnings") or [],
        "blocked_reasons": snapshot.get("blocked_reasons") or [],
        "exchange_rate_usd_cny": exchange_rate,
        "snapshot_id": snapshot.get("snapshot_id"),
        "supplier_search_pages": supplier_search_pages or [],
        **_relevance_fields(product, keyword),
    }


def _pending_offer_item(
    product: dict[str, Any],
    *,
    offer: dict[str, Any],
    keyword: str,
    exchange_rate: float,
    supplier_search_pages: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    unit_price = _float_value(offer.get("unit_price_cny"))
    shipping = _float_value(offer.get("domestic_shipping_cny"))
    amazon_price = _float_value(product.get("price"))
    return {
        "status": "cost_pending",
        "asin": product.get("asin"),
        "image_url": product.get("image_url"),
        "amazon_price_usd": amazon_price,
        "sell_price_usd": amazon_price,
        "keyword": keyword,
        "matched_source_query": product.get("source_query"),
        "title": product.get("title"),
        "title_zh": product.get("title_zh"),
        "category": product.get("category"),
        "supplier_name": offer.get("supplier_name"),
        "supplier_url": offer.get("supplier_url"),
        "supplier_platform": offer.get("supplier_platform"),
        "supplier_platform_label": offer.get("supplier_platform_label"),
        "supplier_url_type": offer.get("supplier_url_type"),
        "supplier_detail_url": offer.get("supplier_detail_url") or offer.get("supplier_url"),
        "supplier_search_url": offer.get("supplier_search_url"),
        "unit_price_cny": unit_price,
        "domestic_shipping_cny": shipping,
        "supplier_total_cny": _sum_optional(unit_price, shipping),
        "moq": offer.get("moq"),
        "one_piece_hint": bool(offer.get("one_piece_hint")),
        "gross_profit_usd": None,
        "gross_profit_cny": None,
        "gross_margin": None,
        "verdict": "pending",
        "warnings": [offer.get("warning") or "供应商成本暂未抓到，利润率未计算。"],
        "blocked_reasons": [],
        "exchange_rate_usd_cny": exchange_rate,
        "snapshot_id": None,
        "supplier_search_pages": supplier_search_pages or [],
        "supplier_alignment": offer.get("supplier_alignment"),
        **_relevance_fields(product, keyword),
    }


def _no_supplier_item(
    product: dict[str, Any],
    *,
    keyword: str,
    supplier_search_pages: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    amazon_price = _float_value(product.get("price"))
    return {
        "status": "supplier_not_found",
        "asin": product.get("asin"),
        "image_url": product.get("image_url"),
        "amazon_price_usd": amazon_price,
        "sell_price_usd": amazon_price,
        "keyword": keyword,
        "matched_source_query": product.get("source_query"),
        "title": product.get("title"),
        "title_zh": product.get("title_zh"),
        "category": product.get("category"),
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
        "warnings": ["Serper 没有返回可用的供应商详情页候选。"],
        "blocked_reasons": [],
        "snapshot_id": None,
        "supplier_search_pages": supplier_search_pages or [],
        **_relevance_fields(product, keyword),
    }


def _error_item(
    product: dict[str, Any],
    *,
    keyword: str,
    error: str,
) -> dict[str, object]:
    item = _no_supplier_item(product, keyword=keyword)
    item["status"] = "failed"
    item["warnings"] = [error]
    return item


def _supplier_search_pages(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    pages: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        search_url = item.get("search_url")
        if not isinstance(search_url, str) or not search_url:
            continue
        key = f"{item.get('platform')}::{search_url}"
        if key in seen:
            continue
        seen.add(key)
        pages.append(
            {
                "query": item.get("query"),
                "platform": item.get("platform"),
                "platform_label": item.get("platform_label"),
                "search_url": search_url,
                "status": item.get("status"),
                "result_count": item.get("result_count"),
            }
        )
    return pages[:12]


def _relevance_fields(product: dict[str, Any], query: str) -> dict[str, object]:
    return classify_product_relevance(query, product).to_product_fields()


def _product_match_score(
    product: dict[str, Any],
    query: str,
    terms: list[str],
) -> int:
    full_query = query.lower()
    source_fields = _joined_lower(
        product.get("source_query"),
        product.get("category"),
        product.get("category_id"),
        product.get("category_path"),
    )
    title_fields = _joined_lower(product.get("title_zh"), product.get("title"))
    brand = _joined_lower(product.get("brand"))
    score = 0
    if full_query in source_fields:
        score += 100
    if full_query in title_fields:
        score += 80
    if full_query in brand:
        score += 45
    for term in terms:
        if term in source_fields:
            score += 35
        if term in title_fields:
            score += 30
        if term in brand:
            score += 15
    return score


def _query_terms(query: str) -> list[str]:
    parts = [part.lower() for part in re.split(r"[\s,，/|]+", query) if part.strip()]
    if not parts and query:
        parts = [query.lower()]
    return _dedupe_preserve_order([part for part in parts if len(part) >= 2])


def _clean_user_query(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\s,，/|-]", " ", str(value or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:120]


def _joined_lower(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            parts.append(json.dumps(value, ensure_ascii=False))
        else:
            parts.append(str(value))
    return " ".join(parts).lower()


def _sum_optional(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return round((left or 0) + (right or 0), 2)


def _float_value(value: Any) -> float | None:
    parsed = decimal_value(value)
    return float(parsed) if parsed is not None else None


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


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _sync_asin_limit() -> int:
    configured = _int_env("RA_AUTO_PROFIT_SYNC_ASIN_LIMIT")
    if configured is None:
        return DEFAULT_ASIN_LIMIT
    return max(1, min(configured, MAX_ASIN_LIMIT))


def _request_budget_seconds() -> float:
    value = os.getenv("RA_AUTO_PROFIT_REQUEST_BUDGET_SECONDS")
    if not value:
        return DEFAULT_REQUEST_BUDGET_SECONDS
    try:
        parsed = float(value)
    except ValueError:
        return DEFAULT_REQUEST_BUDGET_SECONDS
    return max(15.0, min(parsed, 100.0))


def _int_env(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _last_profit_sql(org_id: str | None) -> str:
    del org_id
    return "NULL AS last_profit_at"
