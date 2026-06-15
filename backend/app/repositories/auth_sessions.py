from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models.auth_session import AuthSession


def create_auth_session(
    db: Session,
    *,
    session_id_hash: str,
    user_id: int,
    issued_at: datetime,
    expires_at: datetime,
    ip_address: str | None,
    user_agent: str | None,
) -> AuthSession:
    auth_session = AuthSession(
        session_id_hash=session_id_hash,
        user_id=user_id,
        issued_at=issued_at,
        expires_at=expires_at,
        last_seen_at=issued_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(auth_session)
    db.flush()
    return auth_session


def get_auth_session_by_hash(
    db: Session,
    session_id_hash: str,
) -> AuthSession | None:
    return db.scalar(
        select(AuthSession).where(
            AuthSession.session_id_hash == session_id_hash
        )
    )


def mark_session_seen(
    db: Session,
    auth_session: AuthSession,
    seen_at: datetime,
) -> AuthSession:
    auth_session.last_seen_at = seen_at
    db.add(auth_session)
    return auth_session


def invalidate_auth_session(
    db: Session,
    auth_session: AuthSession,
    *,
    invalidated_at: datetime,
    reason: str,
) -> AuthSession:
    auth_session.invalidated_at = invalidated_at
    auth_session.invalidation_reason = reason
    db.add(auth_session)
    return auth_session


def invalidate_active_sessions_for_user(
    db: Session,
    *,
    user_id: int,
    invalidated_at: datetime,
    reason: str,
) -> int:
    result = db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.invalidated_at.is_(None),
        )
        .values(
            invalidated_at=invalidated_at,
            invalidation_reason=reason,
        )
    )
    return int(result.rowcount or 0)
