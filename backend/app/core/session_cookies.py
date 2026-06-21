from dataclasses import dataclass

from fastapi import Request, Response

from .config import Settings
from .environments import (
    is_development,
    is_production,
    is_staging,
    normalize_environment,
)

SESSION_TOKEN_HEADER = "x-session-token"
SESSION_TOKEN_MAX_LENGTH = 512


@dataclass(frozen=True)
class SessionCookiePolicy:
    name: str
    path: str
    httponly: bool
    secure: bool
    samesite: str
    max_age: int
    domain: str | None
    environment: str


def _configured_secure(settings: Settings) -> bool:
    return bool(settings.auth_session_cookie_secure)


def _samesite_for_secure_cookie(secure: bool) -> str:
    return "none" if secure else "lax"


def get_session_cookie_policy(settings: Settings) -> SessionCookiePolicy:
    cookie_path = settings.auth_session_cookie_path
    if not cookie_path.startswith("/"):
        cookie_path = f"/{cookie_path}"

    environment = normalize_environment(settings)
    if is_production(environment):
        secure = True
        samesite = "none"
    elif is_development(environment):
        secure = False
        samesite = "lax"
    elif is_staging(environment):
        secure = _configured_secure(settings)
        samesite = _samesite_for_secure_cookie(secure)
    else:
        secure = _configured_secure(settings)
        samesite = settings.auth_session_cookie_samesite
        if samesite == "none" and not secure:
            samesite = "lax"

    return SessionCookiePolicy(
        name=settings.auth_session_cookie_name,
        path=cookie_path,
        httponly=True,
        secure=secure,
        samesite=samesite,
        max_age=settings.auth_session_expire_minutes * 60,
        domain=settings.auth_session_cookie_domain,
        environment=environment,
    )


def set_session_cookie(
    response: Response,
    *,
    session_id: str,
    settings: Settings,
) -> None:
    policy = get_session_cookie_policy(settings)
    response.set_cookie(
        key=policy.name,
        value=session_id,
        max_age=policy.max_age,
        httponly=policy.httponly,
        secure=policy.secure,
        samesite=policy.samesite,
        path=policy.path,
        domain=policy.domain,
    )


def clear_session_cookie(response: Response, *, settings: Settings) -> None:
    policy = get_session_cookie_policy(settings)
    response.delete_cookie(
        key=policy.name,
        httponly=policy.httponly,
        secure=policy.secure,
        samesite=policy.samesite,
        path=policy.path,
        domain=policy.domain,
    )


def _safe_session_token(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > SESSION_TOKEN_MAX_LENGTH:
        return None
    if any(character.isspace() for character in candidate):
        return None
    return candidate


def get_session_id_from_request(
    request: Request,
    *,
    settings: Settings,
) -> str | None:
    header_session_id = _safe_session_token(request.headers.get(SESSION_TOKEN_HEADER))
    if header_session_id is not None:
        return header_session_id

    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, separator, token = authorization.partition(" ")
        if separator and scheme.lower() == "bearer":
            bearer_session_id = _safe_session_token(token)
            if bearer_session_id is not None:
                return bearer_session_id

    return _safe_session_token(request.cookies.get(settings.auth_session_cookie_name))
