from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from typing import Literal

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


@dataclass(frozen=True)
class LoginFailureSideEffect:
    user_id: int | None
    failed_at: datetime
    request_id: str
    ip_address: str | None
    user_agent: str | None
    attempts: int = 0


LoginSideEffect = LoginSuccessSideEffect | LoginFailureSideEffect


_queue: Queue[LoginSideEffect] = Queue(maxsize=LOGIN_SIDE_EFFECT_QUEUE_SIZE)
_stop = Event()
_lock = Lock()
_worker: Thread | None = None


def _lockout_until_for_failure(user, failed_at: datetime):
    from ..core.config import get_settings

    settings = get_settings()
    next_count = int(user.failed_login_count or 0) + 1
    if next_count < settings.login_failed_attempt_lockout_threshold:
        return None
    return failed_at + timedelta(minutes=settings.login_account_lockout_minutes)


def _run_login_success_side_effect(effect: LoginSuccessSideEffect) -> None:
    from ..db.session import SessionLocal, rollback_open_transaction
    from ..models.user import User
    from ..repositories.operation_logs import create_operation_log
    from ..repositories.users import reset_login_failures, update_last_login

    db = SessionLocal()
    try:
        user = db.get(User, effect.user_id)
        if user is not None:
            update_last_login(db, user, effect.logged_in_at)
            reset_login_failures(db, user)
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


def _run_login_failure_side_effect(effect: LoginFailureSideEffect) -> None:
    from ..db.session import SessionLocal, rollback_open_transaction
    from ..models.user import User
    from ..repositories.operation_logs import create_operation_log
    from ..repositories.users import record_failed_login

    db = SessionLocal()
    try:
        if effect.user_id is not None:
            user = db.get(User, effect.user_id)
            if user is not None:
                record_failed_login(
                    db,
                    user,
                    failed_at=effect.failed_at,
                    locked_until=_lockout_until_for_failure(user, effect.failed_at),
                )
        create_operation_log(
            db,
            actor_type="anonymous",
            actor_id="anonymous",
            action="auth.login",
            target_type="session",
            target_id="current",
            result="failure",
            error_code="invalid_credentials",
            request_id=effect.request_id,
            ip_address=effect.ip_address,
            user_agent=effect.user_agent,
            details={"outcome": "invalid_credentials"},
        )
        db.commit()
    except Exception:
        rollback_open_transaction(db)
        raise
    finally:
        db.close()


def _run_login_side_effect(effect: LoginSideEffect) -> None:
    if isinstance(effect, LoginSuccessSideEffect):
        _run_login_success_side_effect(effect)
        return
    _run_login_failure_side_effect(effect)


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
    _queue_login_side_effect(effect, side_effect_type="success")


def queue_login_failure_side_effect(effect: LoginFailureSideEffect) -> None:
    _queue_login_side_effect(effect, side_effect_type="failure")


def _queue_login_side_effect(
    effect: LoginSideEffect,
    *,
    side_effect_type: Literal["success", "failure"],
) -> None:
    try:
        _queue.put_nowait(effect)
    except Full:
        _logger.warning(
            "login %s side effect queue is full: user_id=%s",
            side_effect_type,
            getattr(effect, "user_id", None),
        )


def flush_login_side_effects() -> int:
    flushed = 0
    while True:
        try:
            effect = _queue.get_nowait()
        except Empty:
            return flushed
        try:
            _run_login_side_effect(effect)
            flushed += 1
        except Exception as exc:
            _logger.warning("login side effect flush failed: %s", exc)
        finally:
            _queue.task_done()


def pending_login_side_effect_count() -> int:
    return _queue.qsize()


def _requeue(effect: LoginSideEffect) -> None:
    if effect.attempts + 1 >= LOGIN_SIDE_EFFECT_MAX_ATTEMPTS:
        _logger.warning(
            "dropping login side effect after retries: user_id=%s",
            getattr(effect, "user_id", None),
        )
        return
    if isinstance(effect, LoginSuccessSideEffect):
        replacement: LoginSideEffect = LoginSuccessSideEffect(
            user_id=effect.user_id,
            auth_session_id=effect.auth_session_id,
            logged_in_at=effect.logged_in_at,
            role=effect.role,
            request_id=effect.request_id,
            ip_address=effect.ip_address,
            user_agent=effect.user_agent,
            attempts=effect.attempts + 1,
        )
    else:
        replacement = LoginFailureSideEffect(
            user_id=effect.user_id,
            failed_at=effect.failed_at,
            request_id=effect.request_id,
            ip_address=effect.ip_address,
            user_agent=effect.user_agent,
            attempts=effect.attempts + 1,
        )
    try:
        _queue.put_nowait(replacement)
    except Full:
        _logger.warning("login side effect queue is full during retry")


def _worker_loop() -> None:
    while not _stop.is_set():
        try:
            effect = _queue.get(timeout=LOGIN_SIDE_EFFECT_WORKER_TIMEOUT_SECONDS)
        except Empty:
            continue
        try:
            _run_login_side_effect(effect)
        except Exception as exc:
            _logger.warning("login side effect failed: %s", exc)
            _requeue(effect)
        finally:
            _queue.task_done()
