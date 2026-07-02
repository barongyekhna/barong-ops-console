from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread

from sqlalchemy import case, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..models.api_keys import ApiKeyRecord


DEFAULT_USAGE_FLUSH_INTERVAL_SECONDS = 60

_logger = logging.getLogger(__name__)
_worker_lock = Lock()
_worker_stop = Event()
_worker: Thread | None = None


@dataclass(frozen=True)
class ApiKeyUsageFlushReport:
    pending_before: int
    flushed: int
    skipped: bool
    interval_seconds: int = DEFAULT_USAGE_FLUSH_INTERVAL_SECONDS

    @property
    def aggregated_update(self) -> bool:
        return self.flushed > 0 and not self.skipped

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "pending_before": self.pending_before,
            "flushed": self.flushed,
            "skipped": self.skipped,
            "interval_seconds": self.interval_seconds,
            "aggregated_update": self.aggregated_update,
        }


class ApiKeyUsageTracker:
    """Process-local API key usage buffer.

    Request paths call ``record_usage`` only. The database is updated later by
    ``flush_due``/``flush_now`` as one aggregate statement per process.
    """

    def __init__(self, flush_interval_seconds: int = DEFAULT_USAGE_FLUSH_INTERVAL_SECONDS) -> None:
        self.flush_interval = timedelta(seconds=flush_interval_seconds)
        self._last_seen_by_key_id: dict[str, datetime] = {}
        self._last_flush_at = datetime.now(UTC)
        self._lock = Lock()

    def record_usage(
        self,
        key_id: str,
        *,
        used_at: datetime | None = None,
    ) -> None:
        clean_key_id = key_id.strip()
        if not clean_key_id:
            return
        timestamp = used_at or datetime.now(UTC)
        with self._lock:
            previous = self._last_seen_by_key_id.get(clean_key_id)
            if previous is None or timestamp > previous:
                self._last_seen_by_key_id[clean_key_id] = timestamp

    def pending_count(self) -> int:
        with self._lock:
            return len(self._last_seen_by_key_id)

    def flush_due(
        self,
        db: Session,
        *,
        now: datetime | None = None,
    ) -> ApiKeyUsageFlushReport:
        current = now or datetime.now(UTC)
        with self._lock:
            pending_before = len(self._last_seen_by_key_id)
            if current - self._last_flush_at < self.flush_interval:
                return ApiKeyUsageFlushReport(
                    pending_before=pending_before,
                    flushed=0,
                    skipped=True,
                    interval_seconds=int(self.flush_interval.total_seconds()),
                )
        return self.flush_now(db, now=current)

    def flush_now(
        self,
        db: Session,
        *,
        now: datetime | None = None,
    ) -> ApiKeyUsageFlushReport:
        current = now or datetime.now(UTC)
        with self._lock:
            pending = dict(self._last_seen_by_key_id)
            self._last_seen_by_key_id.clear()
            self._last_flush_at = current

        if not pending:
            return ApiKeyUsageFlushReport(
                pending_before=0,
                flushed=0,
                skipped=False,
                interval_seconds=int(self.flush_interval.total_seconds()),
            )

        try:
            db.execute(
                update(ApiKeyRecord)
                .where(ApiKeyRecord.key_id.in_(pending.keys()))
                .values(
                    last_used_at=case(
                        pending,
                        value=ApiKeyRecord.key_id,
                        else_=ApiKeyRecord.last_used_at,
                    )
                )
            )
        except Exception:
            with self._lock:
                for key_id, timestamp in pending.items():
                    previous = self._last_seen_by_key_id.get(key_id)
                    if previous is None or timestamp > previous:
                        self._last_seen_by_key_id[key_id] = timestamp
            raise

        return ApiKeyUsageFlushReport(
            pending_before=len(pending),
            flushed=len(pending),
            skipped=False,
            interval_seconds=int(self.flush_interval.total_seconds()),
        )

    def clear_for_tests(self) -> None:
        with self._lock:
            self._last_seen_by_key_id.clear()
            self._last_flush_at = datetime.now(UTC)


api_key_usage_tracker = ApiKeyUsageTracker()


def record_api_key_usage(key_id: str) -> None:
    api_key_usage_tracker.record_usage(key_id)


def flush_api_key_usage_due(db: Session) -> ApiKeyUsageFlushReport:
    return api_key_usage_tracker.flush_due(db)


def flush_api_key_usage_now(db: Session) -> ApiKeyUsageFlushReport:
    return api_key_usage_tracker.flush_now(db)


def start_api_key_usage_flush_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker_stop.clear()
        _worker = Thread(
            target=_flush_worker,
            name="barong-api-key-usage-flush",
            daemon=True,
        )
        _worker.start()


def stop_api_key_usage_flush_worker(*, timeout_seconds: float = 1.0) -> None:
    global _worker
    worker = _worker
    if worker is None:
        return
    _worker_stop.set()
    worker.join(timeout=timeout_seconds)
    with _worker_lock:
        if _worker is worker:
            _worker = None
    flush_api_key_usage_buffer(force=True)


def flush_api_key_usage_buffer(*, force: bool = False) -> ApiKeyUsageFlushReport:
    try:
        from ..db.session import SessionLocal, rollback_open_transaction

        db = SessionLocal()
        try:
            report = (
                api_key_usage_tracker.flush_now(db)
                if force
                else api_key_usage_tracker.flush_due(db)
            )
            if report.flushed:
                db.commit()
            return report
        except Exception:
            rollback_open_transaction(db)
            raise
        finally:
            db.close()
    except SQLAlchemyError as exc:
        _logger.warning("api key usage batch flush failed: %s", exc)
        return ApiKeyUsageFlushReport(
            pending_before=api_key_usage_tracker.pending_count(),
            flushed=0,
            skipped=True,
        )


def _flush_worker() -> None:
    while not _worker_stop.wait(timeout=DEFAULT_USAGE_FLUSH_INTERVAL_SECONDS):
        flush_api_key_usage_buffer()
