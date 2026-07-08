"""24/7 R-W realtime engine."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.category.category_tree import (
    apply_selected_categories,
    is_holiday_category_id,
    load_category_tree,
    runnable_selected_category_ids,
)
from r_system_v2.rw.core.keepa_buffer_queue import KeepaBufferQueue
from r_system_v2.rw.core.models import IngestionRecord
from r_system_v2.rw.core.pipeline_runner import PipelineRunner
from r_system_v2.rw.providers.keepa_provider import (
    KEEPA_TOKENS_PER_DISCOVERY,
    KEEPA_TOKENS_PER_PRODUCT,
    KEEPA_TOKEN_RESERVE,
    MAX_REQUESTS_PER_MINUTE,
    KeepaConfigurationError,
    KeepaProvider,
    KeepaResponseError,
    _resolve_keepa_category_id,
)
from r_system_v2.rw.scheduler.category_scheduler import CategoryScheduler
from r_system_v2.rw.storage.batch_writer import SQLAlchemyBatchWriter
from r_system_v2.rw.storage.pipeline_events import (
    PipelineEvent,
    delete_queue_successes,
    emit_pipeline_event,
    release_queue_failures,
    upsert_worker_status,
    utc_now,
)
from r_system_v2.rw.storage.discovery_state import (
    load_discovery_cursor,
    save_discovery_cursor,
)
from r_system_v2.rw.storage.runtime_settings import load_runtime_settings


@dataclass(frozen=True)
class RealtimeCycleReport:
    status: str
    selected_categories: list[str]
    claimed: int
    processed: int
    failed: int
    queue_pending: int
    keepa_tokens_left: int | None
    scheduler: dict[str, object]
    deepseek: dict[str, object]
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "selected_categories": self.selected_categories,
            "claimed": self.claimed,
            "processed": self.processed,
            "failed": self.failed,
            "queue_pending": self.queue_pending,
            "keepa_tokens_left": self.keepa_tokens_left,
            "scheduler": self.scheduler,
            "deepseek": self.deepseek,
            "error": self.error,
        }


class RwRealtimeEngine:
    """Runs Keepa, category scheduling, scoring, storage, and UI status updates."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        provider: KeepaProvider,
        deepseek_skill: DeepSeekScreeningSkill,
        org_id: str,
        loop_interval_seconds: int | None = None,
        keepa_batch_size: int | None = None,
        deepseek_interval_seconds: int | None = None,
        deepseek_batch_size: int | None = None,
        enforce_wall_clock_rate: bool | None = None,
        discovery_enabled: bool | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.deepseek_skill = deepseek_skill
        self.org_id = org_id
        self.loop_interval_seconds = loop_interval_seconds or _int_env("RW_KEEPA_LOOP_SECONDS", 60)
        self.keepa_batch_size = min(
            keepa_batch_size or _int_env("RW_KEEPA_BATCH_SIZE", MAX_REQUESTS_PER_MINUTE),
            MAX_REQUESTS_PER_MINUTE,
        )
        self.deepseek_interval_seconds = deepseek_interval_seconds or _int_env(
            "RW_DEEPSEEK_INTERVAL_SECONDS",
            300,
        )
        self.keepa_429_backoff_seconds = _int_env("RW_KEEPA_429_BACKOFF_SECONDS", 60)
        self.discovery_categories_per_cycle = max(
            20,
            _int_env("RW_KEEPA_DISCOVERY_CATEGORIES_PER_CYCLE", 20),
        )
        self.discovery_enabled = (
            _bool_env("RW_KEEPA_DISCOVERY_ENABLED", True)
            if discovery_enabled is None
            else discovery_enabled
        )
        enforce = (
            _bool_env("RW_KEEPA_ENFORCE_WALL_CLOCK", True)
            if enforce_wall_clock_rate is None
            else enforce_wall_clock_rate
        )
        self.scheduler = CategoryScheduler()
        del deepseek_batch_size
        writer = SQLAlchemyBatchWriter(session_factory)
        self.buffer_queue = KeepaBufferQueue(writer=writer.write)
        self.pipeline_runner = PipelineRunner(
            provider=provider,
            buffer_queue=self.buffer_queue,
            deepseek_skill=deepseek_skill,
            deepseek_inline=True,
            enforce_wall_clock_rate=enforce,
        )
        self.discovery_cursor = 0
        self.discovery_blocked_until: dict[str, datetime] = {}
        self.discovery_error_cooldown_seconds = _int_env(
            "RW_KEEPA_DISCOVERY_ERROR_COOLDOWN_SECONDS",
            21_600,
        )
        self.max_discovery_requests_per_cycle = max(
            1,
            min(
                MAX_REQUESTS_PER_MINUTE,
                _int_env("RW_KEEPA_MAX_DISCOVERY_REQUESTS_PER_CYCLE", 3),
            ),
        )
        self.image_backfill_per_cycle = max(
            0,
            min(
                MAX_REQUESTS_PER_MINUTE,
                _int_env("RW_PRODUCT_IMAGE_BACKFILL_PER_CYCLE", 12),
            ),
        )
        # Image backfill is a hard requirement: ~12k legacy products still carry
        # the broken /images/P/ ASIN-fallback and must be re-fetched to a real
        # Keepa image. When priority is on and a backlog remains, hand most of
        # the per-cycle token budget to backfill and keep only a small trickle
        # of new-product fetches; once the backlog drains, flip to full-speed
        # new ingestion but keep a floor so stragglers never stay image-less.
        self.image_backfill_priority = _bool_env("RW_IMAGE_BACKFILL_PRIORITY", True)
        self.image_backlog_active = True
        self.new_fetch_floor = max(0, _int_env("RW_KEEPA_NEW_FETCH_FLOOR", 2))
        self.image_min_floor = max(0, _int_env("RW_IMAGE_BACKFILL_MIN_FLOOR", 1))
        self.discovery_request_interval_seconds = max(
            0,
            _int_env("RW_KEEPA_DISCOVERY_REQUEST_INTERVAL_SECONDS", 3),
        )
        self.keepa_backoff_until: datetime | None = None
        self.adaptive_fetch_cap = self.keepa_batch_size
        self.processed_total = 0
        self.failed_total = 0

    def run_forever(self, *, should_stop: Callable[[], bool]) -> None:
        while not should_stop():
            started = time.monotonic()
            self.run_cycle()
            elapsed = time.monotonic() - started
            sleep_for = max(1.0, self.loop_interval_seconds - elapsed)
            deadline = time.monotonic() + sleep_for
            while not should_stop() and time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))

    def run_cycle(self) -> RealtimeCycleReport:
        cycle_started_at = utc_now()
        with self.session_factory() as db:
            selected_categories = self._selected_categories(db)
            try:
                report = self._run_cycle(db, selected_categories, cycle_started_at)
                db.commit()
                return report
            except Exception as exc:  # pragma: no cover - production guard.
                db.rollback()
                report = RealtimeCycleReport(
                    status="failed",
                    selected_categories=selected_categories,
                    claimed=0,
                    processed=0,
                    failed=1,
                    queue_pending=0,
                    keepa_tokens_left=None,
                    scheduler={},
                    deepseek=self._deepseek_realtime_report(processed=0),
                    error=str(exc),
                )
                self.failed_total += 1
                self._write_status(
                    db,
                    report=report,
                    cycle_started_at=cycle_started_at,
                    cycle_finished_at=utc_now(),
                    last_error=str(exc),
                )
                db.commit()
                return report

    def _run_cycle(
        self,
        db: Session,
        selected_categories: list[str],
        cycle_started_at: datetime,
    ) -> RealtimeCycleReport:
        self._reload_runtime_settings(db)
        stale_released = self.scheduler.release_stale_picks(
            db,
            older_than_seconds=self.loop_interval_seconds * 3,
        )
        processed_purged = self.scheduler.purge_processed_products(db)
        db.commit()
        if self.keepa_backoff_until and utc_now() < self.keepa_backoff_until:
            deepseek = self._deepseek_realtime_report(processed=0)
            report = RealtimeCycleReport(
                status="backoff",
                selected_categories=selected_categories,
                claimed=0,
                processed=int(deepseek.get("processed", 0)),
                failed=0,
                queue_pending=self.scheduler.pending_count(db, selected_categories),
                keepa_tokens_left=None,
                scheduler={
                    "reason": "keepa_429_backoff",
                    "backoff_until": self.keepa_backoff_until.isoformat(),
                    "stale_released": stale_released,
                    "processed_purged": processed_purged,
                },
                deepseek=deepseek,
                error="keepa_429_backoff",
            )
            emit_pipeline_event(
                db,
                PipelineEvent(
                    event_type="keepa_cycle",
                    stage="backoff",
                    status="blocked",
                    message="Keepa 429 backoff active",
                    payload=report.to_dict(),
                ),
            )
            self._write_status(
                db,
                report=report,
                cycle_started_at=cycle_started_at,
                cycle_finished_at=utc_now(),
                last_error="keepa_429_backoff",
            )
            return report
        try:
            keepa_status = self.provider.status()
        except (KeepaConfigurationError, KeepaResponseError, TimeoutError, OSError) as exc:
            deepseek = self._deepseek_realtime_report(processed=0)
            report = RealtimeCycleReport(
                status="blocked",
                selected_categories=selected_categories,
                claimed=0,
                processed=0,
                failed=0,
                queue_pending=self.scheduler.pending_count(db, selected_categories),
                keepa_tokens_left=None,
                scheduler={"reason": str(exc)},
                deepseek=deepseek,
                error=str(exc),
            )
            emit_pipeline_event(
                db,
                PipelineEvent(
                    event_type="keepa_cycle",
                    stage="blocked",
                    status="blocked",
                    message=str(exc),
                    payload=report.to_dict(),
                ),
            )
            self._write_status(
                db,
                report=report,
                cycle_started_at=cycle_started_at,
                cycle_finished_at=utc_now(),
                last_error=str(exc),
            )
            return report
        except Exception as exc:
            deepseek = self._deepseek_realtime_report(processed=0)
            report = RealtimeCycleReport(
                status="blocked",
                selected_categories=selected_categories,
                claimed=0,
                processed=0,
                failed=0,
                queue_pending=self.scheduler.pending_count(db, selected_categories),
                keepa_tokens_left=None,
                scheduler={"reason": "keepa_status_unavailable"},
                deepseek=deepseek,
                error=str(exc),
            )
            emit_pipeline_event(
                db,
                PipelineEvent(
                    event_type="keepa_cycle",
                    stage="blocked",
                    status="blocked",
                    message="Keepa status unavailable",
                    payload=report.to_dict(),
                ),
            )
            self._write_status(
                db,
                report=report,
                cycle_started_at=cycle_started_at,
                cycle_finished_at=utc_now(),
                last_error=str(exc),
            )
            return report

        tokens_left = int(keepa_status.tokens_left)
        # Budget the whole cycle in REAL tokens. Every /product fetch AND every
        # image backfill costs KEEPA_TOKENS_PER_PRODUCT; a discovery /query costs
        # KEEPA_TOKENS_PER_DISCOVERY. Counting each as 1 (the old bug) let the
        # cycle claim ~2x what the pool could pay -> 429 -> adaptive collapse.
        usable_tokens = max(0, tokens_left - KEEPA_TOKEN_RESERVE)
        total_product_ops = usable_tokens // KEEPA_TOKENS_PER_PRODUCT
        if self.image_backfill_priority and self.image_backlog_active:
            # Backlog present: keep new fetches to a trickle, give the rest to
            # image backfill (allocated further below).
            new_fetch_target = min(self.new_fetch_floor, total_product_ops)
        else:
            # Backlog drained: full-speed new ingestion, but reserve a small
            # floor so any straggler that landed on a fallback still gets fixed.
            new_fetch_target = max(0, total_product_ops - self.image_min_floor)
        requested = min(
            self.keepa_batch_size,
            self.adaptive_fetch_cap,
            new_fetch_target,
        )
        records, scheduler_report = self.scheduler.claim(
            db,
            selected_categories=selected_categories,
            requested_tokens=requested,
        )
        if records:
            db.commit()
            try:
                pipeline = self.pipeline_runner.run(records)
            except Exception as exc:
                release_queue_failures(
                    db,
                    {record.asin: str(exc) for record in records},
                )
                db.commit()
                raise
            delete_queue_successes(db, pipeline.processed_asins)
            release_queue_failures(db, pipeline.failed_asins)
            if _has_keepa_429(pipeline.failed_asins):
                self.keepa_backoff_until = utc_now() + timedelta(
                    seconds=self.keepa_429_backoff_seconds,
                )
                self.adaptive_fetch_cap = max(1, min(self.adaptive_fetch_cap, max(1, requested // 2)))
            elif pipeline.failed == 0 and pipeline.processed > 0:
                self.adaptive_fetch_cap = min(
                    self.keepa_batch_size,
                    self.adaptive_fetch_cap + 1,
                )
            score_actions = self._score_actions_for_asins(db, [record.asin for record in records])
            for record in records:
                status = "failed" if record.asin in pipeline.failed_asins else "stored"
                emit_pipeline_event(
                    db,
                    PipelineEvent(
                        asin=record.asin,
                        category_id=record.category_id,
                        event_type="keepa_fetch",
                        stage="deepseek_realtime" if status == "stored" else "rule_prefilter",
                        status=status,
                        score_action=score_actions.get(record.asin)
                        if status == "stored"
                        else "reject",
                        message=pipeline.failed_asins.get(record.asin)
                        if status == "failed"
                        else None,
                        payload={
                            "marketplace": record.marketplace,
                            "source_query": record.source_query,
                        },
                    ),
                )
            processed = pipeline.processed
            failed = pipeline.failed
        else:
            processed = 0
            failed = 0
        tokens_after_fetch = max(
            0,
            usable_tokens - KEEPA_TOKENS_PER_PRODUCT * len(records),
        )
        discovery_token_budget = tokens_after_fetch // KEEPA_TOKENS_PER_DISCOVERY
        discovery_budget = max(
            0,
            min(
                self.discovery_categories_per_cycle,
                self.max_discovery_requests_per_cycle,
                discovery_token_budget,
            ),
        )
        if (
            self.discovery_enabled
            and requested > 0
            and len(records) < requested
            and discovery_budget > 0
        ):
            self._discover_if_needed(
                db,
                selected_categories,
                requested,
                max_category_attempts=discovery_budget,
            )
        tokens_after_discovery = max(
            0,
            tokens_after_fetch - KEEPA_TOKENS_PER_DISCOVERY * discovery_budget,
        )
        image_backfill_budget = min(
            self.image_backfill_per_cycle,
            tokens_after_discovery // KEEPA_TOKENS_PER_PRODUCT,
        )
        image_backfill = (
            self._backfill_missing_product_images(db, limit=image_backfill_budget)
            if image_backfill_budget > 0
            else {"requested": 0, "updated": 0, "skipped": 0, "failed": 0}
        )
        if image_backfill_budget > 0:
            # `requested` == rows still matching the missing-image query. A full
            # page means the backlog persists; fewer rows than we asked for means
            # it is essentially drained -> next cycle flips to full new ingestion.
            self.image_backlog_active = (
                int(image_backfill.get("requested", 0)) >= image_backfill_budget
            )
        scheduler_payload = scheduler_report.to_dict()
        scheduler_payload["stale_released"] = stale_released
        scheduler_payload["processed_purged"] = processed_purged
        scheduler_payload["image_backfill"] = image_backfill
        deepseek = self._deepseek_realtime_report(processed=processed)
        self.processed_total += processed
        self.failed_total += failed
        queue_pending = self.scheduler.pending_count(db, selected_categories)
        status = "active" if records else "idle"
        report = RealtimeCycleReport(
            status=status,
            selected_categories=selected_categories,
            claimed=len(records),
            processed=processed,
            failed=failed,
            queue_pending=queue_pending,
            keepa_tokens_left=int(keepa_status.tokens_left),
            scheduler=scheduler_payload,
            deepseek=deepseek,
        )
        report.scheduler["adaptive_fetch_cap"] = self.adaptive_fetch_cap
        self._write_status(
            db,
            report=report,
            cycle_started_at=cycle_started_at,
            cycle_finished_at=utc_now(),
        )
        return report

    def _discover_if_needed(
        self,
        db: Session,
        selected_categories: list[str],
        requested_tokens: int,
        *,
        max_category_attempts: int,
    ) -> None:
        pending = self.scheduler.pending_count(db, selected_categories)
        if pending >= requested_tokens or not selected_categories:
            return
        missing = requested_tokens - pending
        attempted = 0
        now = utc_now()
        for offset in range(len(selected_categories)):
            if missing <= 0:
                break
            if attempted >= max_category_attempts:
                break
            category_index = (self.discovery_cursor + offset) % len(selected_categories)
            category_id = selected_categories[category_index]
            self.discovery_cursor = (category_index + 1) % len(selected_categories)
            blocked_until = self.discovery_blocked_until.get(category_id)
            if blocked_until and blocked_until > now:
                continue
            if blocked_until:
                self.discovery_blocked_until.pop(category_id, None)
            attempted += 1
            page = load_discovery_cursor(db, category_id)
            try:
                self.pipeline_runner.wait_keepa_turn()
                asins = self.provider.discover_asins(
                    category_id=category_id,
                    limit=min(missing, self.keepa_batch_size),
                    page=page,
                )
            except Exception as exc:  # category mapping or API issue; keep current queue running.
                if _has_keepa_429({"discovery": str(exc)}):
                    self.keepa_backoff_until = utc_now() + timedelta(
                        seconds=self.keepa_429_backoff_seconds,
                    )
                else:
                    self.discovery_blocked_until[category_id] = utc_now() + timedelta(
                        seconds=self.discovery_error_cooldown_seconds,
                    )
                emit_pipeline_event(
                    db,
                    PipelineEvent(
                        category_id=category_id,
                        event_type="keepa_discovery",
                        stage="discovery",
                        status="blocked",
                        message=str(exc),
                    ),
                )
                db.commit()
                if self.keepa_backoff_until:
                    break
                continue
            inserted = self.scheduler.enqueue_discovered(
                db,
                category_id=category_id,
                asins=asins,
            )
            next_page = page + (2 if inserted == 0 else 1)
            save_discovery_cursor(db, category_id, next_page)
            missing -= inserted
            emit_pipeline_event(
                db,
                PipelineEvent(
                    category_id=category_id,
                    event_type="keepa_discovery",
                    stage="discovery",
                    status="queued",
                    payload={
                        "discovered": len(asins),
                        "inserted": inserted,
                        "cursor": page,
                        "next_cursor": next_page,
                    },
                ),
            )
            db.commit()

    def _backfill_missing_product_images(self, db: Session, *, limit: int) -> dict[str, int]:
        if limit <= 0:
            return {"requested": 0, "updated": 0, "skipped": 0, "failed": 0}
        rows = db.execute(
            text(
                """
                SELECT asin, title, image_url, features
                FROM products_rw
                WHERE image_url IS NULL
                   OR image_url = ''
                   OR image_url LIKE '%/images/P/%'
                   OR COALESCE(features->>'image_candidates', '') LIKE '%/images/P/%'
                ORDER BY updated_at DESC NULLS LAST, asin ASC
                LIMIT :limit
                """
            ),
            {"limit": max(1, min(int(limit), MAX_REQUESTS_PER_MINUTE))},
        ).mappings().all()
        updated = 0
        skipped = 0
        failed = 0
        for row in rows:
            asin = str(row["asin"])
            try:
                self.pipeline_runner.wait_keepa_turn()
                keepa_data = self.provider.fetch_product(
                    asin,
                    source_query=str(row.get("title") or asin),
                )
            except Exception as exc:
                failed += 1
                if _has_keepa_429({asin: str(exc)}):
                    self.keepa_backoff_until = utc_now() + timedelta(
                        seconds=self.keepa_429_backoff_seconds,
                    )
                    break
                continue

            image_candidates = _real_keepa_image_candidates(keepa_data.image_candidates)
            if not image_candidates:
                skipped += 1
                continue

            features = row.get("features")
            next_features = dict(features) if isinstance(features, dict) else {}
            next_features["image_candidates"] = image_candidates
            next_features["image_backfill_source"] = "rw_worker_keepa_product_images"
            next_features["image_backfill_candidate_count"] = len(image_candidates)
            next_features["image_backfilled_at"] = utc_now().isoformat()
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
            emit_pipeline_event(
                db,
                PipelineEvent(
                    asin=asin,
                    event_type="product_image_backfill",
                    stage="keepa_image_backfill",
                    status="updated",
                    message="Replaced transparent ASIN fallback image with Keepa image candidates",
                    payload={"candidate_count": len(image_candidates)},
                ),
            )
            updated += 1
        return {
            "requested": len(rows),
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
        }

    def _write_status(
        self,
        db: Session,
        *,
        report: RealtimeCycleReport,
        cycle_started_at: datetime,
        cycle_finished_at: datetime,
        last_error: str | None = None,
    ) -> None:
        upsert_worker_status(
            db,
            worker_name="r-w-keepa-daemon",
            status=report.status,
            loop_interval_seconds=self.loop_interval_seconds,
            deepseek_interval_seconds=self.deepseek_interval_seconds,
            processed_total=self.processed_total,
            failed_total=self.failed_total,
            queue_pending=report.queue_pending,
            selected_categories=report.selected_categories,
            payload={
                "pid": os.getpid(),
                "cycle": report.to_dict(),
            },
            last_error=last_error or report.error,
            cycle_started_at=cycle_started_at,
            cycle_finished_at=cycle_finished_at,
        )

    def _reload_runtime_settings(self, db: Session) -> None:
        settings = load_runtime_settings(db)
        self.keepa_batch_size = min(settings.keepa_batch_size, MAX_REQUESTS_PER_MINUTE)
        self.adaptive_fetch_cap = min(self.adaptive_fetch_cap, self.keepa_batch_size)
        self.discovery_categories_per_cycle = max(
            settings.discovery_categories_per_cycle,
            _int_env("RW_KEEPA_MIN_DISCOVERY_CATEGORIES_PER_CYCLE", 20),
        )
        self.keepa_429_backoff_seconds = min(settings.keepa_429_backoff_seconds, 60)

    def _selected_categories(self, db: Session) -> list[str]:
        settings = load_runtime_settings(db)
        category_tree = apply_selected_categories(
            load_category_tree(),
            settings.selected_categories,
        )
        return _runnable_categories(runnable_selected_category_ids(category_tree))

    def _deepseek_realtime_report(self, *, processed: int) -> dict[str, object]:
        return {
            "mode": "realtime_inline",
            "controls_execution": False,
            "schedule_enabled": False,
            "processed": processed,
            "translation": "realtime_per_keepa_product",
            "screening": "realtime_after_rule_pass",
            "hard_rule_reject_skips_deepseek": True,
        }

    def _score_actions_for_asins(self, db: Session, asins: list[str]) -> dict[str, str]:
        if not asins:
            return {}
        statement = text(
            """
            SELECT asin, state, features
            FROM products_rw
            WHERE asin IN :asins
            """
        )
        rows = db.execute(
            statement.bindparams(bindparam("asins", expanding=True)),
            {"asins": asins},
        ).mappings().all()
        return {
            str(row["asin"]): _score_action_from_state(str(row["state"]), row.get("features"))
            for row in rows
        }


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _runnable_categories(category_ids: list[str]) -> list[str]:
    """Keep only selected nodes that can map to a real Keepa category."""

    runnable: list[str] = []
    for category_id in category_ids:
        if not is_holiday_category_id(category_id) and _resolve_keepa_category_id(category_id) is None:
            continue
        if category_id not in runnable:
            runnable.append(category_id)
    return runnable


def _real_keepa_image_candidates(candidates: list[str]) -> list[str]:
    real_images: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        cleaned = candidate.strip()
        if "/images/I/" not in cleaned:
            continue
        if cleaned not in real_images:
            real_images.append(cleaned)
    return real_images


def _has_keepa_429(errors: dict[str, str]) -> bool:
    return any("429" in message or "Too Many Requests" in message for message in errors.values())


def _score_action_from_state(state: str, features: object) -> str:
    if isinstance(features, dict) and isinstance(features.get("score_action"), str):
        return str(features["score_action"])
    if state == "ai1_passed":
        return "pass"
    if state in {"ai1_rejected", "rejected"}:
        return "reject"
    return "pending_review"
