"""Content-free distributed abuse controls for the universal C19 surface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ...api.deps import get_audit_context, get_current_user
from ...core.config import Settings, get_settings
from ...db.session import get_db
from ...models.user import User
from ...repositories.security import register_rate_limit_attempt

C19RateLimitTier = Literal["write", "stream"]


@dataclass(frozen=True, slots=True)
class C19RateLimitPolicy:
    endpoint_key: str
    user_limit: int
    ip_limit: int
    window_seconds: int


@dataclass(frozen=True, slots=True)
class C19RateLimitDecision:
    allowed: bool
    retry_after_seconds: int | None
    reason: str | None


def classify_c19_request(request: Request) -> C19RateLimitTier | None:
    method = request.method.upper()
    if method not in {"GET", "HEAD", "OPTIONS"}:
        return "write"
    if method != "GET":
        return None
    accept = request.headers.get("accept", "").lower()
    if "text/event-stream" in accept:
        return "stream"
    return None


def _policy(tier: C19RateLimitTier, settings: Settings) -> C19RateLimitPolicy:
    if tier == "stream":
        return C19RateLimitPolicy(
            endpoint_key="c19.stream",
            user_limit=settings.c19_stream_user_rate_limit_attempts,
            ip_limit=settings.c19_stream_ip_rate_limit_attempts,
            window_seconds=settings.c19_rate_limit_window_seconds,
        )
    return C19RateLimitPolicy(
        endpoint_key="c19.write",
        user_limit=settings.c19_write_user_rate_limit_attempts,
        ip_limit=settings.c19_write_ip_rate_limit_attempts,
        window_seconds=settings.c19_rate_limit_window_seconds,
    )


def register_c19_rate_limit_attempt(
    db: Session,
    *,
    actor_user_id: int,
    ip_address: str | None,
    tier: C19RateLimitTier,
    settings: Settings,
    now: datetime | None = None,
) -> C19RateLimitDecision:
    checked_at = now or datetime.now(UTC)
    policy = _policy(tier, settings)
    identifiers = (
        ("c19_user", str(actor_user_id), policy.user_limit),
        ("c19_ip", (ip_address or "unknown").strip() or "unknown", policy.ip_limit),
    )
    for scope, identifier, limit in identifiers:
        result = register_rate_limit_attempt(
            db,
            scope=scope,
            identifier=identifier,
            endpoint_key=policy.endpoint_key,
            limit=limit,
            window_seconds=policy.window_seconds,
            now=checked_at,
        )
        if not result.allowed:
            return C19RateLimitDecision(
                allowed=False,
                retry_after_seconds=result.retry_after_seconds,
                reason=f"{scope}_{tier}_rate_limit",
            )
    return C19RateLimitDecision(
        allowed=True,
        retry_after_seconds=None,
        reason=None,
    )


def enforce_c19_rate_limit(
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> None:
    tier = classify_c19_request(request)
    if tier is None:
        return

    audit = get_audit_context(request)
    try:
        decision = register_c19_rate_limit_attempt(
            db,
            actor_user_id=int(actor.id),
            ip_address=audit.ip_address,
            tier=tier,
            settings=settings,
        )
        # Persist the shared bucket independently of the downstream domain
        # transaction so rejected requests still consume their attempt.
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "c19_rate_limit_contention",
                "message": "C19 is busy. Retry shortly.",
            },
            headers={"Retry-After": "1"},
        ) from None
    except (SQLAlchemyError, TypeError, ValueError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "c19_rate_limit_unavailable",
                "message": "C19 abuse controls are unavailable.",
            },
        ) from None

    if decision.allowed:
        return
    retry_after = max(1, int(decision.retry_after_seconds or 1))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "c19_rate_limited",
            "message": "C19 request limit reached.",
        },
        headers={"Retry-After": str(retry_after)},
    )


__all__ = [
    "C19RateLimitDecision",
    "C19RateLimitPolicy",
    "C19RateLimitTier",
    "classify_c19_request",
    "enforce_c19_rate_limit",
    "register_c19_rate_limit_attempt",
]
