"""SQLAlchemy models for the W-S logistics hub."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base


class WUUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class WTimestampMixin:
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


class WShippingClass(WUUIDPrimaryKeyMixin, WTimestampMixin, Base):
    """WooCommerce shipping class registered for deterministic assignment."""

    __tablename__ = "w_shipping_classes"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_w_shipping_classes_slug"),
        CheckConstraint(
            "origin IN ('cn_direct', 'us_stock')",
            name=conv("ck_w_shipping_classes_valid_origin"),
        ),
    )

    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    zone_rates_json: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    sync_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="draft",
    )
    woo_class_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="cn_direct",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="100",
    )


class WSyncJob(WTimestampMixin, Base):
    """One-time-token dispatch record for W-to-n8n synchronization."""

    __tablename__ = "w_sync_jobs"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_w_sync_jobs_job_id"),
        Index("ix_w_sync_jobs_status", "status"),
        Index("ix_w_sync_jobs_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    job_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    token: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="pending",
    )
    payload_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class WOrder(WUUIDPrimaryKeyMixin, WTimestampMixin, Base):
    """Woo order snapshot with console-owned shipment tracking state."""

    __tablename__ = "w_orders"
    __table_args__ = (
        UniqueConstraint("woo_order_id", name="uq_w_orders_woo_order_id"),
        Index("ix_w_orders_tracking_status", "tracking_status"),
        Index("ix_w_orders_tracking_number", "tracking_number"),
        Index("ix_w_orders_woo_status", "woo_status"),
        Index("ix_w_orders_placed_at", "placed_at"),
    )

    woo_order_id: Mapped[int] = mapped_column(Integer, nullable=False)
    order_number: Mapped[str] = mapped_column(String(64), nullable=False)
    woo_status: Mapped[str] = mapped_column(String(30), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    items_json: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    placed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    tracking_number: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    carrier_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tracking_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="none",
    )
    tracking_events_json: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    tracking_registered: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    last_tracking_update: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    writeback_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="none",
    )


class WShippingRule(WUUIDPrimaryKeyMixin, WTimestampMixin, Base):
    """Priority-ordered deterministic shipping-class assignment rule."""

    __tablename__ = "w_shipping_rules"
    __table_args__ = (
        CheckConstraint(
            "rule_type IN ("
            "'us_stock_override', 'battery_override', 'weight_band'"
            ")",
            name=conv("ck_w_shipping_rules_valid_type"),
        ),
        Index("ix_w_rules_priority", "active", "priority"),
    )

    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    min_weight_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3),
        nullable=True,
    )
    max_weight_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3),
        nullable=True,
    )
    shipping_class_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
