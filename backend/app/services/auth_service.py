from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from threading import Lock

from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.security import (
    InvalidSessionIdError,
    generate_session_id,
    hash_session_id,
    hash_password,
    verify_password,
)
from ..models.auth_session import AuthSession
from ..models.user import User
from ..repositories.auth_sessions import (
    create_auth_session,
    get_auth_session_by_hash,
    invalidate_auth_session,
    mark_session_seen,
)
from ..repositories.operation_logs import create_operation_log
from ..repositories.users import (
    get_user_by_id,
    get_user_by_username,
    record_failed_login,
    reset_login_failures,
    update_last_login,
)


class InvalidCredentialsError(ValueError):
    pass


class InvalidSessionError(ValueError):
    pass


class LoginRateLimitError(ValueError):
    def __init__(
        self,
        message: str = "Too many login attempts. Try again later.",
        *,
        retry_after_seconds: int,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


_IP_LOGIN_ATTEMPTS: dict[str, list[datetime]] = {}
_IP_LOGIN_ATTEMPTS_LOCK = Lock()


@dataclass(frozen=True)
class AuditContext:
    request_id: str
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True)
class LoginResult:
    session_id: str
    user: User
    auth_session: AuthSession


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    auth_session: AuthSession


@dataclass(frozen=True)
class SessionRotationResult:
    session_id: str
    auth_session: AuthSession


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _retry_after_seconds(until: datetime, now: datetime) -> int:
    return max(1, ceil((_as_aware(until) - now).total_seconds()))


def _ip_key(audit: AuditContext) -> str:
    return audit.ip_address or "unknown"


def _register_ip_login_attempt(
    *,
    audit: AuditContext,
    settings: Settings,
    now: datetime,
) -> int | None:
    key = _ip_key(audit)
    window = timedelta(seconds=settings.login_ip_rate_limit_window_seconds)
    with _IP_LOGIN_ATTEMPTS_LOCK:
        attempts = [
            attempted_at
            for attempted_at in _IP_LOGIN_ATTEMPTS.get(key, [])
            if now - attempted_at < window
        ]
        attempts.append(now)
        _IP_LOGIN_ATTEMPTS[key] = attempts
        if len(attempts) <= settings.login_ip_rate_limit_attempts:
            return None
        retry_until = attempts[0] + window
        return _retry_after_seconds(retry_until, now)


def _failed_login_delay_seconds(
    failed_login_count: int,
    settings: Settings,
) -> int:
    if failed_login_count <= 0:
        return 0
    base = settings.login_failed_attempt_base_delay_seconds
    if base <= 0:
        return 0
    exponent = min(failed_login_count - 1, 30)
    return min(
        base * (2**exponent),
        settings.login_failed_attempt_max_delay_seconds,
    )


def _user_retry_after_seconds(
    user: User,
    *,
    settings: Settings,
    now: datetime,
) -> int | None:
    if user.locked_until is not None:
        locked_until = _as_aware(user.locked_until)
        if locked_until > now:
            return _retry_after_seconds(locked_until, now)

    if user.last_failed_login_at is None:
        return None

    delay_seconds = _failed_login_delay_seconds(
        user.failed_login_count,
        settings,
    )
    if delay_seconds <= 0:
        return None

    retry_until = _as_aware(user.last_failed_login_at) + timedelta(
        seconds=delay_seconds
    )
    if retry_until > now:
        return _retry_after_seconds(retry_until, now)
    return None


def _lockout_until_for_failure(
    user: User,
    *,
    settings: Settings,
    failed_at: datetime,
) -> datetime | None:
    next_count = user.failed_login_count + 1
    if next_count < settings.login_failed_attempt_lockout_threshold:
        return None
    return failed_at + timedelta(minutes=settings.login_account_lockout_minutes)


def _record_login_rate_limit(
    db: Session,
    *,
    audit: AuditContext,
    reason: str,
    retry_after_seconds: int,
    user: User | None = None,
) -> None:
    create_operation_log(
        db,
        actor_type="user" if user is not None else "anonymous",
        actor_id=str(user.id) if user is not None else "anonymous",
        action="auth.login_rate_limited",
        target_type="session",
        target_id="current",
        result="failure",
        error_code="login_rate_limited",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={
            "outcome": "rate_limited",
            "reason": reason,
            "retry_after_seconds": retry_after_seconds,
        },
    )
    db.commit()


def _new_session(
    db: Session,
    *,
    user: User,
    settings: Settings,
    audit: AuditContext,
    issued_at: datetime,
) -> tuple[str, AuthSession]:
    session_id = generate_session_id()
    auth_session = create_auth_session(
        db,
        session_id_hash=hash_session_id(session_id),
        user_id=user.id,
        issued_at=issued_at,
        expires_at=issued_at
        + timedelta(minutes=settings.auth_session_expire_minutes),
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
    )
    return session_id, auth_session


def login(
    db: Session,
    *,
    username: str,
    password: str,
    settings: Settings,
    audit: AuditContext,
) -> LoginResult:
    attempted_at = _now()
    retry_after = _register_ip_login_attempt(
        audit=audit,
        settings=settings,
        now=attempted_at,
    )
    if retry_after is not None:
        _record_login_rate_limit(
            db,
            audit=audit,
            reason="ip_rate_limit",
            retry_after_seconds=retry_after,
        )
        raise LoginRateLimitError(retry_after_seconds=retry_after)

    user = get_user_by_username(db, username)
    password_matches = False

    if user is not None:
        retry_after = _user_retry_after_seconds(
            user,
            settings=settings,
            now=attempted_at,
        )
        if retry_after is not None:
            _record_login_rate_limit(
                db,
                audit=audit,
                reason="user_backoff_or_lockout",
                retry_after_seconds=retry_after,
                user=user,
            )
            raise LoginRateLimitError(retry_after_seconds=retry_after)

    if user is None:
        hash_password(password)
    else:
        password_matches = verify_password(password, user.password_hash)

    if user is None or not password_matches or not user.is_active:
        if user is not None:
            record_failed_login(
                db,
                user,
                failed_at=attempted_at,
                locked_until=_lockout_until_for_failure(
                    user,
                    settings=settings,
                    failed_at=attempted_at,
                ),
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
            request_id=audit.request_id,
            ip_address=audit.ip_address,
            user_agent=audit.user_agent,
            details={"outcome": "invalid_credentials"},
        )
        db.commit()
        raise InvalidCredentialsError("Invalid username or password.")

    logged_in_at = _now()
    reset_login_failures(db, user)
    session_id, auth_session = _new_session(
        db,
        user=user,
        settings=settings,
        audit=audit,
        issued_at=logged_in_at,
    )
    update_last_login(db, user, logged_in_at)
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(user.id),
        action="auth.login",
        target_type="session",
        target_id=str(auth_session.id),
        result="success",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={"outcome": "session_created", "role": user.role},
    )
    db.commit()
    return LoginResult(
        session_id=session_id,
        user=user,
        auth_session=auth_session,
    )


def validate_session(
    db: Session,
    *,
    session_id: str,
    audit: AuditContext,
) -> AuthenticatedSession:
    try:
        auth_session = get_auth_session_by_hash(
            db,
            hash_session_id(session_id),
        )
    except InvalidSessionIdError:
        raise InvalidSessionError("Invalid session.") from None

    now = _now()
    if auth_session is None or auth_session.invalidated_at is not None:
        raise InvalidSessionError("Invalid session.")

    if _as_aware(auth_session.expires_at) <= now:
        invalidate_auth_session(
            db,
            auth_session,
            invalidated_at=now,
            reason="expired",
        )
        create_operation_log(
            db,
            actor_type="user",
            actor_id=str(auth_session.user_id),
            action="auth.session_expired",
            target_type="session",
            target_id=str(auth_session.id),
            result="success",
            request_id=audit.request_id,
            ip_address=audit.ip_address,
            user_agent=audit.user_agent,
            details={"outcome": "session_expired"},
        )
        db.commit()
        raise InvalidSessionError("Invalid session.")

    user = get_user_by_id(db, auth_session.user_id)
    if user is None or not user.is_active:
        invalidate_auth_session(
            db,
            auth_session,
            invalidated_at=now,
            reason="user_inactive",
        )
        db.commit()
        raise InvalidSessionError("Invalid session.")

    mark_session_seen(db, auth_session, now)
    db.commit()
    return AuthenticatedSession(user=user, auth_session=auth_session)


def rotate_session(
    db: Session,
    *,
    auth_session: AuthSession,
    user: User,
    settings: Settings,
    audit: AuditContext,
) -> SessionRotationResult:
    rotated_at = _now()
    invalidate_auth_session(
        db,
        auth_session,
        invalidated_at=rotated_at,
        reason="rotated",
    )
    session_id, new_session = _new_session(
        db,
        user=user,
        settings=settings,
        audit=audit,
        issued_at=rotated_at,
    )
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(user.id),
        action="auth.session_rotate",
        target_type="session",
        target_id=str(new_session.id),
        result="success",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={"outcome": "session_rotated"},
    )
    db.commit()
    return SessionRotationResult(
        session_id=session_id,
        auth_session=new_session,
    )


def logout(
    db: Session,
    *,
    user: User,
    auth_session: AuthSession,
    audit: AuditContext,
) -> None:
    if auth_session.invalidated_at is None:
        invalidate_auth_session(
            db,
            auth_session,
            invalidated_at=_now(),
            reason="logout",
        )

    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(user.id),
        action="auth.logout",
        target_type="session",
        target_id=str(auth_session.id),
        result="success",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={"outcome": "session_invalidated"},
    )
    db.commit()
