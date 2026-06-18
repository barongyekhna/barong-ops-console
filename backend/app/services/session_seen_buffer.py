from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Event, Lock, Thread

from sqlalchemy.exc import SQLAlchemyError

SESSION_LAST_SEEN_DEFER_WINDOW_SECONDS = 60
SESSION_LAST_SEEN_FLUSH_INTERVAL_SECONDS = 60
SESSION_LAST_SEEN_BATCH_SIZE = 500
SESSION_LAST_SEEN_MAX_TRACKED_SESSIONS = 8192

_logger = logging.getLogger(__name__)
_lock = Lock()
_wake = Event()
_stop = Event()
_worker: Thread | None = None
_pending_seen_by_hash: dict[str, datetime] = {}
_last_queued_seen_by_hash: dict[str, datetime] = {}
_last_flush_at: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _is_persisted_session_hash(session_id_hash: str) -> bool:
    return len(session_id_hash) == 64


def start_session_seen_flush_worker() -> None:
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _stop.clear()
        _worker = Thread(
            target=_flush_worker,
            name="barong-session-last-seen-flush",
            daemon=True,
        )
        _worker.start()


def stop_session_seen_flush_worker(*, timeout_seconds: float = 1.0) -> None:
    global _worker
    worker = _worker
    if worker is None:
        return
    _stop.set()
    _wake.set()
    worker.join(timeout=timeout_seconds)
    with _lock:
        if _worker is worker:
            _worker = None
    flush_session_seen_updates(force=True)


def queue_session_seen(
    session_id_hash: str,
    *,
    seen_at: datetime | None = None,
) -> bool:
    if not _is_persisted_session_hash(session_id_hash):
        return False

    start_session_seen_flush_worker()
    candidate = _as_aware(seen_at or _now())
    should_wake = False
    with _lock:
        if len(_last_queued_seen_by_hash) > SESSION_LAST_SEEN_MAX_TRACKED_SESSIONS:
            _last_queued_seen_by_hash.clear()

        previous = _last_queued_seen_by_hash.get(session_id_hash)
        if (
            previous is not None
            and (
                candidate - _as_aware(previous)
            ).total_seconds() < SESSION_LAST_SEEN_DEFER_WINDOW_SECONDS
        ):
            return False

        _last_queued_seen_by_hash[session_id_hash] = candidate
        current = _pending_seen_by_hash.get(session_id_hash)
        if current is None or _as_aware(current) < candidate:
            _pending_seen_by_hash[session_id_hash] = candidate

        should_wake = len(_pending_seen_by_hash) >= SESSION_LAST_SEEN_BATCH_SIZE

    if should_wake:
        _wake.set()
    return True


def flush_session_seen_updates(*, force: bool = False) -> int:
    global _last_flush_at
    now = _now()
    with _lock:
        if not _pending_seen_by_hash:
            return 0
        due_by_interval = (
            _last_flush_at is None
            or (now - _as_aware(_last_flush_at)).total_seconds()
            >= SESSION_LAST_SEEN_FLUSH_INTERVAL_SECONDS
        )
        due_by_batch = len(_pending_seen_by_hash) >= SESSION_LAST_SEEN_BATCH_SIZE
        if not force and not due_by_interval and not due_by_batch:
            return 0

        batch_keys = list(_pending_seen_by_hash)[:SESSION_LAST_SEEN_BATCH_SIZE]
        batch = {key: _pending_seen_by_hash.pop(key) for key in batch_keys}
        _last_flush_at = now

    try:
        from ..db.session import SessionLocal, rollback_open_transaction
        from ..repositories.auth_sessions import mark_sessions_seen_batch

        db = SessionLocal()
        try:
            updated = mark_sessions_seen_batch(db, batch)
            db.commit()
            return updated
        except Exception:
            rollback_open_transaction(db)
            _requeue_batch(batch)
            raise
        finally:
            db.close()
    except SQLAlchemyError as exc:
        _logger.warning("session last_seen batch flush failed: %s", exc)
        return 0


def clear_session_seen_buffer() -> None:
    global _last_flush_at
    with _lock:
        _pending_seen_by_hash.clear()
        _last_queued_seen_by_hash.clear()
        _last_flush_at = None
    _wake.clear()


def pending_session_seen_count() -> int:
    with _lock:
        return len(_pending_seen_by_hash)


def _requeue_batch(batch: dict[str, datetime]) -> None:
    with _lock:
        for session_id_hash, seen_at in batch.items():
            current = _pending_seen_by_hash.get(session_id_hash)
            if current is None or _as_aware(current) < _as_aware(seen_at):
                _pending_seen_by_hash[session_id_hash] = seen_at


def _flush_worker() -> None:
    while not _stop.is_set():
        _wake.wait(timeout=SESSION_LAST_SEEN_FLUSH_INTERVAL_SECONDS)
        _wake.clear()
        if _stop.is_set():
            break
        flush_session_seen_updates()
