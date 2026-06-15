from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock


class ReplayProtectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplayRecord:
    payload_digest: str
    expires_at: datetime


class ReplayProtectionStore:
    def __init__(self) -> None:
        self._records: dict[str, ReplayRecord] = {}
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def register(
        self,
        *,
        scope: str,
        key: str,
        payload_digest: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> None:
        checked_at = now or datetime.now(UTC)
        expires_at = checked_at + timedelta(seconds=ttl_seconds)
        scoped_key = f"{scope}:{key}"
        with self._lock:
            self._records = {
                record_key: record
                for record_key, record in self._records.items()
                if record.expires_at > checked_at
            }
            if scoped_key in self._records:
                raise ReplayProtectionError("Duplicate replay protection key.")
            self._records[scoped_key] = ReplayRecord(
                payload_digest=payload_digest,
                expires_at=expires_at,
            )


DEFAULT_REPLAY_PROTECTION_STORE = ReplayProtectionStore()


def reset_replay_protection_store() -> None:
    DEFAULT_REPLAY_PROTECTION_STORE.clear()


def register_replay_key(
    *,
    scope: str,
    key: str,
    payload_digest: str,
    ttl_seconds: int,
    store: ReplayProtectionStore | None = None,
) -> None:
    target_store = store or DEFAULT_REPLAY_PROTECTION_STORE
    target_store.register(
        scope=scope,
        key=key,
        payload_digest=payload_digest,
        ttl_seconds=ttl_seconds,
    )
