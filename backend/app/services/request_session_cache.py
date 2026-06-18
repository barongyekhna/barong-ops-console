from __future__ import annotations

from fastapi import Request

from .auth_service import AuthenticatedSession
from ..models.auth_session import AuthSession
from ..models.user import User

REQUEST_AUTH_SESSION_ATTR = "authenticated_session"
REQUEST_AUTH_SESSION_COOKIE_ATTR = "authenticated_session_cookie"


def _loaded_value(instance: object, name: str):
    values = getattr(instance, "__dict__", {})
    if name in values:
        return values[name]
    return getattr(instance, name)


def _optional_loaded_value(instance: object, name: str):
    values = getattr(instance, "__dict__", {})
    if name in values:
        return values[name]
    return None


def _user_snapshot(user: User) -> User:
    snapshot = User(
        username=_loaded_value(user, "username"),
        password_hash=_loaded_value(user, "password_hash"),
        role=_loaded_value(user, "role"),
        is_active=_loaded_value(user, "is_active"),
    )
    snapshot.id = _loaded_value(user, "id")
    snapshot.last_login_at = _loaded_value(user, "last_login_at")

    for name in (
        "created_at",
        "updated_at",
        "failed_login_count",
        "last_failed_login_at",
        "locked_until",
    ):
        value = _optional_loaded_value(user, name)
        if value is not None:
            setattr(snapshot, name, value)
    return snapshot


def _auth_session_snapshot(auth_session: AuthSession) -> AuthSession:
    snapshot = AuthSession(
        session_id_hash=_loaded_value(auth_session, "session_id_hash"),
        user_id=_loaded_value(auth_session, "user_id"),
        issued_at=_loaded_value(auth_session, "issued_at"),
        expires_at=_loaded_value(auth_session, "expires_at"),
        last_seen_at=_loaded_value(auth_session, "last_seen_at"),
        ip_address=_loaded_value(auth_session, "ip_address"),
        user_agent=_loaded_value(auth_session, "user_agent"),
    )
    snapshot.id = _loaded_value(auth_session, "id")
    snapshot.invalidated_at = _optional_loaded_value(auth_session, "invalidated_at")
    snapshot.invalidation_reason = _optional_loaded_value(
        auth_session,
        "invalidation_reason",
    )

    for name in ("created_at", "updated_at"):
        value = _optional_loaded_value(auth_session, name)
        if value is not None:
            setattr(snapshot, name, value)
    return snapshot


def _session_snapshot(current_session: AuthenticatedSession) -> AuthenticatedSession:
    user = _user_snapshot(current_session.user)
    auth_session = _auth_session_snapshot(current_session.auth_session)
    auth_session.user = user
    return AuthenticatedSession(user=user, auth_session=auth_session)


def cache_authenticated_session(
    request: Request,
    *,
    session_id: str,
    current_session: AuthenticatedSession,
) -> None:
    request.state.authenticated_session = _session_snapshot(current_session)
    request.state.authenticated_session_cookie = session_id


def get_cached_authenticated_session(
    request: Request,
    *,
    session_id: str,
) -> AuthenticatedSession | None:
    cached_session = getattr(request.state, REQUEST_AUTH_SESSION_ATTR, None)
    cached_cookie = getattr(request.state, REQUEST_AUTH_SESSION_COOKIE_ATTR, None)
    if cached_cookie != session_id:
        return None
    if isinstance(cached_session, AuthenticatedSession):
        return cached_session
    return None
