from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models.security import SecurityRateLimitBucket, SecurityReplayNonce


class DuplicateReplayKeyError(ValueError):
    pass


@dataclass(frozen=True)
class RateLimitBucketResult:
    allowed: bool
    scope: str
    retry_after_seconds: int | None


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _retry_after_seconds(until: datetime, now: datetime) -> int:
    return max(1, int((_as_aware(until) - now).total_seconds()) + 1)


def hash_security_key(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _rate_limit_bucket_key(
    *,
    scope: str,
    identifier: str,
    endpoint_key: str,
) -> str:
    return f"{scope}:{endpoint_key}:{identifier}"


def register_rate_limit_attempt(
    db: Session,
    *,
    scope: str,
    identifier: str,
    endpoint_key: str,
    limit: int,
    window_seconds: int,
    now: datetime,
) -> RateLimitBucketResult:
    bucket_key_hash = hash_security_key(
        _rate_limit_bucket_key(
            scope=scope,
            identifier=identifier,
            endpoint_key=endpoint_key,
        )
    )
    identifier_hash = hash_security_key(identifier)
    window_expires_at = now + timedelta(seconds=window_seconds)

    bucket = db.scalar(
        select(SecurityRateLimitBucket).where(
            SecurityRateLimitBucket.bucket_key_hash == bucket_key_hash
        )
    )
    if bucket is None:
        bucket = SecurityRateLimitBucket(
            bucket_key_hash=bucket_key_hash,
            scope=scope,
            identifier_hash=identifier_hash,
            endpoint_key=endpoint_key,
            window_started_at=now,
            expires_at=window_expires_at,
            attempt_count=1,
        )
        db.add(bucket)
        db.flush()
        return RateLimitBucketResult(
            allowed=True,
            scope=scope,
            retry_after_seconds=None,
        )

    if _as_aware(bucket.expires_at) <= now:
        bucket.window_started_at = now
        bucket.expires_at = window_expires_at
        bucket.attempt_count = 1
        bucket.blocked_until = None
        db.add(bucket)
        db.flush()
        return RateLimitBucketResult(
            allowed=True,
            scope=scope,
            retry_after_seconds=None,
        )

    if bucket.blocked_until is not None and _as_aware(bucket.blocked_until) > now:
        return RateLimitBucketResult(
            allowed=False,
            scope=scope,
            retry_after_seconds=_retry_after_seconds(bucket.blocked_until, now),
        )

    bucket.attempt_count += 1
    if bucket.attempt_count > limit:
        bucket.blocked_until = bucket.expires_at
        db.add(bucket)
        db.flush()
        return RateLimitBucketResult(
            allowed=False,
            scope=scope,
            retry_after_seconds=_retry_after_seconds(bucket.expires_at, now),
        )

    db.add(bucket)
    db.flush()
    return RateLimitBucketResult(
        allowed=True,
        scope=scope,
        retry_after_seconds=None,
    )


def register_replay_nonce(
    db: Session,
    *,
    scope: str,
    key: str,
    payload_digest: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> None:
    checked_at = now or datetime.now(timezone.utc)
    expires_at = checked_at + timedelta(seconds=ttl_seconds)
    global_key = f"{scope}:{key}"
    global_dedup_key_hash = hash_security_key(global_key)
    nonce_key_hash = hash_security_key(key)

    db.execute(
        delete(SecurityReplayNonce).where(
            SecurityReplayNonce.expires_at <= checked_at
        )
    )

    existing = db.scalar(
        select(SecurityReplayNonce).where(
            SecurityReplayNonce.global_dedup_key_hash == global_dedup_key_hash
        )
    )
    if existing is not None and _as_aware(existing.expires_at) > checked_at:
        raise DuplicateReplayKeyError("Duplicate replay protection key.")

    if existing is None:
        existing = SecurityReplayNonce(
            global_dedup_key_hash=global_dedup_key_hash,
        )

    existing.scope = scope
    existing.nonce_key_hash = nonce_key_hash
    existing.payload_digest = payload_digest
    existing.first_seen_at = checked_at
    existing.expires_at = expires_at
    db.add(existing)
    db.flush()
