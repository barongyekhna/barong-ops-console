from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin, TimestampMixin


class SecurityRateLimitBucket(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "security_rate_limit_buckets"

    bucket_key_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    scope: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    identifier_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    endpoint_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    blocked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class SecurityReplayNonce(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "security_replay_nonces"

    global_dedup_key_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    scope: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    nonce_key_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
