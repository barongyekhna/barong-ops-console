from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.models.security import SecurityRateLimitBucket
from backend.app.core.config import Settings
from backend.app.modules.c19.rate_limit import (
    classify_c19_request,
    enforce_c19_rate_limit,
    register_c19_rate_limit_attempt,
)
from backend.app.modules.c19.router import router as c19_router


def _settings(**overrides: int) -> SimpleNamespace:
    values = {
        "c19_rate_limit_window_seconds": 60,
        "c19_write_user_rate_limit_attempts": 2,
        "c19_write_ip_rate_limit_attempts": 100,
        "c19_stream_user_rate_limit_attempts": 1,
        "c19_stream_ip_rate_limit_attempts": 10,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _request(method: str, *, accept: str = "application/json") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/app/c19/events",
            "headers": [(b"accept", accept.encode("ascii"))],
        }
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    SecurityRateLimitBucket.__table__.create(engine)
    return Session(engine)


def test_request_classification_limits_only_mutations_and_sse_reconnects() -> None:
    assert classify_c19_request(_request("POST")) == "write"
    assert classify_c19_request(_request("DELETE")) == "write"
    assert classify_c19_request(_request("GET")) is None
    assert (
        classify_c19_request(_request("GET", accept="text/event-stream"))
        == "stream"
    )
    assert classify_c19_request(_request("HEAD")) is None


def test_empty_environment_values_use_safe_c19_rate_limit_defaults() -> None:
    settings = Settings(
        c19_rate_limit_window_seconds="",  # type: ignore[arg-type]
        c19_write_user_rate_limit_attempts="",  # type: ignore[arg-type]
        c19_write_ip_rate_limit_attempts="",  # type: ignore[arg-type]
        c19_stream_user_rate_limit_attempts="",  # type: ignore[arg-type]
        c19_stream_ip_rate_limit_attempts="",  # type: ignore[arg-type]
    )
    assert settings.c19_rate_limit_window_seconds == 60
    assert settings.c19_write_user_rate_limit_attempts == 180
    assert settings.c19_write_ip_rate_limit_attempts == 1800
    assert settings.c19_stream_user_rate_limit_attempts == 30
    assert settings.c19_stream_ip_rate_limit_attempts == 300


def test_every_c19_route_uses_the_shared_distributed_abuse_control() -> None:
    routes = [route for route in c19_router.routes if hasattr(route, "dependant")]
    assert routes
    assert all(
        any(
            dependency.call is enforce_c19_rate_limit
            for dependency in route.dependant.dependencies
        )
        for route in routes
    )


def test_user_write_limit_is_shared_and_stores_only_hashed_identifiers() -> None:
    checked_at = datetime(2026, 7, 12, tzinfo=UTC)
    with _session() as session:
        first = register_c19_rate_limit_attempt(
            session,
            actor_user_id=7,
            ip_address="203.0.113.9",
            tier="write",
            settings=_settings(),  # type: ignore[arg-type]
            now=checked_at,
        )
        second = register_c19_rate_limit_attempt(
            session,
            actor_user_id=7,
            ip_address="203.0.113.9",
            tier="write",
            settings=_settings(),  # type: ignore[arg-type]
            now=checked_at,
        )
        blocked = register_c19_rate_limit_attempt(
            session,
            actor_user_id=7,
            ip_address="203.0.113.9",
            tier="write",
            settings=_settings(),  # type: ignore[arg-type]
            now=checked_at,
        )

        assert first.allowed is True
        assert second.allowed is True
        assert blocked.allowed is False
        assert blocked.reason == "c19_user_write_rate_limit"
        assert blocked.retry_after_seconds == 61

        rows = list(session.scalars(select(SecurityRateLimitBucket)))
        assert {row.scope for row in rows} == {"c19_user", "c19_ip"}
        assert {row.endpoint_key for row in rows} == {"c19.write"}
        serialized = "|".join(
            f"{row.bucket_key_hash}:{row.identifier_hash}" for row in rows
        )
        assert "203.0.113.9" not in serialized
        assert len({row.identifier_hash for row in rows}) == 2


def test_ip_limit_applies_across_users_and_window_expiry_resets() -> None:
    checked_at = datetime(2026, 7, 12, tzinfo=UTC)
    settings = _settings(
        c19_write_user_rate_limit_attempts=100,
        c19_write_ip_rate_limit_attempts=2,
    )
    with _session() as session:
        for user_id in (1, 2):
            decision = register_c19_rate_limit_attempt(
                session,
                actor_user_id=user_id,
                ip_address="198.51.100.4",
                tier="write",
                settings=settings,  # type: ignore[arg-type]
                now=checked_at,
            )
            assert decision.allowed is True

        blocked = register_c19_rate_limit_attempt(
            session,
            actor_user_id=3,
            ip_address="198.51.100.4",
            tier="write",
            settings=settings,  # type: ignore[arg-type]
            now=checked_at,
        )
        assert blocked.allowed is False
        assert blocked.reason == "c19_ip_write_rate_limit"

        reset = register_c19_rate_limit_attempt(
            session,
            actor_user_id=3,
            ip_address="198.51.100.4",
            tier="write",
            settings=settings,  # type: ignore[arg-type]
            now=checked_at + timedelta(seconds=61),
        )
        assert reset.allowed is True


def test_stream_reconnect_has_an_independent_content_free_bucket() -> None:
    checked_at = datetime(2026, 7, 12, tzinfo=UTC)
    with _session() as session:
        assert register_c19_rate_limit_attempt(
            session,
            actor_user_id=11,
            ip_address=None,
            tier="stream",
            settings=_settings(),  # type: ignore[arg-type]
            now=checked_at,
        ).allowed
        blocked = register_c19_rate_limit_attempt(
            session,
            actor_user_id=11,
            ip_address=None,
            tier="stream",
            settings=_settings(),  # type: ignore[arg-type]
            now=checked_at,
        )
        assert blocked.allowed is False
        assert blocked.reason == "c19_user_stream_rate_limit"

        rows = list(session.scalars(select(SecurityRateLimitBucket)))
        assert {row.endpoint_key for row in rows} == {"c19.stream"}


def test_dependency_persists_rejection_and_returns_retry_after() -> None:
    settings = _settings()
    actor = SimpleNamespace(id=29, is_active=True)
    with _session() as session:
        for _ in range(2):
            enforce_c19_rate_limit(
                _request("POST"),
                db=session,
                actor=actor,  # type: ignore[arg-type]
                settings=settings,  # type: ignore[arg-type]
            )

        with pytest.raises(HTTPException) as caught:
            enforce_c19_rate_limit(
                _request("POST"),
                db=session,
                actor=actor,  # type: ignore[arg-type]
                settings=settings,  # type: ignore[arg-type]
            )

        assert caught.value.status_code == 429
        assert caught.value.headers is not None
        assert int(caught.value.headers["Retry-After"]) >= 1
        session.expire_all()
        user_bucket = session.scalar(
            select(SecurityRateLimitBucket).where(
                SecurityRateLimitBucket.scope == "c19_user"
            )
        )
        assert user_bucket is not None
        assert user_bucket.attempt_count == 3
