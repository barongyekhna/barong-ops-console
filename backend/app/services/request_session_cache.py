from __future__ import annotations

from fastapi import Request

from .auth_service import AuthenticatedSession

REQUEST_AUTH_SESSION_ATTR = "authenticated_session"
REQUEST_AUTH_SESSION_COOKIE_ATTR = "authenticated_session_cookie"


def cache_authenticated_session(
    request: Request,
    *,
    session_id: str,
    current_session: AuthenticatedSession,
) -> None:
    request.state.authenticated_session = current_session
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
