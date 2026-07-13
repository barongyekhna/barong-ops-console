"""SQLAlchemy models for the W-A shipping hub."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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
