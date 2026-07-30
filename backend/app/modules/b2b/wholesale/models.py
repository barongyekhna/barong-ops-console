"""SQLAlchemy models for the B2B wholesale catalogue.

一条产品在这里只存"批发形态"的数据(批发价/箱规/MOQ/交期)。零售形态
(标题/图/零售价/文案)的真相源仍然是 K,这里只快照必要字段用于出 line
sheet,并在零售价漂移时把记录标成待复核——否则 line sheet 上印的 MSRP
会和网站实际售价对不上,那就是又一条"说的和做的不一样"。
"""

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
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base

STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_ARCHIVED = "archived"
ALLOWED_STATUSES = (STATUS_PENDING, STATUS_READY, STATUS_ARCHIVED)


class B2BWholesaleItem(Base):
    """One sellable product expressed in wholesale terms."""

    __tablename__ = "b2b_wholesale_items"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_b2b_wholesale_items_sku"),
        CheckConstraint(
            "status IN ('pending', 'ready', 'archived')",
            name=conv("ck_b2b_wholesale_items_status"),
        ),
        CheckConstraint(
            "wholesale_price IS NULL OR wholesale_price >= 0",
            name=conv("ck_b2b_wholesale_items_wholesale_price"),
        ),
        CheckConstraint(
            "case_pack IS NULL OR case_pack > 0",
            name=conv("ck_b2b_wholesale_items_case_pack"),
        ),
        CheckConstraint(
            "moq_units IS NULL OR moq_units > 0",
            name=conv("ck_b2b_wholesale_items_moq_units"),
        ),
        CheckConstraint(
            "lead_time_days IS NULL OR lead_time_days >= 0",
            name=conv("ck_b2b_wholesale_items_lead_time_days"),
        ),
        Index("ix_b2b_wholesale_items_status", "status"),
        Index("ix_b2b_wholesale_items_needs_review", "needs_review"),
        Index("ix_b2b_wholesale_items_k_product_id", "k_product_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)

    # ---- 来源:P 上架成功后自动灌进来 ----
    k_product_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    woo_product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ---- 零售侧快照(真相源在 K/Woo,这里只是出图册用) ----
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str] = mapped_column(String(512), nullable=False)
    category_path: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    msrp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # ---- 批发侧:人工填写 ----
    wholesale_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    price_tiers_json: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    case_pack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moq_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variant_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- 状态 ----
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=STATUS_PENDING,
    )
    # 零售价漂移了就置真:line sheet 上的 MSRP 不能和网站对不上。
    needs_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    def wholesale_fields_complete(self) -> bool:
        """出 line sheet 的最低要求。缺一样都不许导出。"""
        return (
            self.wholesale_price is not None
            and self.msrp is not None
            and self.case_pack is not None
            and self.moq_units is not None
            and self.lead_time_days is not None
        )
