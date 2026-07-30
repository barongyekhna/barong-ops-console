"""B2B 单据(第一种:形式发票 PI)。

**为什么必须有这张纸**:外贸收钱的动作是买家拿着 PI 去银行电汇定金。没有它,
客户说"我要了"之后就卡住——漏斗最后一节是断的。

**为什么把内容整份快照下来,而不是每次重新从批发目录渲染**:单据一旦发出去
就是**对外承诺的凭证**。批发价过两天调了、产品改名了、条款改了,已经发出去的
那张单子**必须还是当时那个样子**,否则买家拿着旧单来付款,双方对不上账。
这和 P 系列派单时冻结 targets_json 是同一个道理。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base
from ....models.base_mixins import json_type

DOC_TYPE_PROFORMA = "proforma_invoice"
# 发货时海关要的两张。批发页上已经承诺了「every order 提供 commercial invoice、
# packing list 和运输单据」——承诺在先,这两张不是新功能是补欠账。
DOC_TYPE_COMMERCIAL = "commercial_invoice"
DOC_TYPE_PACKING = "packing_list"
DOC_TYPES = (DOC_TYPE_PROFORMA, DOC_TYPE_COMMERCIAL, DOC_TYPE_PACKING)
DOC_TYPE_LABELS = {
    DOC_TYPE_PROFORMA: "形式发票 PI",
    DOC_TYPE_COMMERCIAL: "商业发票 CI",
    DOC_TYPE_PACKING: "装箱单 PL",
}

# 订单走到哪一步了。**只对 PI 有意义**——商业发票和装箱单是它的派生物。
STAGE_QUOTED = "quoted"
STAGE_DEPOSIT_PAID = "deposit_paid"
STAGE_IN_PRODUCTION = "in_production"
STAGE_SHIPPED = "shipped"
STAGE_BALANCE_PAID = "balance_paid"
STAGE_CLOSED = "closed"
STAGES = (
    STAGE_QUOTED,
    STAGE_DEPOSIT_PAID,
    STAGE_IN_PRODUCTION,
    STAGE_SHIPPED,
    STAGE_BALANCE_PAID,
    STAGE_CLOSED,
)
STAGE_LABELS = {
    STAGE_QUOTED: "已报价",
    STAGE_DEPOSIT_PAID: "定金已到",
    STAGE_IN_PRODUCTION: "生产中",
    STAGE_SHIPPED: "已发货",
    STAGE_BALANCE_PAID: "尾款已到",
    STAGE_CLOSED: "已完成",
}

DOC_STATUS_DRAFT = "draft"
DOC_STATUS_ISSUED = "issued"
DOC_STATUS_VOID = "void"
DOC_STATUSES = (DOC_STATUS_DRAFT, DOC_STATUS_ISSUED, DOC_STATUS_VOID)


class B2BDocument(Base):
    __tablename__ = "b2b_documents"
    __table_args__ = (
        CheckConstraint(
            "doc_type IN ('proforma_invoice', 'commercial_invoice', "
            "'packing_list')",
            name=conv("ck_b2b_documents_doc_type"),
        ),
        CheckConstraint(
            "status IN ('draft', 'issued', 'void')",
            name=conv("ck_b2b_documents_status"),
        ),
        Index("ix_b2b_documents_number", "number", unique=True),
        Index("ix_b2b_documents_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 人看的单号,买家汇款时会写在附言里。全局唯一。
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DOC_STATUS_DRAFT
    )

    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    # 过期就得重开:关税一变货代运费就变,旧价不能一直认。
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)

    # 买方。可从线索池带出来,但**存的是快照**——线索行改了不该动已开的单。
    buyer_company: Mapped[str] = mapped_column(String(200), nullable=False)
    buyer_contact: Mapped[str | None] = mapped_column(String(120), nullable=True)
    buyer_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    buyer_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    ship_to: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 行项目快照:[{sku, name, variant, qty, unit_price, line_total}, ...]
    items_json: Mapped[list[dict[str, object]]] = mapped_column(
        json_type(), nullable=False, default=list
    )
    # 条款/卖方信息/收款信息的快照。发出去之后改 policies.py 不影响旧单。
    terms_json: Mapped[dict[str, object]] = mapped_column(
        json_type(), nullable=False, default=dict
    )

    # 商业发票 / 装箱单指回它们的那张 PI:同一单的三张纸要能串起来。
    source_document_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    # 订单走到哪一步(只对 PI 有意义)。开完 PI 之后此前是没有下文的。
    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STAGE_QUOTED
    )

    # 装箱单要的三个数。**打包时才知道**,所以留空就在纸上印 "TBC",
    # 不假装我们算得出来——报错的装箱单比没有更麻烦。
    carton_count: Mapped[int | None] = mapped_column(nullable=True)
    gross_weight_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    net_weight_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    # 运费单独一行:报出来就是到门含税的全部,买家不用再算。
    freight: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # 样品费抵扣。**这是已经承诺过的**(小窗/批发页/图册/开发信四处都写了
    # "样品费全额抵扣首单"),此前没有任何地方记账——第三个客户就开始虚。
    sample_credit: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
