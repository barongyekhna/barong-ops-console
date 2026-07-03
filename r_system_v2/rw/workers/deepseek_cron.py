"""Configurable DeepSeek first-pass cron for R-W."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, time as wall_time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    max_runtime_seconds: int
    stopped_by_deadline: bool
    errors: list[str]
    schedule_enabled: bool = False
    window_start: str = "01:00"
    window_end: str = "05:00"
    timezone: str = "Asia/Shanghai"
    window_open: bool = False
    next_window: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "due": self.due,
            "processed": self.processed,
            "passed": self.passed,
            "rejected": self.rejected,
            "pending_review": self.pending_review,
            "interval_seconds": self.interval_seconds,
            "max_runtime_seconds": self.max_runtime_seconds,
            "stopped_by_deadline": self.stopped_by_deadline,
            "errors": self.errors,
            "schedule_enabled": self.schedule_enabled,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "timezone": self.timezone,
            "window_open": self.window_open,
            "next_window": self.next_window,
        }


class DeepSeekPreFilterCron:
    """Runs DeepSeek automatically on rule-passed R-W products."""

    def __init__(
        self,
        *,
        skill: DeepSeekScreeningSkill,
        interval_seconds: int = 300,
        batch_size: int = 100,
        max_runtime_seconds: int = 240,
        schedule_enabled: bool = False,
        window_start: str = "01:00",
        window_end: str = "05:00",
        timezone: str = "Asia/Shanghai",
        scoring_engine: ScoringEngine | None = None,
    ) -> None:
        self.skill = skill
        self.interval_seconds = max(60, int(interval_seconds))
        self.batch_size = max(1, int(batch_size))
        self.max_runtime_seconds = max(10, int(max_runtime_seconds))
        self.schedule_enabled = schedule_enabled
        self.window_start = window_start
        self.window_end = window_end
        self.timezone = timezone
        self.scoring_engine = scoring_engine or ScoringEngine()
        self._last_run_monotonic = 0.0

    def run_due(self, db: Session, *, force: bool = False) -> DeepSeekCronReport:
        window = _window_state(
            enabled=self.schedule_enabled,
            start=self.window_start,
            end=self.window_end,
            timezone_name=self.timezone,
        )
        if not force and not window["open"]:
            return self._empty_report(
                due=False,
                window_open=False,
                next_window=str(window.get("next_window") or ""),
            )
        now = time.monotonic()
        if not force and now - self._last_run_monotonic < self.interval_seconds:
            return self._empty_report(due=False, window_open=bool(window["open"]))
        self._last_run_monotonic = now
        return self.run_once(db, window_deadline_seconds=window.get("seconds_until_close"))

    def run_once(
        self,
        db: Session,
        *,
        window_deadline_seconds: float | None = None,
    ) -> DeepSeekCronReport:
        rows = self._load_pending_products(db)
        passed = rejected = pending_review = 0
        errors: list[str] = []
        runtime_budget = self.max_runtime_seconds
        if window_deadline_seconds is not None:
            runtime_budget = min(runtime_budget, max(0, int(window_deadline_seconds)))
        deadline = time.monotonic() + runtime_budget
        stopped_by_deadline = False
        attempted = 0
        for row in rows:
            if time.monotonic() >= deadline:
                stopped_by_deadline = True
                emit_pipeline_event(
                    db,
                    PipelineEvent(
                        event_type="deepseek_prefilter",
                        stage="deadline",
                        status="stopped",
                        message="DeepSeek 初筛到达运行时间上限，剩余产品留待下轮处理",
                        payload={
                            "max_runtime_seconds": self.max_runtime_seconds,
                            "window_end": self.window_end,
                            "remaining_estimate": max(0, len(rows) - attempted),
                        },
                    ),
                )
                break
            attempted += 1
            asin = str(row["asin"])
            try:
                product = _product_from_row(row)
                screening = self.skill.evaluate(product)
                decision = self.scoring_engine.score_deepseek(screening)
                state = ProductState.AI1_PASSED.value
                passed += 1
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
                features["deepseek_score"] = screening.score
                features["deepseek_verdict"] = screening.verdict
                features["deepseek_reason"] = screening.top_reason
                features["score_action"] = "pending_review"
                features["score_reason"] = screening.top_reason
                features["ra_review_required"] = True
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
                        score_action="pending_review",
                        message=screening.top_reason,
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
            processed=attempted - len(errors),
            passed=passed,
            rejected=rejected,
            pending_review=pending_review,
            interval_seconds=self.interval_seconds,
            max_runtime_seconds=self.max_runtime_seconds,
            stopped_by_deadline=stopped_by_deadline,
            errors=errors,
            schedule_enabled=self.schedule_enabled,
            window_start=self.window_start,
            window_end=self.window_end,
            timezone=self.timezone,
            window_open=True,
        )

    def _empty_report(
        self,
        *,
        due: bool,
        window_open: bool,
        next_window: str | None = None,
    ) -> DeepSeekCronReport:
        return DeepSeekCronReport(
            due=due,
            processed=0,
            passed=0,
            rejected=0,
            pending_review=0,
            interval_seconds=self.interval_seconds,
            max_runtime_seconds=self.max_runtime_seconds,
            stopped_by_deadline=False,
            errors=[],
            schedule_enabled=self.schedule_enabled,
            window_start=self.window_start,
            window_end=self.window_end,
            timezone=self.timezone,
            window_open=window_open,
            next_window=next_window,
        )

    def _load_pending_products(self, db: Session) -> list[dict[str, Any]]:
        rows = db.execute(
            text(
                """
                SELECT asin, marketplace, source_query, title, image_url, brand,
                       category, category_id, category_path, price, bsr, reviews,
                       seller_count, landed_cost, est_net_margin, brand_share,
                       price_trend, rating, fulfillment_method,
                       lithium_battery_warning, margin_source,
                       margin_confidence, features
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
        landed_cost=float(row["landed_cost"]) if row.get("landed_cost") is not None else None,
        est_net_margin=float(row["est_net_margin"]) if row.get("est_net_margin") is not None else None,
        brand_share=float(row.get("brand_share") or 0),
        price_trend=str(row.get("price_trend") or "unknown"),
        rating=float(row["rating"]) if row.get("rating") is not None else None,
        fulfillment_method=str(row["fulfillment_method"]) if row.get("fulfillment_method") else None,
        lithium_battery_warning=bool(row.get("lithium_battery_warning")),
        margin_source=str(row["margin_source"]) if row.get("margin_source") else None,
        margin_confidence=str(row["margin_confidence"]) if row.get("margin_confidence") else None,
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


def _window_state(
    *,
    enabled: bool,
    start: str,
    end: str,
    timezone_name: str,
) -> dict[str, object]:
    if not enabled:
        return {"open": False, "seconds_until_close": 0.0, "next_window": start}
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    start_time = _parse_wall_time(start)
    end_time = _parse_wall_time(end)
    current = now.time().replace(second=0, microsecond=0)
    if start_time <= end_time:
        is_open = start_time <= current < end_time
    else:
        is_open = current >= start_time or current < end_time
    if not is_open:
        return {"open": False, "seconds_until_close": 0.0, "next_window": start}
    close_at = now.replace(
        hour=end_time.hour,
        minute=end_time.minute,
        second=0,
        microsecond=0,
    )
    if close_at <= now:
        close_at = close_at + timedelta(days=1)
    return {
        "open": True,
        "seconds_until_close": max(0.0, (close_at - now).total_seconds()),
        "next_window": None,
    }


def _parse_wall_time(value: str) -> wall_time:
    hour, minute = value.split(":", 1)
    return wall_time(hour=int(hour), minute=int(minute))
