"""Backfill Amazon pack quantity fields for existing R-W products."""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

from sqlalchemy import text

from backend.app.db.session import SessionLocal
from r_system_v2.rw.core.models import KeepaProductData, utc_now_iso
from r_system_v2.rw.processor.amazon_pack_resolver import resolve_amazon_pack
from r_system_v2.rw.providers.keepa_provider import (
    KEEPA_SUSTAINABLE_REQUESTS_PER_MIN,
    KeepaConfigurationError,
    KeepaProvider,
    KeepaResponseError,
)
from r_system_v2.rw.workers.deepseek_cron import _dict_value, _is_postgres
from r_system_v2.rw.workers.worker_runtime import _resolve_org_id


BACKFILL_VERSION = "amazon_pack_backfill_2026_07_08_v1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--token-reserve", type=int, default=2)
    parser.add_argument("--asins", default=os.getenv("RW_AMAZON_PACK_BACKFILL_ASINS", ""))
    args = parser.parse_args()
    report = backfill_amazon_pack(
        limit=max(1, args.limit),
        sleep_seconds=max(0.0, args.sleep),
        token_reserve=max(0, args.token_reserve),
        asins=_parse_asins(args.asins),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def backfill_amazon_pack(
    *,
    limit: int,
    sleep_seconds: float = 0.0,
    token_reserve: int = 2,
    asins: list[str] | None = None,
) -> dict[str, Any]:
    org_id = _resolve_org_id()
    provider = KeepaProvider(org_id=org_id)
    scanned = 0
    updated = 0
    from_keepa = 0
    from_existing_text = 0
    failed = 0
    max_rows = max(1, min(limit, 500))

    with SessionLocal() as db:
        rows = _load_rows(db, limit=max_rows, asins=asins or [])
        for row in rows:
            asin = str(row["asin"])
            features = _dict_value(row.get("features"))
            scanned += 1
            keepa_data: KeepaProductData | None = None
            try:
                if _may_spend_keepa_token(provider, token_reserve=token_reserve):
                    keepa_data = provider.fetch_product(
                        asin,
                        source_query=str(row.get("source_query") or asin),
                    )
            except (KeepaConfigurationError, KeepaResponseError, TimeoutError, OSError) as exc:
                failed += 1
                features["amazon_pack_backfill_error"] = f"{type(exc).__name__}:{str(exc)[:180]}"
            if keepa_data is not None:
                _merge_pack_features(features, _pack_from_keepa_data(keepa_data), source="keepa")
                from_keepa += 1
            else:
                fallback = resolve_amazon_pack(
                    {
                        "asin": asin,
                        "title": " ".join(
                            str(value)
                            for value in (row.get("title"), row.get("title_zh"))
                            if value
                        ),
                    },
                    asin=asin,
                )
                _merge_pack_features(features, fallback, source="existing_text")
                from_existing_text += 1
            _update_product(db, asin=asin, features=features)
            updated += 1
            if sleep_seconds:
                time.sleep(sleep_seconds)
        db.commit()

    return {
        "scanned": scanned,
        "updated": updated,
        "from_keepa": from_keepa,
        "from_existing_text": from_existing_text,
        "failed": failed,
        "version": BACKFILL_VERSION,
    }


def _load_rows(db, *, limit: int, asins: list[str]) -> list[dict[str, Any]]:
    if asins:
        rows = db.execute(
            text(
                """
                SELECT asin, source_query, title, title_zh, features
                FROM products_rw
                WHERE asin = ANY(:asins)
                ORDER BY asin
                LIMIT :limit
                """
            ),
            {"asins": asins, "limit": limit},
        ).mappings()
        return [dict(row) for row in rows]
    if _is_postgres(db):
        statement = text(
            """
            SELECT asin, source_query, title, title_zh, features
            FROM products_rw
            WHERE NOT (COALESCE(features, '{}'::jsonb) ? 'amazon_pack_backfill_version')
              AND (
                COALESCE(features->>'amazon_pack_source', '') = ''
                OR COALESCE(features->>'amazon_pack_confidence', '') IN ('needs_review', 'none')
              )
            ORDER BY updated_at DESC NULLS LAST
            LIMIT :limit
            """
        )
    else:
        statement = text(
            """
            SELECT asin, source_query, title, title_zh, features
            FROM products_rw
            WHERE json_extract(features, '$.amazon_pack_backfill_version') IS NULL
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        )
    return [dict(row) for row in db.execute(statement, {"limit": limit}).mappings()]


def _may_spend_keepa_token(provider: KeepaProvider, *, token_reserve: int) -> bool:
    status = provider.status()
    return int(status.tokens_left) > max(token_reserve, KEEPA_SUSTAINABLE_REQUESTS_PER_MIN)


def _pack_from_keepa_data(keepa_data: KeepaProductData) -> dict[str, Any]:
    return {
        "count": keepa_data.amazon_pack_count,
        "label": keepa_data.amazon_pack_label,
        "source": keepa_data.amazon_pack_source,
        "confidence": keepa_data.amazon_pack_confidence,
        "requires_alignment": keepa_data.amazon_pack_requires_alignment,
        "evidence": keepa_data.amazon_pack_evidence,
        "variation_attributes": keepa_data.amazon_variation_attributes,
        "parent_asin": keepa_data.amazon_parent_asin,
        "variation_csv": keepa_data.amazon_variation_csv,
    }


def _merge_pack_features(features: dict[str, Any], pack: dict[str, Any], *, source: str) -> None:
    resolved_count = pack.get("count")
    features.update(
        {
            "amazon_pack_count": resolved_count,
            "amazon_pack_label": pack.get("label"),
            "amazon_pack_source": pack.get("source"),
            "amazon_pack_confidence": pack.get("confidence"),
            "amazon_pack_requires_alignment": bool(pack.get("requires_alignment")),
            "amazon_pack_evidence": pack.get("evidence") or [],
            "amazon_variation_attributes": pack.get("variation_attributes") or [],
            "amazon_parent_asin": pack.get("parent_asin"),
            "amazon_variation_csv": pack.get("variation_csv"),
            "amazon_pack_checked_at": utc_now_iso(),
            "amazon_pack_backfill_source": source,
            "amazon_pack_backfill_version": BACKFILL_VERSION,
        }
    )
    if _positive_count(resolved_count):
        ra_profit = _dict_value(features.get("ra_profit"))
        if str(ra_profit.get("status") or "").strip() == "quantity_pending":
            features["ra_profit_previous_quantity_pending"] = ra_profit
            features["ra_profit_reset_reason"] = (
                "amazon_pack_count_resolved_after_backfill; R-A profit can recalculate."
            )
            features.pop("ra_profit", None)


def _update_product(db, *, asin: str, features: dict[str, Any]) -> None:
    features_value = "CAST(:features AS JSONB)" if _is_postgres(db) else ":features"
    db.execute(
        text(
            f"""
            UPDATE products_rw
            SET features = {features_value},
                updated_at = CURRENT_TIMESTAMP
            WHERE asin = :asin
            """
        ),
        {
            "asin": asin,
            "features": json.dumps(features, ensure_ascii=False),
        },
    )


def _parse_asins(value: str) -> list[str]:
    output: list[str] = []
    for item in value.replace("\n", ",").split(","):
        asin = item.strip().upper()
        if len(asin) == 10 and asin.isalnum() and asin not in output:
            output.append(asin)
    return output


def _positive_count(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return int(value) > 1
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip()) > 1
    return False


if __name__ == "__main__":
    main()
