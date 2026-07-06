"""Backfill R-W product images from Keepa product payloads."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from sqlalchemy import select, text

from backend.app.db.session import SessionLocal
from backend.app.models.organization import OrganizationRecord
from r_system_v2.core.secret_manager import SecretManager
from r_system_v2.rw.providers.keepa_provider import KeepaProvider


TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"


def main() -> None:
    args = _parse_args()
    report = backfill_product_images(limit=args.limit, sleep_seconds=args.sleep)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def backfill_product_images(*, limit: int, sleep_seconds: float = 0.0) -> dict[str, Any]:
    db = SessionLocal()
    try:
        org = db.scalar(
            select(OrganizationRecord)
            .where(
                OrganizationRecord.org_name == TARGET_ORGANIZATION_NAME,
                OrganizationRecord.status != "deleted",
            )
            .order_by(OrganizationRecord.org_id)
            .limit(1)
        )
        if org is None:
            raise RuntimeError("target_organization_not_found")

        provider = KeepaProvider(
            org_id=org.org_id,
            secret_manager=SecretManager(db_session=db),
            timeout_sec=12.0,
        )
        rows = db.execute(
            text(
                """
                SELECT asin, title, image_url, features, updated_at
                FROM products_rw
                WHERE image_url IS NULL
                   OR image_url = ''
                   OR image_url LIKE '%/images/P/%'
                   OR COALESCE(features->>'image_candidates', '') LIKE '%/images/P/%'
                ORDER BY updated_at DESC NULLS LAST, asin ASC
                LIMIT :limit
                """
            ),
            {"limit": max(1, min(int(limit), 5000))},
        ).mappings().all()

        updated = 0
        skipped_no_image = 0
        failed: list[dict[str, str]] = []
        for row in rows:
            asin = str(row["asin"])
            try:
                keepa_data = provider.fetch_product(asin, source_query=row.get("title"))
            except Exception as exc:
                message = str(exc)
                failed.append({"asin": asin, "error": message[:240]})
                if _looks_rate_limited(message):
                    break
                continue

            image_candidates = [
                candidate
                for candidate in keepa_data.image_candidates
                if isinstance(candidate, str) and "/images/I/" in candidate
            ]
            if not image_candidates:
                skipped_no_image += 1
                continue

            features = row.get("features") if isinstance(row.get("features"), dict) else {}
            next_features = dict(features)
            next_features["image_candidates"] = image_candidates
            next_features["image_backfill_source"] = "keepa_product_images"
            next_features["image_backfill_candidate_count"] = len(image_candidates)
            db.execute(
                text(
                    """
                    UPDATE products_rw
                    SET image_url = :image_url,
                        features = CAST(:features AS jsonb),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE asin = :asin
                    """
                ),
                {
                    "asin": asin,
                    "image_url": image_candidates[0],
                    "features": json.dumps(next_features, ensure_ascii=False),
                },
            )
            db.commit()
            updated += 1
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        return {
            "requested": len(rows),
            "updated": updated,
            "skipped_no_image": skipped_no_image,
            "failed": failed[:20],
            "failed_count": len(failed),
        }
    finally:
        db.close()


def _looks_rate_limited(message: str) -> bool:
    lowered = message.lower()
    return "429" in lowered or "too many" in lowered or "tokens" in lowered


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=0.0)
    return parser.parse_args()


if __name__ == "__main__":
    main()
