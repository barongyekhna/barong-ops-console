from dataclasses import dataclass

from fastapi import Response

from .config import Settings

PRODUCTION_ENVS = frozenset({"production", "prod", "staging"})


@dataclass(frozen=True)
class SessionCookiePolicy:
    name: str
    path: str
    httponly: bool
    secure: bool
    samesite: str
    max_age: int


def get_session_cookie_policy(settings: Settings) -> SessionCookiePolicy:
    cookie_path = settings.auth_session_cookie_path
    if not cookie_path.startswith("/"):
        cookie_path = f"/{cookie_path}"

    secure = settings.auth_session_cookie_secure
    if secure is None:
        secure = settings.app_env.lower() in PRODUCTION_ENVS

    return SessionCookiePolicy(
        name=settings.auth_session_cookie_name,
        path=cookie_path,
        httponly=True,
        secure=secure,
        samesite=settings.auth_session_cookie_samesite,
        max_age=settings.auth_session_expire_minutes * 60,
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
    )


def clear_session_cookie(response: Response, *, settings: Settings) -> None:
    policy = get_session_cookie_policy(settings)
    response.delete_cookie(
        key=policy.name,
        httponly=policy.httponly,
        secure=policy.secure,
        samesite=policy.samesite,
        path=policy.path,
    )
