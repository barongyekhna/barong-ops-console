from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..db.compatibility import is_missing_table_error
from ..core.config import Settings
from ..repositories.security import (
    RateLimitBucketResult,
    register_rate_limit_attempt,
)

LOGIN_ENDPOINT_KEY = "auth.login"


class RateLimitAuditContext(Protocol):
    ip_address: str | None


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    reason: str | None
    retry_after_seconds: int | None


def _identity_value(value: str | None) -> str:
    normalized = (value or "unknown").strip().lower()
    return normalized or "unknown"


def _blocked_result(
    result: RateLimitBucketResult,
) -> RateLimitDecision | None:
    if result.allowed:
        return None
    return RateLimitDecision(
        allowed=False,
        reason=f"{result.scope}_rate_limit",
        retry_after_seconds=result.retry_after_seconds,
    )


def register_login_rate_limit_attempt(
    db: Session,
    *,
    username: str,
    audit: RateLimitAuditContext,
    settings: Settings,
    now: datetime,
) -> RateLimitDecision:
    ip_identifier = _identity_value(audit.ip_address)
    user_identifier = _identity_value(username)
    endpoint_identifier = LOGIN_ENDPOINT_KEY
    checks = (
        {
            "scope": "ip",
            "identifier": ip_identifier,
            "limit": settings.login_ip_rate_limit_attempts,
        },
        {
            "scope": "user",
            "identifier": user_identifier,
            "limit": settings.login_user_rate_limit_attempts,
        },
        {
            "scope": "endpoint",
            "identifier": endpoint_identifier,
            "limit": settings.login_endpoint_rate_limit_attempts,
        },
    )

    try:
        for check in checks:
            blocked = _blocked_result(
                register_rate_limit_attempt(
                    db,
                    scope=check["scope"],
                    identifier=check["identifier"],
                    endpoint_key=LOGIN_ENDPOINT_KEY,
                    limit=check["limit"],
                    window_seconds=settings.login_ip_rate_limit_window_seconds,
                    now=now,
                )
            )
            if blocked is not None:
                return blocked
    except IntegrityError:
        db.rollback()
        return RateLimitDecision(
            allowed=False,
            reason="distributed_rate_limit_contention",
            retry_after_seconds=1,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        if is_missing_table_error(exc, "security_rate_limit_buckets"):
            return RateLimitDecision(
                allowed=True,
                reason="c05b_compat_rate_limit_unavailable",
                retry_after_seconds=None,
            )
        raise

    return RateLimitDecision(
        allowed=True,
        reason=None,
        retry_after_seconds=None,
    )
