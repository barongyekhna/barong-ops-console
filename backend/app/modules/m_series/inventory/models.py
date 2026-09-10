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
from sqlalchemy.orm import Mapped, mapped_column, relationship
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
# 自动编码:成品三位流水、物料四位流水
CODE_DIGITS = {KIND_PRODUCT: 3, KIND_PART: 4}

# 成本表不是库存单据(不动库存、不进 mfg_documents),但取号要的并发安全跟单据
# 一模一样,所以借用同一张计数器表和同一个 _next_doc_no();mfg_doc_counters 上
# 没有 doc_type 的 CHECK 约束,多一个种类不影响既有四种。
DOC_COST_SHEET = "cost_sheet"

DOC_NO_PREFIX = {
    DOC_RECEIPT: "RC",
    DOC_PRODUCTION: "PR",
    DOC_SHIPMENT: "SH",
    DOC_ADJUSTMENT: "AJ",
    DOC_COST_SHEET: "CS",
}

QTY = Numeric(14, 3)
# 金额四位小数:单价可能是 0.0125 这种(小五金按个算),合计再往上取整
MONEY = Numeric(14, 4)


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
    # 波动料(电线受铜价影响这类):勾上以后,含它的成本表有效期从 30 天缩到 7 天
    is_volatile: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # 编码组(成品系列 / 物料大类);老数据与手填编码为空
    group_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("mfg_code_groups.id", ondelete="SET NULL"), nullable=True
    )
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

    group: Mapped["MfgCodeGroup | None"] = relationship(lazy="selectin")

    @property
    def group_code(self) -> str | None:
        return self.group.code if self.group is not None else None

    @property
    def group_name(self) -> str | None:
        return self.group.name if self.group is not None else None


class MfgCodeGroup(Base):
    """编码组:成品的「系列」/ 物料的「大类」。每组自己发流水号。

    成品 ``TBL-001``(三位),物料 ``PK-0001``(四位),位数本身就把两种东西分开。
    组码在工厂内唯一(不分 kind),避免 PK-001 与 PK-0001 并存。
    """

    __tablename__ = "mfg_code_groups"
    __table_args__ = (
        UniqueConstraint(
            "factory_org_id", "code", name="uq_mfg_code_groups_factory_org_id"
        ),
        CheckConstraint(
            "kind IN ('part', 'product')", name=conv("ck_mfg_code_groups_kind")
        ),
        Index("ix_mfg_code_groups_factory_kind", "factory_org_id", "kind"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    next_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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
    """流水:一张单据下挂 N 行,每行一个 item 的 ±数量。

    **一条正向入库流水就是一个批次**,所以采购单价与到厂运费直接落在这里,而不是
    另开一张价格表——价格表要把数量再存一遍,同一个数字存两份迟早不一致。流水本来
    就只增不改,价格跟着它天然获得同样的保护:铜价涨了是下一批的事,老批次一个字
    不动。

    只有 receipt 的正行带价格;领料/发货/盘点的行留空。盘盈(正向 adjustment)也
    留空,于是它是个"无价批次"——FIFO 队头落到它身上时,成本表那一行判为缺价,
    绝不当 0 算。
    """

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
    # 批次价:采购单价 + 摊到每单位的到厂运费。录入按整批总运费填,除法由服务层做。
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    unit_freight: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # 发票没到时先按暂估价入库;发票到了发一条修正事件,不改这一行
    price_is_estimated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfgDocCounter(Base):
    """单号计数器,按 (工厂, 单据类型) 一行,取号时 FOR UPDATE。"""

    __tablename__ = "mfg_doc_counters"

    factory_org_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    next_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
