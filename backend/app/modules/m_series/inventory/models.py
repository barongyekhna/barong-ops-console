"""M 系列 · 制造库存的 SQLAlchemy 模型。

一本账两个台面:物料(part)和成品(product)共用 ``mfg_items`` 主档,所有数量
变动只走 ``mfg_movements`` 流水(只增不改不删),当前库存 = 流水求和,永远不存
一个可以被手改的"库存数"字段。

归属列刻意叫 ``factory_org_id`` 而不是 ``org_id``:请求里的"当前组织"由后端按
规则算死(owner 永远落在最早建的贸易公司),带 ``org_id`` 列的模型会被 C18G
数据隔离自动盖成那家。M 系列由服务层显式定位 factory 类型组织。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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

KIND_PART = "part"
KIND_PRODUCT = "product"
ALLOWED_KINDS = (KIND_PART, KIND_PRODUCT)

# 每件消耗 qty 个 / 每 qty 件装一箱(向上取整)
BOM_MODE_PER_UNIT = "per_unit"
BOM_MODE_PER_CARTON = "per_carton"
ALLOWED_BOM_MODES = (BOM_MODE_PER_UNIT, BOM_MODE_PER_CARTON)

DOC_RECEIPT = "receipt"
DOC_PRODUCTION = "production"
DOC_SHIPMENT = "shipment"
DOC_ADJUSTMENT = "adjustment"
ALLOWED_DOC_TYPES = (DOC_RECEIPT, DOC_PRODUCTION, DOC_SHIPMENT, DOC_ADJUSTMENT)
DOC_NO_PREFIX = {
    DOC_RECEIPT: "RC",
    DOC_PRODUCTION: "PR",
    DOC_SHIPMENT: "SH",
    DOC_ADJUSTMENT: "AJ",
}

QTY = Numeric(14, 3)


class MfgItem(Base):
    """物料或成品主档。"""

    __tablename__ = "mfg_items"
    __table_args__ = (
        UniqueConstraint(
            "factory_org_id", "code", name="uq_mfg_items_factory_org_id"
        ),
        CheckConstraint(
            "kind IN ('part', 'product')", name=conv("ck_mfg_items_kind")
        ),
        Index("ix_mfg_items_factory_kind", "factory_org_id", "kind"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MfgBomLine(Base):
    """成品的配件清单行。"""

    __tablename__ = "mfg_bom_lines"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "part_id", name="uq_mfg_bom_lines_product_id"
        ),
        CheckConstraint(
            "mode IN ('per_unit', 'per_carton')",
            name=conv("ck_mfg_bom_lines_mode"),
        ),
        CheckConstraint("qty > 0", name=conv("ck_mfg_bom_lines_qty")),
        Index("ix_mfg_bom_lines_product_id", "product_id"),
        Index("ix_mfg_bom_lines_part_id", "part_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfg_items.id", ondelete="CASCADE"), nullable=False
    )
    part_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfg_items.id", ondelete="RESTRICT"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MfgDocument(Base):
    """单据头:采购入库 / 生产 / 发货 / 盘点调整。永不改、永不删。"""

    __tablename__ = "mfg_documents"
    __table_args__ = (
        UniqueConstraint(
            "factory_org_id", "doc_no", name="uq_mfg_documents_factory_org_id"
        ),
        CheckConstraint(
            "doc_type IN ('receipt', 'production', 'shipment', 'adjustment')",
            name=conv("ck_mfg_documents_doc_type"),
        ),
        Index(
            "ix_mfg_documents_factory_created",
            "factory_org_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    doc_no: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfgMovement(Base):
    """流水:一张单据下挂 N 行,每行一个 item 的 ±数量。"""

    __tablename__ = "mfg_movements"
    __table_args__ = (
        Index(
            "ix_mfg_movements_factory_item_created",
            "factory_org_id",
            "item_id",
            "created_at",
        ),
        Index("ix_mfg_movements_document_id", "document_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfg_documents.id", ondelete="RESTRICT"), nullable=False
    )
    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfg_items.id", ondelete="RESTRICT"), nullable=False
    )
    qty_delta: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfgDocCounter(Base):
    """单号计数器,按 (工厂, 单据类型) 一行,取号时 FOR UPDATE。"""

    __tablename__ = "mfg_doc_counters"

    factory_org_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    next_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
