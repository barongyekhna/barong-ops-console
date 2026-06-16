from datetime import datetime

from sqlalchemy import BigInteger, DateTime, JSON, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


def json_type() -> JSON:
    return JSON().with_variant(JSONB(), "postgresql")


class PrimaryKeyMixin:
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class OrgScopedMixin:
    org_id: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
    )
