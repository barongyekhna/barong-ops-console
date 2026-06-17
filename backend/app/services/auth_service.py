import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import json
from math import ceil
from hashlib import sha256

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.security import (
    InvalidSessionIdError,
    generate_session_id,
    hash_session_id,
    hash_password,
    verify_password,
)
from ..db.compatibility import is_missing_table_error, table_exists
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
    login_lockout_columns_available,
    update_last_login,
)
from .event_collector import emit_event
from .rate_limiter import register_login_rate_limit_attempt


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


LEGACY_SESSION_PREFIX = "legacy-v1"
LEGACY_SESSION_HASH_MARKER = "legacy-v1:c05b-compat"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _retry_after_seconds(until: datetime, now: datetime) -> int:
    return max(1, ceil((_as_aware(until) - now).total_seconds()))


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


def _auth_sessions_table_available(db: Session) -> bool:
    return table_exists(db, "auth_sessions")


def _legacy_secret(settings: Settings) -> bytes:
    secret_parts = [settings.app_name, settings.database_url]
    if settings.owner_password is not None:
        secret_parts.append(settings.owner_password.get_secret_value())
    return "|".join(secret_parts).encode("utf-8")


def _base64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _base64url_decode(payload: str) -> bytes:
    padding = "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode(f"{payload}{padding}".encode("ascii"))


def _legacy_session_token(
    *,
    user_id: int,
    expires_at: datetime,
    settings: Settings,
) -> str:
    body = _base64url_encode(
        json.dumps(
            {
                "uid": user_id,
                "exp": int(expires_at.timestamp()),
                "nonce": generate_session_id(),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    signature = hmac.new(
        _legacy_secret(settings),
        body.encode("ascii"),
        sha256,
    ).hexdigest()
    return f"{LEGACY_SESSION_PREFIX}.{body}.{signature}"


def _parse_legacy_session_token(
    session_id: str,
    *,
    settings: Settings,
    now: datetime,
) -> tuple[int, datetime] | None:
    parts = session_id.split(".")
    if len(parts) != 3 or parts[0] != LEGACY_SESSION_PREFIX:
        return None
    body = parts[1]
    expected_signature = hmac.new(
        _legacy_secret(settings),
        body.encode("ascii"),
        sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, parts[2]):
        return None
    try:
        payload = json.loads(_base64url_decode(body))
        user_id = int(payload["uid"])
        expires_at = datetime.fromtimestamp(int(payload["exp"]), timezone.utc)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if expires_at <= now:
        return None
    return user_id, expires_at


def _transient_auth_session(
    *,
    user: User,
    issued_at: datetime,
    expires_at: datetime,
    audit: AuditContext,
) -> AuthSession:
    auth_session = AuthSession(
        session_id_hash=LEGACY_SESSION_HASH_MARKER,
        user_id=user.id,
        issued_at=issued_at,
        expires_at=expires_at,
        last_seen_at=issued_at,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
    )
    auth_session.id = 0
    auth_session.user = user
    return auth_session


def _is_legacy_auth_session(auth_session: AuthSession) -> bool:
    return auth_session.session_id_hash == LEGACY_SESSION_HASH_MARKER


def _new_session(
    db: Session,
    *,
    user: User,
    settings: Settings,
    audit: AuditContext,
    issued_at: datetime,
) -> tuple[str, AuthSession]:
    expires_at = issued_at + timedelta(minutes=settings.auth_session_expire_minutes)
    if not _auth_sessions_table_available(db):
        session_id = _legacy_session_token(
            user_id=user.id,
            expires_at=expires_at,
            settings=settings,
        )
        return (
            session_id,
            _transient_auth_session(
                user=user,
                issued_at=issued_at,
                expires_at=expires_at,
                audit=audit,
            ),
        )

    session_id = generate_session_id()
    try:
        auth_session = create_auth_session(
            db,
            session_id_hash=hash_session_id(session_id),
            user_id=user.id,
            issued_at=issued_at,
            expires_at=expires_at,
            ip_address=audit.ip_address,
            user_agent=audit.user_agent,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        if not is_missing_table_error(exc, "auth_sessions"):
            raise
        session_id = _legacy_session_token(
            user_id=user.id,
            expires_at=expires_at,
            settings=settings,
        )
        auth_session = _transient_auth_session(
            user=user,
            issued_at=issued_at,
            expires_at=expires_at,
            audit=audit,
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
    rate_limit_decision = register_login_rate_limit_attempt(
        db,
        username=username,
        audit=audit,
        settings=settings,
        now=attempted_at,
    )
    if not rate_limit_decision.allowed:
        _record_login_rate_limit(
            db,
            audit=audit,
            reason=rate_limit_decision.reason or "distributed_rate_limit",
            retry_after_seconds=rate_limit_decision.retry_after_seconds or 1,
        )
        emit_event(
            event_type="auth.login",
            module="system",
            action="auth.login",
            source="backend",
            status="failed",
            context_id=audit.request_id,
            payload={
                "outcome": "rate_limited",
                "reason": rate_limit_decision.reason,
            },
        )
        raise LoginRateLimitError(
            retry_after_seconds=rate_limit_decision.retry_after_seconds or 1
        )

    user = get_user_by_username(db, username)
    password_matches = False

    login_lockout_available = login_lockout_columns_available(db)

    if user is not None and login_lockout_available:
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
            emit_event(
                event_type="auth.login",
                module="system",
                action="auth.login",
                source="backend",
                status="failed",
                context_id=audit.request_id,
                user_id=str(user.id),
                payload={"outcome": "rate_limited", "reason": "user_backoff"},
            )
            raise LoginRateLimitError(retry_after_seconds=retry_after)

    if user is None:
        hash_password(password)
    else:
        password_matches = verify_password(password, user.password_hash)

    if user is None or not password_matches or not user.is_active:
        if user is not None and login_lockout_available:
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
        emit_event(
            event_type="auth.login",
            module="system",
            action="auth.login",
            source="backend",
            status="failed",
            context_id=audit.request_id,
            user_id=str(user.id) if user is not None else None,
            payload={"outcome": "invalid_credentials"},
        )
        raise InvalidCredentialsError("Invalid username or password.")

    logged_in_at = _now()
    if login_lockout_available:
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
    emit_event(
        event_type="auth.login",
        module="system",
        action="auth.login",
        source="backend",
        status="success",
        context_id=audit.request_id,
        user_id=str(user.id),
        payload={"outcome": "session_created", "role": user.role},
    )
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
    now = _now()
    from ..core.config import get_settings

    legacy_session = _parse_legacy_session_token(
        session_id,
        settings=get_settings(),
        now=now,
    )
    if legacy_session is not None:
        user_id, expires_at = legacy_session
        user = get_user_by_id(db, user_id)
        if user is None or not user.is_active:
            raise InvalidSessionError("Invalid session.")
        return AuthenticatedSession(
            user=user,
            auth_session=_transient_auth_session(
                user=user,
                issued_at=now,
                expires_at=expires_at,
                audit=audit,
            ),
        )

    try:
        auth_session = get_auth_session_by_hash(
            db,
            hash_session_id(session_id),
        )
    except InvalidSessionIdError:
        raise InvalidSessionError("Invalid session.") from None

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
    if not _is_legacy_auth_session(auth_session) and auth_session.invalidated_at is None:
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
    emit_event(
        event_type="auth.logout",
        module="system",
        action="auth.logout",
        source="backend",
        status="success",
        context_id=audit.request_id,
        user_id=str(user.id),
        payload={"outcome": "session_invalidated"},
    )
