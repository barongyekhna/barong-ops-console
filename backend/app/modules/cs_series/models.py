"""Persistent customer-service messages for the retail and wholesale teams."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ...db.base import Base

TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"
DEFAULT_BUSINESS_CONTEXT = "independent_store"
DEFAULT_SCOPE_MODE = "production"


class CSMessage(Base):
    """One public contact-form submission, scoped to one organization/team."""

    __tablename__ = "cs_messages"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('retail', 'wholesale')",
            name=conv("ck_cs_messages_valid_channel"),
        ),
        CheckConstraint(
            "status IN ('new', 'in_progress', 'resolved', 'spam')",
            name=conv("ck_cs_messages_valid_status"),
        ),
        CheckConstraint(
            "length(message) BETWEEN 1 AND 5000",
            name=conv("ck_cs_messages_message_length"),
        ),
        Index(
            "ix_cs_messages_channel_status_created",
            "channel",
            "status",
            "created_at",
        ),
        Index(
            "ix_cs_messages_org_channel_created",
            "org_id",
            "channel",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # ``org_id`` participates in the C18 isolation layer. ``workspace_key``
    # mirrors the K/I international-trade series scope contract.
    org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    workspace_key: Mapped[str] = mapped_column(String(128), nullable=False)
    business_context: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default=DEFAULT_BUSINESS_CONTEXT,
        server_default=DEFAULT_BUSINESS_CONTEXT,
    )
    scope_mode: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=DEFAULT_SCOPE_MODE,
        server_default=DEFAULT_SCOPE_MODE,
    )
    organization_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default=TARGET_ORGANIZATION_NAME,
        server_default=TARGET_ORGANIZATION_NAME,
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    order_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    client_ip: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="new",
        server_default="new",
    )
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = [
    "CSMessage",
    "DEFAULT_BUSINESS_CONTEXT",
    "DEFAULT_SCOPE_MODE",
    "TARGET_ORGANIZATION_NAME",
]
