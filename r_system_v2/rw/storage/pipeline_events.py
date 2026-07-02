"""Persistence helpers for R-W live pipeline status and events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class PipelineEvent:
    event_type: str
    stage: str
    status: str
    asin: str | None = None
    category_id: str | None = None
    score_action: str | None = None
    message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def emit_pipeline_event(db: Session, event: PipelineEvent) -> None:
    payload_sql = (
        "CAST(:payload AS JSONB)"
        if db.get_bind().dialect.name == "postgresql"
        else ":payload"
    )
    try:
        db.execute(
            text(
                f"""
                INSERT INTO rw_pipeline_events (
                  asin, category_id, event_type, stage, status,
                  score_action, message, payload, created_at
                )
                VALUES (
                  :asin, :category_id, :event_type, :stage, :status,
                  :score_action, :message, {payload_sql}, :created_at
                )
                """
            ),
            {
                "asin": event.asin,
                "category_id": event.category_id,
                "event_type": event.event_type,
                "stage": event.stage,
                "status": event.status,
                "score_action": event.score_action,
                "message": event.message,
                "payload": json.dumps(event.payload, ensure_ascii=False, default=str),
                "created_at": utc_now(),
            },
        )
    except SQLAlchemyError:
        db.rollback()


def delete_queue_successes(db: Session, asins: list[str]) -> None:
    if not asins:
        return
    statement = text("DELETE FROM enrich_queue WHERE asin IN :asins").bindparams(
        bindparam("asins", expanding=True),
    )
    db.execute(statement, {"asins": asins})


def release_queue_failures(db: Session, errors: dict[str, str]) -> None:
    for asin, error in errors.items():
        db.execute(
            text(
                """
                UPDATE enrich_queue
                SET picked = false,
                    retry_count = retry_count + 1,
                    last_error = :last_error,
                    picked_at = NULL
                WHERE asin = :asin
                """
            ),
            {"asin": asin, "last_error": error[:500]},
        )


def upsert_worker_status(
    db: Session,
    *,
    worker_name: str,
    status: str,
    loop_interval_seconds: int,
    deepseek_interval_seconds: int,
    processed_total: int,
    failed_total: int,
    queue_pending: int,
    selected_categories: list[str],
    payload: dict[str, Any],
    last_error: str | None = None,
    cycle_started_at: datetime | None = None,
    cycle_finished_at: datetime | None = None,
) -> None:
    now = utc_now()
    selected_categories_json = json.dumps(selected_categories, ensure_ascii=False, default=str)
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    values = {
        "worker_name": worker_name,
        "status": status,
        "pid": payload.get("pid"),
        "loop_interval_seconds": loop_interval_seconds,
        "deepseek_interval_seconds": deepseek_interval_seconds,
        "last_heartbeat_at": now,
        "last_cycle_started_at": cycle_started_at,
        "last_cycle_finished_at": cycle_finished_at,
        "last_error": last_error,
        "processed_total": processed_total,
        "failed_total": failed_total,
        "queue_pending": queue_pending,
        "selected_categories": selected_categories_json,
        "payload": payload_json,
        "updated_at": now,
    }
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text(
                """
                INSERT INTO rw_worker_status (
                  worker_name, status, pid, loop_interval_seconds,
                  deepseek_interval_seconds, last_heartbeat_at,
                  last_cycle_started_at, last_cycle_finished_at, last_error,
                  processed_total, failed_total, queue_pending,
                  selected_categories, payload, updated_at
                )
                VALUES (
                  :worker_name, :status, :pid, :loop_interval_seconds,
                  :deepseek_interval_seconds, :last_heartbeat_at,
                  :last_cycle_started_at, :last_cycle_finished_at, :last_error,
                  :processed_total, :failed_total, :queue_pending,
                  CAST(:selected_categories AS JSONB), CAST(:payload AS JSONB),
                  :updated_at
                )
                ON CONFLICT (worker_name) DO UPDATE SET
                  status = EXCLUDED.status,
                  pid = EXCLUDED.pid,
                  loop_interval_seconds = EXCLUDED.loop_interval_seconds,
                  deepseek_interval_seconds = EXCLUDED.deepseek_interval_seconds,
                  last_heartbeat_at = EXCLUDED.last_heartbeat_at,
                  last_cycle_started_at = EXCLUDED.last_cycle_started_at,
                  last_cycle_finished_at = EXCLUDED.last_cycle_finished_at,
                  last_error = EXCLUDED.last_error,
                  processed_total = EXCLUDED.processed_total,
                  failed_total = EXCLUDED.failed_total,
                  queue_pending = EXCLUDED.queue_pending,
                  selected_categories = EXCLUDED.selected_categories,
                  payload = EXCLUDED.payload,
                  updated_at = EXCLUDED.updated_at
                """
            ),
            values,
        )
        return

    updated = db.execute(
        text(
            """
            UPDATE rw_worker_status
            SET status = :status,
                pid = :pid,
                loop_interval_seconds = :loop_interval_seconds,
                deepseek_interval_seconds = :deepseek_interval_seconds,
                last_heartbeat_at = :last_heartbeat_at,
                last_cycle_started_at = :last_cycle_started_at,
                last_cycle_finished_at = :last_cycle_finished_at,
                last_error = :last_error,
                processed_total = :processed_total,
                failed_total = :failed_total,
                queue_pending = :queue_pending,
                selected_categories = :selected_categories,
                payload = :payload,
                updated_at = :updated_at
            WHERE worker_name = :worker_name
            """
        ),
        values,
    )
    if updated.rowcount:
        return
    db.execute(
        text(
            """
            INSERT INTO rw_worker_status (
              worker_name, status, pid, loop_interval_seconds,
              deepseek_interval_seconds, last_heartbeat_at,
              last_cycle_started_at, last_cycle_finished_at, last_error,
              processed_total, failed_total, queue_pending,
              selected_categories, payload, updated_at
            )
            VALUES (
              :worker_name, :status, :pid, :loop_interval_seconds,
              :deepseek_interval_seconds, :last_heartbeat_at,
              :last_cycle_started_at, :last_cycle_finished_at, :last_error,
              :processed_total, :failed_total, :queue_pending,
              :selected_categories, :payload, :updated_at
            )
            """
        ),
        values,
    )


def runtime_overview(db: Session, *, event_limit: int = 50) -> dict[str, Any]:
    worker_rows = _fetch_mappings(
        db,
        """
        SELECT worker_name, status, loop_interval_seconds,
               deepseek_interval_seconds, last_heartbeat_at,
               last_cycle_started_at, last_cycle_finished_at, last_error,
               processed_total, failed_total, queue_pending,
               selected_categories, payload, updated_at
        FROM rw_worker_status
        ORDER BY worker_name
        """,
    )
    events = _fetch_mappings(
        db,
        """
        SELECT asin, category_id, event_type, stage, status, score_action,
               message, payload, created_at
        FROM rw_pipeline_events
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"limit": event_limit},
    )
    counts = _fetch_one(
        db,
        """
        SELECT
          COUNT(*) AS total_products,
          COALESCE(SUM(CASE WHEN state = 'ai1_passed' THEN 1 ELSE 0 END), 0) AS passed,
          COALESCE(SUM(CASE WHEN state IN ('ai1_rejected', 'rejected') THEN 1 ELSE 0 END), 0) AS rejected,
          COALESCE(SUM(CASE WHEN state = 'rule_passed' THEN 1 ELSE 0 END), 0) AS pending_review,
          MAX(updated_at) AS last_product_update
        FROM products_rw
        """,
    )
    queue = _fetch_one(
        db,
        """
        SELECT
          COUNT(*) AS total,
          COALESCE(SUM(CASE WHEN picked THEN 1 ELSE 0 END), 0) AS picked,
          COALESCE(SUM(CASE WHEN NOT picked THEN 1 ELSE 0 END), 0) AS pending
        FROM enrich_queue
        """,
    )
    return {
        "workers": worker_rows,
        "events": events,
        "counts": counts or {},
        "queue": queue or {},
    }


def _fetch_mappings(
    db: Session,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in db.execute(text(sql), params or {}).mappings().all()]
    except SQLAlchemyError:
        db.rollback()
        return []


def _fetch_one(
    db: Session,
    sql: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        row = db.execute(text(sql), params or {}).mappings().first()
    except SQLAlchemyError:
        db.rollback()
        return None
    return dict(row) if row else None
