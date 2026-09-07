"""Persistence service for R-A profit snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import os
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from r_system_v2.ra.profit_engine import (
    DEFAULT_MIN_GROSS_MARGIN,
    FIRST_MILE_CNY_PER_KG,
    FORMULA_VERSION,
    REFERRAL_FEE_RATE,
    ProfitInput,
    ProfitResult,
    calculate_us_profit,
    decimal_value,
)
from r_system_v2.ra.exchange_rate import get_usd_cny_quote
from r_system_v2.rw.product_images import primary_product_image_url, product_image_candidates


class RAProfitError(ValueError):
    pass


def profit_formula_config() -> dict[str, object]:
    quote = get_usd_cny_quote()
    return {
        "marketplace": "US",
        "formula_version": FORMULA_VERSION,
        "referral_fee_rate": float(REFERRAL_FEE_RATE),
        "seller_receipt_rate": 0.85,
        "first_mile_cny_per_kg": float(FIRST_MILE_CNY_PER_KG),
        "default_exchange_rate_usd_cny": float(quote.rate),
        "exchange_rate_source": quote.source,
        "exchange_rate_live": quote.live,
        "exchange_rate_fetched_at": quote.fetched_at,
        "exchange_rate_warning": quote.warning,
        "default_min_gross_margin": float(_min_gross_margin()),
        "volume_weight_formula": "长(cm) * 宽(cm) * 高(cm) / 6000",
        "chargeable_weight_rule": "体积重量与实际重量取较大值",
        "gross_profit_formula": (
            "售价 * 0.85 - 头程运费 - FBA费用 - 供应商产品成本 - 供应商国内运费"
        ),
    }


def calculate_manual_profit(
    db: Session,
    *,
    org_id: str,
    asin: str,
    unit_price_cny: Decimal,
    domestic_shipping_cny: Decimal | None = None,
    supplier_name: str | None = None,
    supplier_url: str | None = None,
    moq: int | None = None,
    exchange_rate_usd_cny: Decimal | None = None,
    min_gross_margin: Decimal | None = None,
) -> dict[str, object]:
    product = _load_product(db, asin)
    candidate_id = _ensure_candidate(db, org_id=org_id, product=product)
    offer_id = _insert_supplier_offer(
        db,
        org_id=org_id,
        candidate_id=candidate_id,
        asin=asin,
        unit_price_cny=unit_price_cny,
        domestic_shipping_cny=domestic_shipping_cny,
        supplier_name=supplier_name,
        supplier_url=supplier_url,
        moq=moq,
        source="manual_1688",
    )
    result = _calculate_from_product_and_offer(
        product,
        {
            "id": offer_id,
            "unit_price_cny": unit_price_cny,
            "payload": {"domestic_shipping_cny": _decimal_number(domestic_shipping_cny)},
        },
        exchange_rate_usd_cny=exchange_rate_usd_cny,
        min_gross_margin=min_gross_margin,
    )
    snapshot_id = _insert_profit_snapshot(
        db,
        org_id=org_id,
        candidate_id=candidate_id,
        asin=asin,
        result=result,
        product=product,
        offer={
            "id": offer_id,
            "supplier_name": supplier_name,
            "supplier_url": supplier_url,
            "unit_price_cny": unit_price_cny,
            "moq": moq,
            "payload": {"domestic_shipping_cny": _decimal_number(domestic_shipping_cny)},
        },
    )
    _update_candidate_profit_status(db, candidate_id=candidate_id, verdict=result.verdict)
    db.commit()
    return _snapshot_response(
        snapshot_id=snapshot_id,
        candidate_id=candidate_id,
        asin=asin,
        product=product,
        result=result,
        offer={
            "id": offer_id,
            "supplier_name": supplier_name,
            "supplier_url": supplier_url,
            "unit_price_cny": unit_price_cny,
            "moq": moq,
            "payload": {"domestic_shipping_cny": _decimal_number(domestic_shipping_cny)},
        },
    )


def run_profit_for_existing_offers(
    db: Session,
    *,
    org_id: str,
    limit: int,
    asin: str | None = None,
    candidate_id: str | None = None,
    exchange_rate_usd_cny: Decimal | None = None,
    min_gross_margin: Decimal | None = None,
) -> dict[str, object]:
    rows = _load_supplier_offer_rows(
        db,
        org_id=org_id,
        limit=limit,
        asin=asin,
        candidate_id=candidate_id,
    )
    items: list[dict[str, object]] = []
    counts = {"processed": 0, "pass": 0, "reject": 0, "blocked": 0}
    for row in rows:
        product = _product_from_offer_row(row)
        if product is None:
            continue
        candidate_id = row.get("candidate_id") or _ensure_candidate(
            db,
            org_id=org_id,
            product=product,
        )
        result = _calculate_from_product_and_offer(
            product,
            row,
            exchange_rate_usd_cny=exchange_rate_usd_cny,
            min_gross_margin=min_gross_margin,
        )
        snapshot_id = _insert_profit_snapshot(
            db,
            org_id=org_id,
            candidate_id=str(candidate_id),
            asin=str(product["asin"]),
            result=result,
            product=product,
            offer=row,
        )
        _update_candidate_profit_status(db, candidate_id=str(candidate_id), verdict=result.verdict)
        counts["processed"] += 1
        counts[result.verdict if result.verdict in counts else "blocked"] += 1
        items.append(
            _snapshot_response(
                snapshot_id=snapshot_id,
                candidate_id=str(candidate_id),
                asin=str(product["asin"]),
                product=product,
                result=result,
                offer=row,
            )
        )
    db.commit()
    return {"counts": counts, "items": items, "formula": profit_formula_config()}


def list_profit_snapshots(
    db: Session,
    *,
    org_id: str,
    limit: int = 50,
) -> dict[str, object]:
    rows = db.execute(
        text(
            """
            SELECT s.id, s.candidate_id, s.asin, s.sell_price_usd,
                   s.landed_cost_usd, s.amazon_fees_usd, s.net_profit_usd,
                   s.net_margin, s.roi, s.confidence, s.payload, s.created_at,
                   p.title, p.title_zh, p.image_url, p.category, p.features
            FROM ra_profit_snapshots s
            LEFT JOIN products_rw p ON p.asin = s.asin
            WHERE s.org_id = :org_id
            ORDER BY s.created_at DESC
            LIMIT :limit
            """
        ),
        {"org_id": org_id, "limit": max(1, min(limit, 200))},
    ).mappings()
    items: list[dict[str, object]] = []
    for row in rows:
        payload = _dict_value(row.get("payload"))
        exchange_rate = decimal_value(
            payload.get("exchange_rate_usd_cny")
            or (payload.get("formula") or {}).get("default_exchange_rate_usd_cny")
        )
        gross_profit_cny = decimal_value(payload.get("gross_profit_cny"))
        if gross_profit_cny is None and exchange_rate is not None:
            net_profit = decimal_value(row["net_profit_usd"])
            if net_profit is not None:
                gross_profit_cny = net_profit * exchange_rate
        features = _dict_value(row.get("features"))
        items.append(
            {
                "snapshot_id": row["id"],
                "candidate_id": row["candidate_id"],
                "asin": row["asin"],
                "title": row["title"],
                "title_zh": row["title_zh"],
                "image_url": primary_product_image_url(
                    asin=str(row["asin"] or ""),
                    image_url=str(row["image_url"]) if row["image_url"] else None,
                    features=features,
                ),
                "image_candidates": product_image_candidates(
                    asin=str(row["asin"] or ""),
                    image_url=str(row["image_url"]) if row["image_url"] else None,
                    features=features,
                ),
                "category": row["category"],
                "amazon_price_usd": _decimal_number(row["sell_price_usd"]),
                "sell_price_usd": _decimal_number(row["sell_price_usd"]),
                "landed_cost_usd": _decimal_number(row["landed_cost_usd"]),
                "amazon_fees_usd": _decimal_number(row["amazon_fees_usd"]),
                "gross_profit_usd": _decimal_number(row["net_profit_usd"]),
                "gross_profit_cny": _money_number(gross_profit_cny),
                "gross_margin": _decimal_number(row["net_margin"]),
                "roi": _decimal_number(row["roi"]),
                "confidence": row["confidence"],
                "verdict": payload.get("verdict"),
                "warnings": payload.get("warnings") or [],
                "blocked_reasons": payload.get("blocked_reasons") or [],
                "supplier": payload.get("supplier") or {},
                "formula": payload.get("formula") or {},
                "created_at": str(row["created_at"]) if row["created_at"] else None,
            }
        )
    return {"items": items, "count": len(items), "formula": profit_formula_config()}


def _load_product(db: Session, asin: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            SELECT asin, marketplace, source_query, title, title_zh, image_url,
                   brand, category, category_id, category_path, price, state,
                   skill_score, features
            FROM products_rw
            WHERE asin = :asin
            LIMIT 1
            """
        ),
        {"asin": asin.strip().upper()},
    ).mappings().first()
    if row is None:
        raise RAProfitError("R-W 产品库中没有找到该 ASIN。")
    return dict(row)


def _ensure_candidate(
    db: Session,
    *,
    org_id: str,
    product: dict[str, Any],
    run_id: str | None = None,
) -> str:
    return _ensure_candidate_for_run(
        db,
        org_id=org_id,
        product=product,
        run_id=run_id,
    )


TITLE_ZH_SOURCE_RA_KEYWORD_PROFILE = "ra_keyword_profile"


def persist_title_zh(
    db: Session,
    *,
    asin: str,
    title_zh: str,
    source: str = TITLE_ZH_SOURCE_RA_KEYWORD_PROFILE,
    candidate_id: str | None = None,
) -> bool:
    """把 R-A 抽词顺带产出的中文名写回 R-W 产品行（只填空，不覆盖已有翻译）。

    2026-09-07 起 R-W 不再逐个产品调模型翻译，中文名只在产品走到 R-A 付费搜索
    这一步时由抽词那一次 DeepSeek 调用顺手带出来——不多花一次 API。
    """
    cleaned = " ".join(str(title_zh or "").split()).strip(" '\"“”")[:160]
    normalized_asin = str(asin or "").strip().upper()
    if not cleaned or not normalized_asin:
        return False
    result = db.execute(
        text(
            """
            UPDATE products_rw
            SET title_zh = :title_zh,
                title_zh_source = :source,
                title_zh_updated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE asin = :asin
              AND (title_zh IS NULL OR title_zh = '')
            """
        ),
        {"asin": normalized_asin, "title_zh": cleaned, "source": source},
    )
    if candidate_id:
        db.execute(
            text(
                """
                UPDATE ra_candidates
                SET title_zh = :title_zh, updated_at = CURRENT_TIMESTAMP
                WHERE id = :candidate_id
                  AND (title_zh IS NULL OR title_zh = '')
                """
            ),
            {"candidate_id": candidate_id, "title_zh": cleaned},
        )
    db.commit()
    return bool(getattr(result, "rowcount", 0))


def _ensure_candidate_for_run(
    db: Session,
    *,
    org_id: str,
    product: dict[str, Any],
    run_id: str | None = None,
) -> str:
    if run_id:
        existing = db.execute(
            text(
                """
                SELECT id
                FROM ra_candidates
                WHERE org_id = :org_id
                  AND run_id = :run_id
                  AND source_asin = :asin
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"org_id": org_id, "run_id": run_id, "asin": product["asin"]},
        ).mappings().first()
        if existing is not None:
            return str(existing["id"])

    if not run_id:
        existing = db.execute(
            text(
                """
                SELECT id
                FROM ra_candidates
                WHERE org_id = :org_id AND source_asin = :asin
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"org_id": org_id, "asin": product["asin"]},
        ).mappings().first()
        if existing is not None:
            return str(existing["id"])

    candidate_id = str(uuid4())
    snapshot = _product_snapshot(product)
    db.execute(
        text(
            f"""
            INSERT INTO ra_candidates (
              id, org_id, source_asin, marketplace, source_state, title,
              title_zh, channel_hint, candidate_status, run_id, snapshot
            )
            VALUES (
              :id, :org_id, :source_asin, :marketplace, :source_state, :title,
              :title_zh, 'amazon', 'profit_pending', :run_id, {_json_bind(db, "snapshot")}
            )
            """
        ),
        {
            "id": candidate_id,
            "org_id": org_id,
            "source_asin": product["asin"],
            "marketplace": product.get("marketplace") or "US",
            "source_state": product.get("state"),
            "title": product.get("title"),
            "title_zh": product.get("title_zh"),
            "run_id": run_id,
            "snapshot": json.dumps(snapshot, ensure_ascii=False),
        },
    )
    return candidate_id


def _insert_supplier_offer(
    db: Session,
    *,
    org_id: str,
    candidate_id: str,
    asin: str,
    unit_price_cny: Decimal | None,
    domestic_shipping_cny: Decimal | None,
    supplier_name: str | None,
    supplier_url: str | None,
    moq: int | None,
    source: str,
    search_id: str | None = None,
    rating: Decimal | None = None,
    match_score: int | None = 100,
    offer_status: str = "selected",
    payload_extra: dict[str, Any] | None = None,
) -> str:
    offer_id = str(uuid4())
    payload = {
        "source": source,
        "domestic_shipping_cny": _decimal_number(domestic_shipping_cny),
        "shipping_fee_cny": _decimal_number(domestic_shipping_cny),
        "captured_at": datetime.now(UTC).isoformat(),
    }
    if payload_extra:
        payload.update(payload_extra)
    db.execute(
        text(
            f"""
            INSERT INTO ra_supplier_offers (
              id, org_id, search_id, candidate_id, asin, supplier_name,
              supplier_url, unit_price_cny, moq, rating, match_score,
              offer_status, payload
            )
            VALUES (
              :id, :org_id, :search_id, :candidate_id, :asin, :supplier_name,
              :supplier_url, :unit_price_cny, :moq, :rating, :match_score,
              :offer_status, {_json_bind(db, "payload")}
            )
            """
        ),
        {
            "id": offer_id,
            "org_id": org_id,
            "search_id": search_id,
            "candidate_id": candidate_id,
            "asin": asin,
            "supplier_name": supplier_name,
            "supplier_url": supplier_url,
            "unit_price_cny": unit_price_cny,
            "moq": moq,
            "rating": rating,
            "match_score": match_score,
            "offer_status": offer_status,
            "payload": json.dumps(payload, ensure_ascii=False),
        },
    )
    return offer_id


def _insert_profit_snapshot(
    db: Session,
    *,
    org_id: str,
    candidate_id: str,
    asin: str,
    result: ProfitResult,
    product: dict[str, Any],
    offer: dict[str, Any],
) -> str:
    snapshot_id = str(uuid4())
    payload = result.to_payload()
    payload.update(
        {
            "formula": profit_formula_config(),
            "product": _product_snapshot(product),
            "supplier": _supplier_payload(offer),
        }
    )
    db.execute(
        text(
            f"""
            INSERT INTO ra_profit_snapshots (
              id, org_id, candidate_id, asin, sell_price_usd, landed_cost_usd,
              amazon_fees_usd, net_profit_usd, net_margin, roi, confidence,
              payload
            )
            VALUES (
              :id, :org_id, :candidate_id, :asin, :sell_price_usd,
              :landed_cost_usd, :amazon_fees_usd, :net_profit_usd,
              :net_margin, :roi, :confidence, {_json_bind(db, "payload")}
            )
            """
        ),
        {
            "id": snapshot_id,
            "org_id": org_id,
            "candidate_id": candidate_id,
            "asin": asin,
            "sell_price_usd": result.sell_price_usd,
            "landed_cost_usd": result.landed_cost_usd,
            "amazon_fees_usd": result.amazon_fees_usd,
            "net_profit_usd": result.gross_profit_usd,
            "net_margin": result.gross_margin,
            "roi": result.roi,
            "confidence": result.confidence,
            "payload": json.dumps(payload, ensure_ascii=False),
        },
    )
    return snapshot_id


def _update_candidate_profit_status(db: Session, *, candidate_id: str, verdict: str) -> None:
    status = {
        "pass": "profit_passed",
        "reject": "profit_rejected",
        "blocked": "profit_blocked",
    }.get(verdict, "profit_pending")
    db.execute(
        text(
            """
            UPDATE ra_candidates
            SET candidate_status = :status, updated_at = CURRENT_TIMESTAMP
            WHERE id = :candidate_id
            """
        ),
        {"candidate_id": candidate_id, "status": status},
    )


def _calculate_from_product_and_offer(
    product: dict[str, Any],
    offer: dict[str, Any],
    *,
    exchange_rate_usd_cny: Decimal | None,
    min_gross_margin: Decimal | None,
) -> ProfitResult:
    features = _dict_value(product.get("features"))
    payload = _dict_value(offer.get("payload"))
    unit_price_cny = decimal_value(offer.get("unit_price_cny"))
    if _supplier_payload_blocks_profit(product=product, payload=payload):
        unit_price_cny = None
    domestic_shipping_cny = _offer_domestic_shipping(offer)
    return calculate_us_profit(
        ProfitInput(
            asin=str(product["asin"]),
            sell_price_usd=decimal_value(product.get("price")),
            fba_fee_usd=_feature_decimal(features, "fba_fee_usd"),
            unit_price_cny=unit_price_cny,
            domestic_shipping_cny=domestic_shipping_cny,
            actual_weight_kg=_weight_kg(features),
            length_cm=_dimension_cm(features, "length"),
            width_cm=_dimension_cm(features, "width"),
            height_cm=_dimension_cm(features, "height"),
            exchange_rate_usd_cny=exchange_rate_usd_cny or _exchange_rate(),
            min_gross_margin=min_gross_margin or _min_gross_margin(),
            marketplace=str(product.get("marketplace") or "US"),
        )
    )


def _supplier_payload_blocks_profit(*, product: dict[str, Any], payload: dict[str, Any]) -> bool:
    alignment = _dict_value(payload.get("supplier_alignment"))
    alignment_status = str(alignment.get("match_status") or "").strip().lower()
    if alignment_status and alignment_status != "match":
        return True
    quantity = _dict_value(alignment.get("quantity"))
    if str(quantity.get("status") or "").strip().lower() == "needs_review":
        return True
    dimensions = _dict_value(alignment.get("dimensions"))
    if str(dimensions.get("status") or "").strip().lower() == "needs_review":
        return True

    product_text = " ".join(
        str(value)
        for value in (product.get("title"), product.get("title_zh"))
        if value
    )
    keyword_profile = _dict_value(payload.get("keyword_profile"))
    profile_text = " ".join(
        str(value)
        for value in (
            keyword_profile.get("product_type_zh"),
            keyword_profile.get("pack_count"),
        )
        if value
    )
    if _requires_pack_alignment_text(f"{product_text} {profile_text}"):
        quantity_status = str(quantity.get("status") or "").strip().lower()
        if quantity_status != "aligned":
            return True
    return False


def _requires_pack_alignment_text(text_value: str) -> bool:
    return bool(
        re.search(
            r"(?:multipack|multi\s*pack|pack\s*of|set\s*of|多件装|多只装|多个装|多片装|多双装|多对装|套装|组合装|礼盒装)",
            str(text_value or "").lower(),
            flags=re.IGNORECASE,
        )
    )


def _load_supplier_offer_rows(
    db: Session,
    *,
    org_id: str,
    limit: int,
    asin: str | None = None,
    candidate_id: str | None = None,
) -> list[dict[str, Any]]:
    asin_filter = "AND COALESCE(o.asin, c.source_asin) = :asin" if asin else ""
    candidate_filter = "AND o.candidate_id = :candidate_id" if candidate_id else ""
    rows = db.execute(
        text(
            f"""
            SELECT o.id, o.search_id, o.candidate_id, o.asin, o.supplier_name, o.supplier_url,
                   o.unit_price_cny, o.moq, o.rating, o.match_score,
                   o.offer_status, o.payload,
                   p.asin AS product_asin, p.marketplace, p.source_query, p.title,
                   p.title_zh, p.image_url, p.brand, p.category, p.category_id,
                   p.category_path, p.price, p.state, p.skill_score,
                   p.features
            FROM ra_supplier_offers o
            LEFT JOIN ra_candidates c ON c.id = o.candidate_id
            LEFT JOIN products_rw p ON p.asin = COALESCE(o.asin, c.source_asin)
            WHERE o.org_id = :org_id
              AND o.unit_price_cny IS NOT NULL
              AND p.asin IS NOT NULL
              {asin_filter}
              {candidate_filter}
            ORDER BY
              CASE WHEN o.offer_status = 'selected' THEN 0 ELSE 1 END,
              o.match_score DESC NULLS LAST,
              o.unit_price_cny ASC NULLS LAST,
              o.updated_at DESC
            LIMIT :limit
            """
        ),
        {
            "org_id": org_id,
            "limit": max(1, min(limit, 200)),
            "asin": asin.strip().upper() if asin else None,
            "candidate_id": candidate_id,
        },
    ).mappings()
    return [dict(row) for row in rows]


def _product_from_offer_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row.get("product_asin"):
        return None
    return {
        "asin": row["product_asin"],
        "marketplace": row.get("marketplace"),
        "source_query": row.get("source_query"),
        "title": row.get("title"),
        "title_zh": row.get("title_zh"),
        "image_url": row.get("image_url"),
        "brand": row.get("brand"),
        "category": row.get("category"),
        "category_id": row.get("category_id"),
        "category_path": row.get("category_path"),
        "price": row.get("price"),
        "state": row.get("state"),
        "skill_score": row.get("skill_score"),
        "features": row.get("features"),
    }


def _product_snapshot(product: dict[str, Any]) -> dict[str, Any]:
    features = _dict_value(product.get("features"))
    image_candidates = product_image_candidates(
        asin=str(product.get("asin") or ""),
        image_url=str(product.get("image_url")) if product.get("image_url") else None,
        features=features,
    )
    return {
        "asin": product.get("asin"),
        "marketplace": product.get("marketplace"),
        "title": product.get("title"),
        "title_zh": product.get("title_zh"),
        "image_url": primary_product_image_url(
            asin=str(product.get("asin") or ""),
            image_url=str(product.get("image_url")) if product.get("image_url") else None,
            features=features,
        ),
        "image_candidates": image_candidates,
        "category": product.get("category"),
        "category_id": product.get("category_id"),
        "category_path": product.get("category_path"),
        "price": _decimal_number(product.get("price")),
        "state": product.get("state"),
        "skill_score": product.get("skill_score"),
        "fba_fee_usd": _decimal_number(_feature_decimal(features, "fba_fee_usd")),
        "package_weight_g": _decimal_number(_feature_decimal(features, "package_weight_g")),
        "package_length_mm": _decimal_number(_feature_decimal(features, "package_length_mm")),
        "package_width_mm": _decimal_number(_feature_decimal(features, "package_width_mm")),
        "package_height_mm": _decimal_number(_feature_decimal(features, "package_height_mm")),
        "amazon_pack_count": _decimal_number(features.get("amazon_pack_count")),
        "amazon_pack_label": features.get("amazon_pack_label"),
        "amazon_pack_source": features.get("amazon_pack_source"),
        "amazon_pack_confidence": features.get("amazon_pack_confidence"),
        "amazon_pack_requires_alignment": bool(features.get("amazon_pack_requires_alignment")),
    }


def _supplier_payload(offer: dict[str, Any]) -> dict[str, Any]:
    payload = _dict_value(offer.get("payload"))
    return {
        "offer_id": offer.get("id"),
        "search_id": offer.get("search_id"),
        "supplier_name": offer.get("supplier_name"),
        "supplier_url": offer.get("supplier_url"),
        "unit_price_cny": _decimal_number(offer.get("unit_price_cny")),
        "domestic_shipping_cny": _decimal_number(_offer_domestic_shipping(offer)),
        "moq": offer.get("moq"),
        "rating": _decimal_number(offer.get("rating")),
        "match_score": offer.get("match_score"),
        "offer_status": offer.get("offer_status"),
        "source": payload.get("source"),
        "supplier_platform": payload.get("platform"),
        "supplier_platform_label": payload.get("platform_label"),
        "supplier_url_type": payload.get("supplier_url_type"),
        "supplier_detail_url": payload.get("supplier_detail_url") or offer.get("supplier_url"),
        "supplier_search_url": payload.get("supplier_search_url")
        or payload.get("search_url")
        or payload.get("choice_page_url"),
        "crawler_status": payload.get("crawler_status"),
        "one_piece_hint": bool(payload.get("one_piece_hint")),
        "supplier_alignment": payload.get("supplier_alignment"),
        "shipping_notice": payload.get("shipping_notice")
        or payload.get("freight_notice")
        or payload.get("shipping_text"),
    }


def _snapshot_response(
    *,
    snapshot_id: str,
    candidate_id: str,
    asin: str,
    product: dict[str, Any],
    result: ProfitResult,
    offer: dict[str, Any],
) -> dict[str, object]:
    features = _dict_value(product.get("features"))
    return {
        "snapshot_id": snapshot_id,
        "candidate_id": candidate_id,
        "asin": asin,
        "title": product.get("title"),
        "title_zh": product.get("title_zh"),
        "image_url": primary_product_image_url(
            asin=asin,
            image_url=str(product.get("image_url")) if product.get("image_url") else None,
            features=features,
        ),
        "image_candidates": product_image_candidates(
            asin=asin,
            image_url=str(product.get("image_url")) if product.get("image_url") else None,
            features=features,
        ),
        "category": product.get("category"),
        "amazon_price_usd": _decimal_number(result.sell_price_usd),
        "sell_price_usd": _decimal_number(result.sell_price_usd),
        "landed_cost_usd": _decimal_number(result.landed_cost_usd),
        "amazon_fees_usd": _decimal_number(result.amazon_fees_usd),
        "gross_profit_usd": _decimal_number(result.gross_profit_usd),
        "gross_profit_cny": _money_number(
            result.gross_profit_usd * result.exchange_rate_usd_cny
            if result.gross_profit_usd is not None
            else None
        ),
        "gross_margin": _decimal_number(result.gross_margin),
        "roi": _decimal_number(result.roi),
        "confidence": result.confidence,
        "verdict": result.verdict,
        "warnings": list(result.warnings),
        "blocked_reasons": list(result.blocked_reasons),
        "supplier": _supplier_payload(offer),
        "formula": profit_formula_config(),
        "created_at": datetime.now(UTC).isoformat(),
    }


def _offer_domestic_shipping(offer: dict[str, Any]) -> Decimal | None:
    payload = _dict_value(offer.get("payload"))
    for key in (
        "domestic_shipping_cny",
        "shipping_fee_cny",
        "freight_cny",
        "freight",
        "delivery_fee_cny",
        "shipping_cost_cny",
        "1688_shipping_fee_cny",
    ):
        value = decimal_value(payload.get(key))
        if value is not None:
            return value
    return None


def _weight_kg(features: dict[str, Any]) -> Decimal | None:
    grams = _feature_decimal(features, "package_weight_g") or _feature_decimal(
        features,
        "item_weight_g",
    )
    if grams is not None:
        return grams / Decimal("1000")
    return _feature_decimal(features, "package_weight_kg") or _feature_decimal(
        features,
        "item_weight_kg",
    )


def _dimension_cm(features: dict[str, Any], dimension: str) -> Decimal | None:
    mm_key = f"package_{dimension}_mm"
    item_mm_key = f"item_{dimension}_mm"
    cm_key = f"package_{dimension}_cm"
    item_cm_key = f"item_{dimension}_cm"
    mm = _feature_decimal(features, mm_key) or _feature_decimal(features, item_mm_key)
    if mm is not None:
        return mm / Decimal("10")
    return _feature_decimal(features, cm_key) or _feature_decimal(features, item_cm_key)


def _feature_decimal(features: dict[str, Any], key: str) -> Decimal | None:
    return decimal_value(features.get(key))


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


def _decimal_number(value: Any) -> float | None:
    decimal = decimal_value(value)
    return float(decimal) if decimal is not None else None


def _money_number(value: Any) -> float | None:
    decimal = decimal_value(value)
    if decimal is None:
        return None
    return float(decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _json_bind(db: Session, name: str) -> str:
    if _is_postgres(db):
        return f"CAST(:{name} AS JSONB)"
    return f":{name}"


def _is_postgres(db: Session) -> bool:
    try:
        return db.get_bind().dialect.name == "postgresql"
    except SQLAlchemyError:
        return False


def _exchange_rate() -> Decimal:
    return get_usd_cny_quote().rate


def _min_gross_margin() -> Decimal:
    return decimal_value(os.getenv("RA_MIN_GROSS_MARGIN")) or DEFAULT_MIN_GROSS_MARGIN
