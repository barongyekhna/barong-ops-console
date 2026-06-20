from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

_logger = logging.getLogger(__name__)

LOGIN_SIDE_EFFECT_QUEUE_SIZE = 10000
LOGIN_SIDE_EFFECT_WORKER_TIMEOUT_SECONDS = 0.5
LOGIN_SIDE_EFFECT_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class LoginSuccessSideEffect:
    user_id: int
    auth_session_id: int
    logged_in_at: datetime
    role: str
    request_id: str
    ip_address: str | None
    user_agent: str | None
    attempts: int = 0


_queue: Queue[LoginSuccessSideEffect] = Queue(maxsize=LOGIN_SIDE_EFFECT_QUEUE_SIZE)
_stop = Event()
_lock = Lock()
_worker: Thread | None = None


def _run_login_success_side_effect(effect: LoginSuccessSideEffect) -> None:
    from ..db.session import SessionLocal, rollback_open_transaction
    from ..models.user import User
    from ..repositories.operation_logs import create_operation_log
    from ..repositories.users import update_last_login

    db = SessionLocal()
    try:
        user = db.get(User, effect.user_id)
        if user is not None:
            update_last_login(db, user, effect.logged_in_at)
        create_operation_log(
            db,
            actor_type="user",
            actor_id=str(effect.user_id),
            action="auth.login",
            target_type="session",
            target_id=str(effect.auth_session_id),
            result="success",
            request_id=effect.request_id,
            ip_address=effect.ip_address,
            user_agent=effect.user_agent,
            details={"outcome": "session_created", "role": effect.role},
        )
        db.commit()
    except Exception:
        rollback_open_transaction(db)
        raise
    finally:
        db.close()


def start_login_side_effect_worker() -> None:
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _stop.clear()
        _worker = Thread(
            target=_worker_loop,
            name="barong-login-side-effects",
            daemon=True,
        )
        _worker.start()


def stop_login_side_effect_worker(*, timeout_seconds: float = 1.0) -> None:
    global _worker
    worker = _worker
    if worker is None:
        flush_login_side_effects()
        return
    _stop.set()
    worker.join(timeout=timeout_seconds)
    with _lock:
        if _worker is worker:
            _worker = None
    flush_login_side_effects()


def queue_login_success_side_effect(effect: LoginSuccessSideEffect) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        _run_login_success_side_effect(effect)
        return

    start_login_side_effect_worker()
    try:
        _queue.put_nowait(effect)
    except Full:
        _logger.warning(
            "login side effect queue is full: user_id=%s session_id=%s",
            effect.user_id,
            effect.auth_session_id,
        )


def flush_login_side_effects() -> int:
    flushed = 0
    while True:
        try:
            effect = _queue.get_nowait()
        except Empty:
            return flushed
        try:
            _run_login_success_side_effect(effect)
            flushed += 1
        except Exception as exc:
            _logger.warning("login side effect flush failed: %s", exc)
        finally:
            _queue.task_done()


def pending_login_side_effect_count() -> int:
    return _queue.qsize()


def _requeue(effect: LoginSuccessSideEffect) -> None:
    if effect.attempts + 1 >= LOGIN_SIDE_EFFECT_MAX_ATTEMPTS:
        _logger.warning(
            "dropping login side effect after retries: user_id=%s session_id=%s",
            effect.user_id,
            effect.auth_session_id,
        )
        return
    try:
        _queue.put_nowait(
            LoginSuccessSideEffect(
                user_id=effect.user_id,
                auth_session_id=effect.auth_session_id,
                logged_in_at=effect.logged_in_at,
                role=effect.role,
                request_id=effect.request_id,
                ip_address=effect.ip_address,
                user_agent=effect.user_agent,
                attempts=effect.attempts + 1,
            )
        )
    except Full:
        _logger.warning("login side effect queue is full during retry")


def _worker_loop() -> None:
    while not _stop.is_set():
        try:
            effect = _queue.get(timeout=LOGIN_SIDE_EFFECT_WORKER_TIMEOUT_SECONDS)
        except Empty:
            continue
        try:
            _run_login_success_side_effect(effect)
        except Exception as exc:
            _logger.warning("login side effect failed: %s", exc)
            _requeue(effect)
        finally:
            _queue.task_done()
