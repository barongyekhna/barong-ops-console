"""Configurable DeepSeek first-pass cron for R-W."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.core.models import NormalizedProduct, ProductState
from r_system_v2.rw.scoring_engine import ScoringEngine
from r_system_v2.rw.storage.pipeline_events import PipelineEvent, emit_pipeline_event


@dataclass(frozen=True)
class DeepSeekCronReport:
    due: bool
    processed: int
    passed: int
    rejected: int
    pending_review: int
    interval_seconds: int
    errors: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "due": self.due,
            "processed": self.processed,
            "passed": self.passed,
            "rejected": self.rejected,
            "pending_review": self.pending_review,
            "interval_seconds": self.interval_seconds,
            "errors": self.errors,
        }


class DeepSeekPreFilterCron:
    """Runs DeepSeek automatically on rule-passed R-W products."""

    def __init__(
        self,
        *,
        skill: DeepSeekScreeningSkill,
        interval_seconds: int = 300,
        batch_size: int = 100,
        scoring_engine: ScoringEngine | None = None,
    ) -> None:
        self.skill = skill
        self.interval_seconds = max(60, int(interval_seconds))
        self.batch_size = max(1, int(batch_size))
        self.scoring_engine = scoring_engine or ScoringEngine()
        self._last_run_monotonic = 0.0

    def run_due(self, db: Session, *, force: bool = False) -> DeepSeekCronReport:
        now = time.monotonic()
        if not force and now - self._last_run_monotonic < self.interval_seconds:
            return DeepSeekCronReport(
                due=False,
                processed=0,
                passed=0,
                rejected=0,
                pending_review=0,
                interval_seconds=self.interval_seconds,
                errors=[],
            )
        self._last_run_monotonic = now
        return self.run_once(db)

    def run_once(self, db: Session) -> DeepSeekCronReport:
        rows = self._load_pending_products(db)
        passed = rejected = pending_review = 0
        errors: list[str] = []
        for row in rows:
            asin = str(row["asin"])
            try:
                product = _product_from_row(row)
                screening = self.skill.evaluate(product)
                decision = self.scoring_engine.score_deepseek(screening)
                if decision.action == "pass":
                    state = ProductState.AI1_PASSED.value
                    passed += 1
                elif decision.action == "reject":
                    state = ProductState.AI1_REJECTED.value
                    rejected += 1
                else:
                    state = ProductState.RULE_PASSED.value
                    pending_review += 1
                json_value = "CAST(:payload AS JSONB)" if _is_postgres(db) else ":payload"
                db.execute(
                    text(
                        f"""
                        INSERT INTO ai_evaluations (
                          asin, layer, model, score, verdict, payload, created_at
                        )
                        VALUES (
                          :asin, 'deepseek', 'deepseek-chat',
                          :score, :verdict, {json_value}, CURRENT_TIMESTAMP
                        )
                        """
                    ),
                    {
                        "asin": screening.asin,
                        "score": screening.score,
                        "verdict": screening.verdict,
                        "payload": json.dumps(screening.strict_json, ensure_ascii=False),
                    },
                )
                features = _dict_value(row.get("features"))
                features["score_action"] = decision.action
                features["score_reason"] = decision.reason
                features_value = (
                    "CAST(:features AS JSONB)" if _is_postgres(db) else ":features"
                )
                db.execute(
                    text(
                        f"""
                        UPDATE products_rw
                        SET state = :state,
                            skill_score = :skill_score,
                            features = {features_value},
                            updated_at = CURRENT_TIMESTAMP
                        WHERE asin = :asin
                        """
                    ),
                    {
                        "asin": screening.asin,
                        "state": state,
                        "skill_score": screening.score,
                        "features": json.dumps(features, ensure_ascii=False),
                    },
                )
                emit_pipeline_event(
                    db,
                    PipelineEvent(
                        asin=screening.asin,
                        category_id=str(row["category_id"]) if row.get("category_id") else None,
                        event_type="deepseek_prefilter",
                        stage=state,
                        status="processed",
                        score_action=decision.action,
                        message=decision.reason,
                        payload=decision.to_dict(),
                    ),
                )
            except Exception as exc:  # pragma: no cover - runtime guard.
                errors.append(f"{asin}: {exc}")
                emit_pipeline_event(
                    db,
                    PipelineEvent(
                        asin=asin,
                        category_id=str(row["category_id"]) if row.get("category_id") else None,
                        event_type="deepseek_prefilter",
                        stage="rule_passed",
                        status="failed",
                        message=str(exc),
                    ),
                )
        return DeepSeekCronReport(
            due=True,
            processed=len(rows) - len(errors),
            passed=passed,
            rejected=rejected,
            pending_review=pending_review,
            interval_seconds=self.interval_seconds,
            errors=errors,
        )

    def _load_pending_products(self, db: Session) -> list[dict[str, Any]]:
        rows = db.execute(
            text(
                """
                SELECT asin, marketplace, source_query, title, image_url, brand,
                       category, category_id, category_path, price, bsr, reviews,
                       seller_count, landed_cost, est_net_margin, brand_share,
                       price_trend, rating, features
                FROM products_rw p
                WHERE p.state = 'rule_passed'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM ai_evaluations a
                    WHERE a.asin = p.asin AND a.layer = 'deepseek'
                  )
                ORDER BY p.updated_at ASC
                LIMIT :limit
                """
            ),
            {"limit": self.batch_size},
        ).mappings()
        return [dict(row) for row in rows]


def _product_from_row(row: dict[str, Any]) -> NormalizedProduct:
    category_path = row.get("category_path")
    if isinstance(category_path, str):
        parsed_category_path = [part for part in category_path.split(">") if part]
    elif isinstance(category_path, list):
        parsed_category_path = [str(part) for part in category_path]
    else:
        parsed_category_path = []
    return NormalizedProduct(
        asin=str(row["asin"]),
        source_query=str(row.get("source_query") or row.get("title") or row["asin"]),
        marketplace=str(row.get("marketplace") or "US"),
        title=str(row.get("title") or row["asin"]),
        image_url=str(row["image_url"]) if row.get("image_url") else None,
        brand=str(row.get("brand") or "Unknown"),
        category=str(row.get("category") or "Unknown"),
        price=float(row.get("price") or 0),
        bsr=int(row.get("bsr") or 0),
        reviews=int(row.get("reviews") or 0),
        seller_count=int(row.get("seller_count") or 0),
        landed_cost=float(row.get("landed_cost") or 0),
        est_net_margin=float(row.get("est_net_margin") or 0),
        brand_share=float(row.get("brand_share") or 0),
        price_trend=str(row.get("price_trend") or "unknown"),
        rating=float(row["rating"]) if row.get("rating") is not None else None,
        category_id=str(row["category_id"]) if row.get("category_id") else None,
        category_path=parsed_category_path,
        state=ProductState.RULE_PASSED,
        features=_dict_value(row.get("features")),
    )


def _is_postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}
