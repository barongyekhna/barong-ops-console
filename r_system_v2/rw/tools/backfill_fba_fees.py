"""Backfill Keepa FBA fee fields for existing R-W products."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from sqlalchemy import text

from backend.app.db.session import SessionLocal
from r_system_v2.rw.core.models import KeepaProductData, utc_now_iso
from r_system_v2.rw.providers.keepa_provider import (
    MAX_REQUESTS_PER_MINUTE,
    KeepaConfigurationError,
    KeepaProvider,
    KeepaResponseError,
)
from r_system_v2.rw.workers.deepseek_cron import _dict_value, _is_postgres


BACKFILL_VERSION = "fba_fee_backfill_2026_07_04_v1"
DEFAULT_BATCH_SIZE = 20
DEFAULT_SLEEP_SECONDS = 60


def main() -> None:
    batch_size = min(_int_env("RW_FBA_FEE_BACKFILL_BATCH_SIZE", DEFAULT_BATCH_SIZE), MAX_REQUESTS_PER_MINUTE)
    max_products = _int_env("RW_FBA_FEE_BACKFILL_MAX_PRODUCTS", 0, minimum=0)
    token_reserve = _int_env("RW_FBA_FEE_BACKFILL_TOKEN_RESERVE", 0, minimum=0)
    sleep_seconds = _int_env("RW_FBA_FEE_BACKFILL_SLEEP_SECONDS", DEFAULT_SLEEP_SECONDS)
    org_id = _resolve_org_id()
    provider = KeepaProvider(org_id=org_id)
    scanned = 0
    updated = 0
    missing = 0
    failed = 0

    while max_products <= 0 or scanned < max_products:
        try:
            status = provider.status()
        except (KeepaConfigurationError, KeepaResponseError, TimeoutError, OSError) as exc:
            failed += 1
            print(f"status_error={type(exc).__name__}:{str(exc)[:160]}", flush=True)
            time.sleep(sleep_seconds)
            continue

        available = max(0, int(status.tokens_left) - token_reserve)
        limit = min(batch_size, available)
        if max_products > 0:
            limit = min(limit, max_products - scanned)
        if limit <= 0:
            print(
                f"waiting_for_tokens tokens_left={status.tokens_left} reserve={token_reserve}",
                flush=True,
            )
            time.sleep(sleep_seconds)
            continue

        with SessionLocal() as db:
            rows = _load_rows(db, limit=limit)
            if not rows:
                break
            for row in rows:
                asin = str(row["asin"])
                scanned += 1
                try:
                    keepa_data = provider.fetch_product(asin, source_query=str(row.get("source_query") or asin))
                    features = _dict_value(row.get("features"))
                    _merge_fee_features(features, keepa_data)
                    _update_product(db, asin=asin, features=features, keepa_data=keepa_data)
                    updated += 1
                    if keepa_data.fba_fee_usd is None:
                        missing += 1
                except (KeepaConfigurationError, KeepaResponseError, TimeoutError, OSError) as exc:
                    failed += 1
                    print(f"asin={asin} error={type(exc).__name__}:{str(exc)[:160]}", flush=True)
                    if "429" in str(exc):
                        break
            db.commit()
        print(
            f"scanned={scanned} updated={updated} missing_fee={missing} failed={failed}",
            flush=True,
        )

    print(
        f"done scanned={scanned} updated={updated} missing_fee={missing} failed={failed}",
        flush=True,
    )


def _load_rows(db, *, limit: int) -> list[dict[str, Any]]:
    if _is_postgres(db):
        statement = text(
            """
            SELECT asin, source_query, features
            FROM products_rw
            WHERE NOT (COALESCE(features, '{}'::jsonb) ? 'fba_fee_backfill_version')
              AND NOT (
                COALESCE(features, '{}'::jsonb) ? 'fba_fee_source'
                AND COALESCE(features->>'fba_fee_source', '') <> ''
              )
            ORDER BY last_keepa_pull ASC NULLS FIRST, updated_at ASC NULLS FIRST
            LIMIT :limit
            """
        )
    else:
        statement = text(
            """
            SELECT asin, source_query, features
            FROM products_rw
            WHERE json_extract(features, '$.fba_fee_backfill_version') IS NULL
              AND json_extract(features, '$.fba_fee_source') IS NULL
            ORDER BY last_keepa_pull ASC, updated_at ASC
            LIMIT :limit
            """
        )
    rows = db.execute(statement, {"limit": max(1, limit)}).mappings()
    return [dict(row) for row in rows]


def _merge_fee_features(features: dict[str, Any], keepa_data: KeepaProductData) -> None:
    checked_at = utc_now_iso()
    features.update(
        {
            "fba_fee_usd": keepa_data.fba_fee_usd,
            "fba_pick_pack_fee_usd": keepa_data.fba_fee_usd,
            "fba_fee_currency": "USD" if keepa_data.fba_fee_usd is not None else None,
            "fba_fee_source": "keepa_fbaFees.pickAndPackFee"
            if keepa_data.fba_fee_usd is not None
            else "missing_keepa_fbaFees",
            "fba_fee_last_update": keepa_data.fba_fee_last_update,
            "fba_fee_checked_at": checked_at,
            "fba_fee_backfill_version": BACKFILL_VERSION,
            "referral_fee_percentage": keepa_data.referral_fee_percentage,
            "package_weight_g": keepa_data.package_weight_g,
            "package_length_mm": keepa_data.package_length_mm,
            "package_width_mm": keepa_data.package_width_mm,
            "package_height_mm": keepa_data.package_height_mm,
            "item_weight_g": keepa_data.item_weight_g,
            "item_length_mm": keepa_data.item_length_mm,
            "item_width_mm": keepa_data.item_width_mm,
            "item_height_mm": keepa_data.item_height_mm,
            "amazon_pack_count": keepa_data.amazon_pack_count,
            "amazon_pack_label": keepa_data.amazon_pack_label,
            "amazon_pack_source": keepa_data.amazon_pack_source,
            "amazon_pack_confidence": keepa_data.amazon_pack_confidence,
            "amazon_pack_requires_alignment": keepa_data.amazon_pack_requires_alignment,
            "amazon_pack_evidence": keepa_data.amazon_pack_evidence,
            "amazon_variation_attributes": keepa_data.amazon_variation_attributes,
            "amazon_parent_asin": keepa_data.amazon_parent_asin,
            "amazon_variation_csv": keepa_data.amazon_variation_csv,
        }
    )
    if keepa_data.fulfillment_method:
        features["fulfillment_method"] = keepa_data.fulfillment_method


def _update_product(
    db,
    *,
    asin: str,
    features: dict[str, Any],
    keepa_data: KeepaProductData,
) -> None:
    features_value = "CAST(:features AS JSONB)" if _is_postgres(db) else ":features"
    db.execute(
        text(
            f"""
            UPDATE products_rw
            SET features = {features_value},
                fulfillment_method = COALESCE(:fulfillment_method, fulfillment_method),
                last_keepa_pull = COALESCE(:last_keepa_pull, last_keepa_pull),
                updated_at = updated_at
            WHERE asin = :asin
            """
        ),
        {
            "asin": asin,
            "features": json.dumps(features, ensure_ascii=False),
            "fulfillment_method": keepa_data.fulfillment_method,
            "last_keepa_pull": keepa_data.fetched_at,
        },
    )


def _resolve_org_id() -> str:
    configured = os.getenv("R_SYSTEM_ORG_ID", "").strip()
    if configured:
        return configured
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                SELECT org_id
                FROM organizations
                WHERE org_name = :name OR name = :name
                ORDER BY created_at ASC
                LIMIT 1
                """
            ),
            {"name": "涌龙麟（深圳）国际贸易有限公司"},
        ).first()
    return str(row[0]) if row else ""


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


if __name__ == "__main__":
    main()
