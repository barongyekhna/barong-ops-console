from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class ReplayProtectionError(RuntimeError):
    pass


class ReplayProtectionStore:
    def __init__(self) -> None:
        self._tables_ready = False

    def clear(self) -> None:
        self._ensure_table()
        from ..db.session import managed_session
        from ..models.security import SecurityReplayNonce

        with managed_session() as db:
            db.execute(delete(SecurityReplayNonce))
            db.commit()

    def register(
        self,
        *,
        scope: str,
        key: str,
        payload_digest: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> None:
        del now
        self._ensure_table()
        from ..db.session import managed_session

        with managed_session() as db:
            _register_replay_key_in_db(
                db,
                scope=scope,
                key=key,
                payload_digest=payload_digest,
                ttl_seconds=ttl_seconds,
            )

    def _ensure_table(self) -> None:
        if self._tables_ready:
            return
        from ..db.base import Base
        from ..db.session import engine
        from ..models.security import SecurityReplayNonce

        Base.metadata.create_all(
            bind=engine,
            tables=[SecurityReplayNonce.__table__],
            checkfirst=True,
        )
        self._tables_ready = True


DEFAULT_REPLAY_PROTECTION_STORE = ReplayProtectionStore()


def reset_replay_protection_store() -> None:
    DEFAULT_REPLAY_PROTECTION_STORE.clear()


def _register_replay_key_in_db(
    db: Session,
    *,
    scope: str,
    key: str,
    payload_digest: str,
    ttl_seconds: int,
) -> None:
    from ..repositories.security import (
        DuplicateReplayKeyError,
        register_replay_nonce,
    )

    try:
        register_replay_nonce(
            db,
            scope=scope,
            key=key,
            payload_digest=payload_digest,
            ttl_seconds=ttl_seconds,
        )
        db.commit()
    except (DuplicateReplayKeyError, IntegrityError) as exc:
        db.rollback()
        raise ReplayProtectionError("Duplicate replay protection key.") from exc


def register_replay_key(
    *,
    scope: str,
    key: str,
    payload_digest: str,
    ttl_seconds: int,
    db: Session | None = None,
    store: ReplayProtectionStore | None = None,
) -> None:
    if db is not None:
        _register_replay_key_in_db(
            db,
            scope=scope,
            key=key,
            payload_digest=payload_digest,
            ttl_seconds=ttl_seconds,
        )
        return

    target_store = store or DEFAULT_REPLAY_PROTECTION_STORE
    target_store.register(
        scope=scope,
        key=key,
        payload_digest=payload_digest,
        ttl_seconds=ttl_seconds,
    )
