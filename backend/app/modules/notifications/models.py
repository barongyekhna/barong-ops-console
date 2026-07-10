"""SQLAlchemy model for the append-only console notification inbox."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from ...db.base import Base
from ...models.base_mixins import CreatedAtMixin, PrimaryKeyMixin, json_type


class PNotification(PrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "p_notifications"
    __table_args__ = (
        Index("ix_p_notifications_status_created", "status", "created_at"),
        Index(
            "ix_p_notifications_recipient_status_created",
            "recipient_user_id",
            "status",
            "created_at",
        ),
        Index("ix_p_notifications_org", "org_id"),
        Index("ix_p_notifications_product", "product_id"),
    )

    org_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Null means a legacy/global notification; targeted alerts are private.
    recipient_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Emitter: e.g. "p.woocommerce", "n8n", "k.product_knowledge".
    source: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        server_default="system",
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="info",
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional link back to the K product this event is about.
    product_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    # External result references: {"woo_product_id": ..., "url": ..., ...}.
    external_refs: Mapped[dict[str, Any] | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    # Raw event payload for audit / debugging.
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="unread",
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
