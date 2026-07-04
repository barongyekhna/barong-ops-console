"""Backfill BSR-based monthly sales estimates for existing R-W products."""

from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy import text

from backend.app.db.session import SessionLocal
from r_system_v2.rw.processor.monthly_sales_estimator import (
    ESTIMATOR_VERSION,
    estimate_monthly_sales,
)
from r_system_v2.rw.workers.deepseek_cron import _dict_value, _is_postgres


DEFAULT_BATCH_SIZE = 500


def main() -> None:
    batch_size = _int_env("RW_MONTHLY_SALES_BACKFILL_BATCH_SIZE", DEFAULT_BATCH_SIZE)
    scanned = 0
    updated = 0
    with SessionLocal() as db:
        while True:
            rows = _load_rows(db, limit=batch_size)
            if not rows:
                break
            for row in rows:
                scanned += 1
                features = _dict_value(row.get("features"))
                estimate = estimate_monthly_sales(
                    bsr=_int_value(row.get("bsr")),
                    category=str(row.get("category") or ""),
                    parent_category_name=_string_feature(features, "parent_category_name"),
                    subcategory_name=_string_feature(features, "subcategory_name"),
                    monthly_sales=_int_value(features.get("monthly_sales")),
                )
                features.update(estimate.to_features())
                if features.get("monthly_sales") in {0, "0"}:
                    features["monthly_sales"] = None
                if features.get("monthly_sales") is None:
                    features["monthly_sales_source"] = "unknown"
                _update_features(db, asin=str(row["asin"]), features=features)
                updated += 1
            db.commit()
    print(f"scanned={scanned} updated={updated}")


def _load_rows(db, *, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT asin, category, bsr, features
            FROM products_rw
            WHERE COALESCE(features->>'monthly_sales_estimator_version', '') <> :version
               OR NOT (features ? 'monthly_sales_estimate')
            ORDER BY updated_at ASC
            LIMIT :limit
            """
        ),
        {"version": ESTIMATOR_VERSION, "limit": max(1, limit)},
    ).mappings()
    return [dict(row) for row in rows]


def _update_features(db, *, asin: str, features: dict[str, Any]) -> None:
    features_value = "CAST(:features AS JSONB)" if _is_postgres(db) else ":features"
    db.execute(
        text(
            f"""
            UPDATE products_rw
            SET features = {features_value},
                updated_at = updated_at
            WHERE asin = :asin
            """
        ),
        {"asin": asin, "features": json.dumps(features, ensure_ascii=False)},
    )


def _string_feature(features: dict[str, Any], key: str) -> str | None:
    value = features.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


if __name__ == "__main__":
    main()
