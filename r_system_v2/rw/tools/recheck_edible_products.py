"""Recheck existing R-W products after DeepSeek policy boundary changes."""

from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy import text

from backend.app.db.session import SessionLocal
from r_system_v2.rw.ai.deepseek_screening import (
    DeepSeekScreeningSkill,
    deepseek_reject_code,
)
from r_system_v2.rw.ai.model_config import rw_deepseek_model
from r_system_v2.rw.core.models import ProductState
from r_system_v2.rw.scoring_engine import ScoringEngine
from r_system_v2.rw.storage.pipeline_events import PipelineEvent, emit_pipeline_event
from r_system_v2.rw.workers.deepseek_cron import _dict_value, _is_postgres, _product_from_row


DEFAULT_BATCH_SIZE = 500
POLICY_RECHECK_VERSION = "2026-07-07-v10"
POLICY_REJECT_REASONS = {
    "deepseek_edible_product",
    "deepseek_liquid_powder_spray_product",
    "deepseek_pest_control_product",
}


def main() -> None:
    limit = _int_env("RW_DEEPSEEK_POLICY_RECHECK_LIMIT", 0)
    batch_size = _int_env("RW_DEEPSEEK_POLICY_RECHECK_BATCH_SIZE", DEFAULT_BATCH_SIZE)
    target_asins = _csv_env("RW_DEEPSEEK_POLICY_RECHECK_ASINS")
    scanned = 0
    rejected = 0
    skill = DeepSeekScreeningSkill()
    scoring = ScoringEngine()
    with SessionLocal() as db:
        while True:
            rows = _load_rows(db, limit=batch_size, target_asins=target_asins)
            if not rows:
                break
            for row in rows:
                scanned += 1
                product = _product_from_row(row)
                screening = skill.evaluate(product)
                decision = scoring.score_deepseek(screening)
                if decision.action == "reject":
                    _reject_product(db, row, screening, decision.reason)
                    rejected += 1
                elif row.get("rule_reject_reason") in POLICY_REJECT_REASONS:
                    _restore_policy_product(db, row, screening, decision.reason)
                else:
                    _mark_checked(db, row)
                if limit and scanned >= limit:
                    db.commit()
                    print(f"scanned={scanned} rejected={rejected}")
                    return
            db.commit()
            if target_asins:
                print(f"scanned={scanned} rejected={rejected}")
                return
    print(f"scanned={scanned} rejected={rejected}")


def _load_rows(
    db,
    *,
    limit: int,
    target_asins: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if target_asins:
        return _load_target_rows(db, target_asins=target_asins)[: max(1, limit)]
    rows = db.execute(
        text(
            """
            SELECT asin, marketplace, source_query, title, image_url, brand, category,
                   price, bsr, reviews, seller_count, landed_cost, est_net_margin,
                   brand_share, price_trend, rating, fulfillment_method,
                   lithium_battery_warning, margin_source, margin_confidence,
                   category_id, category_path, state, skill_score, features,
                   rule_reject_reason
            FROM products_rw
            WHERE COALESCE(features->>'deepseek_policy_recheck_version', '') <> :version
            ORDER BY updated_at ASC
            LIMIT :limit
            """
        ),
        {"limit": max(1, limit), "version": POLICY_RECHECK_VERSION},
    ).mappings()
    return [dict(row) for row in rows]


def _load_target_rows(db, *, target_asins: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    query = text(
        """
        SELECT asin, marketplace, source_query, title, image_url, brand, category,
               price, bsr, reviews, seller_count, landed_cost, est_net_margin,
               brand_share, price_trend, rating, fulfillment_method,
               lithium_battery_warning, margin_source, margin_confidence,
               category_id, category_path, state, skill_score, features,
               rule_reject_reason
        FROM products_rw
        WHERE asin = :asin
        LIMIT 1
        """
    )
    for asin in target_asins:
        row = db.execute(query, {"asin": asin}).mappings().first()
        if row is not None:
            rows.append(dict(row))
    return rows


def _reject_product(db, row: dict[str, Any], screening, reason: str) -> None:
    features = _dict_value(row.get("features"))
    _sanitize_rank_features(row, features)
    features.update(
        {
            "deepseek_score": screening.score,
            "deepseek_verdict": screening.verdict,
            "deepseek_reason": screening.top_reason,
            "score_action": "reject",
            "score_reason": reason,
            "ra_review_required": False,
            "deepseek_policy_recheck_version": POLICY_RECHECK_VERSION,
        }
    )
    json_value = "CAST(:payload AS JSONB)" if _is_postgres(db) else ":payload"
    db.execute(
        text(
            f"""
            INSERT INTO ai_evaluations (
              asin, layer, model, score, verdict, payload, created_at
            )
            VALUES (
              :asin, 'deepseek', :model, :score, :verdict,
              {json_value}, CURRENT_TIMESTAMP
            )
            """
        ),
        {
            "asin": screening.asin,
            "model": rw_deepseek_model(),
            "score": screening.score,
            "verdict": screening.verdict,
            "payload": json.dumps(screening.strict_json, ensure_ascii=False),
        },
    )
    _update_product(
        db,
        asin=screening.asin,
        state=ProductState.AI1_REJECTED.value,
        skill_score=screening.score,
        rule_reject_reason=deepseek_reject_code(screening.top_reason),
        features=features,
    )
    emit_pipeline_event(
        db,
        PipelineEvent(
            asin=screening.asin,
            category_id=str(row["category_id"]) if row.get("category_id") else None,
            event_type="deepseek_policy_recheck",
            stage=ProductState.AI1_REJECTED.value,
            status="processed",
            score_action="reject",
            message=reason,
            payload=screening.strict_json,
        ),
    )


def _mark_checked(db, row: dict[str, Any]) -> None:
    features = _dict_value(row.get("features"))
    _sanitize_rank_features(row, features)
    if features.get("deepseek_policy_recheck_version") == POLICY_RECHECK_VERSION:
        return
    features["deepseek_policy_recheck_version"] = POLICY_RECHECK_VERSION
    _update_product(
        db,
        asin=str(row["asin"]),
        state=str(row.get("state") or ""),
        skill_score=row.get("skill_score"),
        rule_reject_reason=row.get("rule_reject_reason"),
        features=features,
        preserve_state=True,
    )


def _restore_policy_product(db, row: dict[str, Any], screening, reason: str) -> None:
    features = _dict_value(row.get("features"))
    _sanitize_rank_features(row, features)
    features.update(
        {
            "deepseek_score": screening.score,
            "deepseek_verdict": screening.verdict,
            "deepseek_reason": screening.top_reason,
            "score_action": "pending_review",
            "score_reason": reason,
            "ra_review_required": True,
            "deepseek_policy_recheck_version": POLICY_RECHECK_VERSION,
            "policy_recheck_restored": True,
        }
    )
    _update_product(
        db,
        asin=str(row["asin"]),
        state=ProductState.AI1_PASSED.value,
        skill_score=screening.score,
        rule_reject_reason=None,
        features=features,
    )
    emit_pipeline_event(
        db,
        PipelineEvent(
            asin=screening.asin,
            category_id=str(row["category_id"]) if row.get("category_id") else None,
            event_type="deepseek_policy_recheck",
            stage=ProductState.AI1_PASSED.value,
            status="restored",
            score_action="pending_review",
            message=reason,
            payload=screening.strict_json,
        ),
    )


def _sanitize_rank_features(row: dict[str, Any], features: dict[str, Any]) -> None:
    image_url = row.get("image_url")
    if (
        isinstance(image_url, str)
        and image_url.startswith(("http://", "https://"))
        and not isinstance(features.get("image_candidates"), list)
    ):
        features["image_candidates"] = [image_url]
    if not isinstance(features.get("amazon_category_path"), list):
        category_path = _category_path_from_row(row)
        if category_path:
            features["amazon_category_path"] = category_path
    bsr = row.get("bsr")
    subcategory_rank = features.get("subcategory_rank")
    has_leaf_category = bool(features.get("amazon_leaf_category_id"))
    try:
        same_as_bsr = int(subcategory_rank) == int(bsr)
    except (TypeError, ValueError):
        same_as_bsr = False
    if same_as_bsr and not has_leaf_category:
        features["subcategory_rank"] = None
        features["subcategory_rank_source"] = "missing_keepa_salesRanks"
    for key in (
        "bestseller_parent_rank",
        "bestseller_parent_category",
        "category_bestseller_asin",
    ):
        features.pop(key, None)


def _category_path_from_row(row: dict[str, Any]) -> list[str]:
    raw_path = row.get("category_path")
    parts: list[str] = []
    if isinstance(raw_path, str):
        parts = [part.strip() for part in raw_path.split(">") if part.strip()]
    elif isinstance(raw_path, list):
        parts = [str(part).strip() for part in raw_path if str(part).strip()]
    names = [part for part in parts if not part.isdigit()]
    category = row.get("category")
    if isinstance(category, str) and category.strip() and category.strip() not in names:
        names.append(category.strip())
    return names


def _update_product(
    db,
    *,
    asin: str,
    state: str,
    skill_score: Any,
    rule_reject_reason: Any,
    features: dict[str, Any],
    preserve_state: bool = False,
) -> None:
    features_value = "CAST(:features AS JSONB)" if _is_postgres(db) else ":features"
    state_sql = "state = state" if preserve_state else "state = :state"
    reject_reason_sql = (
        "rule_reject_reason = rule_reject_reason"
        if preserve_state
        else "rule_reject_reason = :rule_reject_reason"
    )
    updated_at_sql = "updated_at = updated_at" if preserve_state else "updated_at = CURRENT_TIMESTAMP"
    db.execute(
        text(
            f"""
            UPDATE products_rw
            SET {state_sql},
                skill_score = COALESCE(:skill_score, skill_score),
                {reject_reason_sql},
                features = {features_value},
                {updated_at_sql}
            WHERE asin = :asin
            """
        ),
        {
            "asin": asin,
            "state": state,
            "skill_score": skill_score,
            "rule_reject_reason": rule_reject_reason,
            "features": json.dumps(features, ensure_ascii=False),
        },
    )


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _csv_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    return tuple(part.strip().upper() for part in raw.split(",") if part.strip())


if __name__ == "__main__":
    main()
