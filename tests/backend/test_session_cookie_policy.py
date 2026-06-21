from fastapi import Response
from starlette.requests import Request

from backend.app.core.config import Settings
from backend.app.core.environments import (
    is_development,
    is_production,
    is_production_like,
    is_staging,
    normalize_environment,
)
from backend.app.core.session_cookies import (
    clear_session_cookie,
    get_session_id_from_request,
    get_session_cookie_policy,
    set_session_cookie,
)


def _request(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
        }
    )


def test_env_fallback_is_used_when_app_env_is_absent(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("ENV", "stage")

    settings = Settings()

    assert settings.app_env == "stage"
    assert normalize_environment(settings) == "staging"
    assert is_staging(settings) is True
    assert is_production_like(settings) is True


def test_app_env_takes_priority_over_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ENV", "development")

    settings = Settings()

    assert normalize_environment(settings) == "production"
    assert is_production(settings) is True
    assert is_development(settings) is False


def test_development_cookie_policy_allows_http() -> None:
    settings = Settings(
        app_env="development",
        auth_session_cookie_path="api/backend",
        auth_session_cookie_secure=True,
        auth_session_cookie_samesite="none",
    )

    policy = get_session_cookie_policy(settings)

    assert policy.environment == "development"
    assert policy.path == "/api/backend"
    assert policy.httponly is True
    assert policy.secure is False
    assert policy.samesite == "lax"


def test_staging_cookie_policy_uses_configurable_secure_flag() -> None:
    http_settings = Settings(app_env="staging", auth_session_cookie_secure=False)
    https_settings = Settings(app_env="staging", auth_session_cookie_secure=True)

    http_policy = get_session_cookie_policy(http_settings)
    https_policy = get_session_cookie_policy(https_settings)

    assert http_policy.environment == "staging"
    assert http_policy.secure is False
    assert http_policy.samesite == "lax"
    assert https_policy.environment == "staging"
    assert https_policy.secure is True
    assert https_policy.samesite == "none"


def test_production_cookie_policy_enforces_secure_cookie() -> None:
    settings = Settings(
        app_env="production",
        auth_session_cookie_secure=False,
        auth_session_cookie_samesite="lax",
    )

    policy = get_session_cookie_policy(settings)

    assert policy.environment == "production"
    assert policy.httponly is True
    assert policy.secure is True
    assert policy.samesite == "none"


def test_set_and_clear_cookie_share_policy_attributes() -> None:
    settings = Settings(
        app_env="development",
        auth_session_cookie_path="/api/backend",
        auth_session_cookie_domain="console.example.test",
    )
    set_response = Response()
    clear_response = Response()

    set_session_cookie(set_response, session_id="session-123", settings=settings)
    clear_session_cookie(clear_response, settings=settings)

    set_cookie = set_response.headers["set-cookie"].lower()
    clear_cookie = clear_response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "secure" not in set_cookie
    assert "samesite=lax" in set_cookie
    assert "domain=console.example.test" in set_cookie
    assert "path=/api/backend" in set_cookie
    assert "samesite=lax" in clear_cookie
    assert "domain=console.example.test" in clear_cookie
    assert "path=/api/backend" in clear_cookie


def test_session_token_header_is_primary_session_signal() -> None:
    settings = Settings(auth_session_cookie_name="barong_ops_session")
    request = _request(
        [
            (b"x-session-token", b"header-session"),
            (b"cookie", b"barong_ops_session=cookie-session"),
        ]
    )

    assert get_session_id_from_request(request, settings=settings) == "header-session"


def test_bearer_token_falls_back_before_cookie() -> None:
    settings = Settings(auth_session_cookie_name="barong_ops_session")
    request = _request(
        [
            (b"authorization", b"Bearer bearer-session"),
            (b"cookie", b"barong_ops_session=cookie-session"),
        ]
    )

    assert get_session_id_from_request(request, settings=settings) == "bearer-session"


def test_session_cookie_remains_compatibility_fallback() -> None:
    settings = Settings(auth_session_cookie_name="barong_ops_session")
    request = _request([(b"cookie", b"barong_ops_session=cookie-session")])

    assert get_session_id_from_request(request, settings=settings) == "cookie-session"
