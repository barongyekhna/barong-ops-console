"""M 系列 · 出货成本明细的 SQLAlchemy 模型。

一句话总纲:**价格不是属性,是事件**。

物料主档上永远没有"单价"字段,就像它上面永远没有"库存数"字段一样。铜价涨了不是
去改一个格子,而是下一批入库时多出一条流水,老批次一个字不动。于是历史永远解释得
清:三个月前那张报价单为什么是 12.40,点开就能看到它吃的是哪一批料。

这里的三张事件表(参考价 / 工价 / 出厂价)与流水上的批次价共用同一条规矩:**只增
不改不删**,"当前值"= 按 ``effective_date`` 取最新一行。改价 = 新增一行,于是每样
东西都自带一条价格曲线。

成本在**生产那一刻**就冻结进生产单的 ``payload_json.cost_snapshot``(见
``..inventory.service.production``),不在这里存;这里存的是**给人看的那份文档**——
成本表快照与它的分享台账。两者不是一回事:前者是"这批成品花了多少",后者是"我在
哪一天把哪些数字发给了谁"。

归属列同样叫 ``factory_org_id`` 而不是 ``org_id``:带 ``org_id`` 的模型会被 C18G
行级隔离自动盖成最早建的贸易公司。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
from ..inventory.models import MONEY, QTY

# 人工计价方式:每件消耗一次 / 整批消耗一次(调机、开模摊销)
LABOR_MODE_PER_UNIT = "per_unit"
LABOR_MODE_PER_BATCH = "per_batch"
ALLOWED_LABOR_MODES = (LABOR_MODE_PER_UNIT, LABOR_MODE_PER_BATCH)

# 参考价的来源。**没有 receipt**:入过库的价格在流水上,不在这张表里,
# 两处各存一份就等于给自己留一个对不上的机会。
PRICE_SOURCE_QUOTE = "quote"
PRICE_SOURCE_MANUAL = "manual"
ALLOWED_PRICE_SOURCES = (PRICE_SOURCE_QUOTE, PRICE_SOURCE_MANUAL)

# 成本表的两种成色
BASIS_ACTUAL = "actual"  # 有成品库存:读队头那批生产时冻结的真实成本
BASIS_ESTIMATE = "estimate"  # 没生产过/已发完:按当前物料队头预估
ALLOWED_BASES = (BASIS_ACTUAL, BASIS_ESTIMATE)

# 快照行的两个区块
LINE_KIND_MATERIAL = "material"
LINE_KIND_LABOR = "labor"
ALLOWED_LINE_KINDS = (LINE_KIND_MATERIAL, LINE_KIND_LABOR)

# 分享口径。price_only 版本在**生成时**就不含成本数字,不是前端藏起来——
# 所以转发也漏不出去。
SHARE_MODE_FULL = "full"
SHARE_MODE_PRICE_ONLY = "price_only"
ALLOWED_SHARE_MODES = (SHARE_MODE_FULL, SHARE_MODE_PRICE_ONLY)

# 报价有效期:全表取最短。只要有一个波动料就是 7 天。
VALID_DAYS_VOLATILE = 7
VALID_DAYS_NORMAL = 30


class MfgLaborProcess(Base):
    """工厂级工序库:组装、焊接、测试、包装……

    工序做成工厂级而不是产品内联,是为了让"涨工资"只改一次:工价挂在工序上,
    产品只挂接"用哪几道、每道多少",下次生产自动按新工价算。产品内联的话,
    工价一变就要一个产品一个产品地改,漏改的后果是成本算低、报价亏钱。
    """

    __tablename__ = "mfg_labor_processes"
    __table_args__ = (
        UniqueConstraint(
            "factory_org_id", "name", name="uq_mfg_labor_processes_factory_org_id"
        ),
        Index("ix_mfg_labor_processes_factory", "factory_org_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfgLaborRate(Base):
    """工价事件。改价 = 新增一行,永不 UPDATE。"""

    __tablename__ = "mfg_labor_rates"
    __table_args__ = (
        CheckConstraint("rate >= 0", name=conv("ck_mfg_labor_rates_rate")),
        Index(
            "ix_mfg_labor_rates_process_effective",
            "process_id",
            "effective_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    process_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("mfg_labor_processes.id", ondelete="CASCADE"),
        nullable=False,
    )
    rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfgLaborLine(Base):
    """产品挂接工序:这个成品要走哪几道工序、每道多少。

    ``mode=per_unit`` 时单位人工 = ``rate × qty``;``per_batch`` 时整批算一次,
    单位人工 = ``rate × qty / 批量``——1000 件和 100 件摊下来天差地别,这一条
    直接决定小单能不能接。
    """

    __tablename__ = "mfg_labor_lines"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "process_id", name="uq_mfg_labor_lines_product_id"
        ),
        CheckConstraint(
            "mode IN ('per_unit', 'per_batch')", name=conv("ck_mfg_labor_lines_mode")
        ),
        CheckConstraint("qty > 0", name=conv("ck_mfg_labor_lines_qty")),
        Index("ix_mfg_labor_lines_product_id", "product_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfg_items.id", ondelete="CASCADE"), nullable=False
    )
    process_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfg_labor_processes.id", ondelete="RESTRICT"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MfgItemPrice(Base):
    """物料的**参考价**——只放没入过库的东西。

    入过库的价格在 ``mfg_movements.unit_price`` 上,这里不重复存。这张表服务的是
    "供应商报了价但还没进过货"的物料,让一个从没生产过的成品也能出一张标着
    「预估」的表。前端要把这种行明确标成"参考价·未入库",不能跟真实批次价混着看。
    """

    __tablename__ = "mfg_item_prices"
    __table_args__ = (
        CheckConstraint(
            "source IN ('quote', 'manual')", name=conv("ck_mfg_item_prices_source")
        ),
        CheckConstraint("unit_price >= 0", name=conv("ck_mfg_item_prices_unit_price")),
        Index(
            "ix_mfg_item_prices_item_effective",
            "item_id",
            "effective_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfg_items.id", ondelete="CASCADE"), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    freight_per_unit: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0")
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfgSalePrice(Base):
    """成品出厂价事件。

    成本是算出来的,出厂价是**人定的**——成本之上加多少利润,只有厂长和 owner 说
    了算,所以写这张表要 ``mfg.cost.price`` 权限。挂在产品档案上而不是每张表填一
    次:定一次全站带出,单张表要让价可以就地覆盖(覆盖值进那张表的快照,不回写
    这里)。
    """

    __tablename__ = "mfg_sale_prices"
    __table_args__ = (
        CheckConstraint("unit_price >= 0", name=conv("ck_mfg_sale_prices_unit_price")),
        Index(
            "ix_mfg_sale_prices_product_effective",
            "product_id",
            "effective_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfg_items.id", ondelete="CASCADE"), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfgCostSheet(Base):
    """成本表快照:某一刻、某个成品、某个批量下的一份定稿文档。

    发出去的数字再也不能变,所以这是一份**快照**而不是一个视图:生成时把每一行
    抄成文本存死,物料改名、BOM 改版、价格翻倍都影响不到它。

    ``missing_price_count > 0`` 时,``unit_cost`` 与各项合计一律为 NULL——缺价绝不
    当 0 算,给一个看着完整的假总价比不给危险得多。``sale_price`` 是手填的,不依赖
    成本,所以照常有值。
    """

    __tablename__ = "mfg_cost_sheets"
    __table_args__ = (
        UniqueConstraint(
            "factory_org_id", "sheet_no", name="uq_mfg_cost_sheets_factory_org_id"
        ),
        CheckConstraint(
            "basis IN ('actual', 'estimate')", name=conv("ck_mfg_cost_sheets_basis")
        ),
        CheckConstraint("batch_qty > 0", name=conv("ck_mfg_cost_sheets_batch_qty")),
        Index(
            "ix_mfg_cost_sheets_factory_created",
            "factory_org_id",
            "created_at",
        ),
        Index("ix_mfg_cost_sheets_product_id", "product_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    sheet_no: Mapped[str] = mapped_column(String(32), nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfg_items.id", ondelete="RESTRICT"), nullable=False
    )
    # 抄一份,产品改名后老表照旧
    product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_unit: Mapped[str] = mapped_column(String(20), nullable=False)
    batch_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    basis: Mapped[str] = mapped_column(String(16), nullable=False)
    # actual 时指向那张冻结了成本的生产单
    source_document_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("mfg_documents.id", ondelete="SET NULL"), nullable=True
    )
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    has_volatile: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    missing_price_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # 缺价时这四个全是 NULL,不是 0
    material_total: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    freight_total: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    labor_total: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    sale_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    actor_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfgCostSheetLine(Base):
    """快照行。物料区与人工区共用一张表,靠 ``kind`` 分区。

    存的是**抄下来的文本**而不是外键引用:三个月后物料改了名、BOM 换了配方,这一
    行还是当时的样子。``batch_breakdown`` 记跨批拆解——一个加权出来的 12.40 如果不
    把"哪几批、各多少、各什么价"一起留下,以后没人解释得清它是怎么来的。
    """

    __tablename__ = "mfg_cost_sheet_lines"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('material', 'labor')",
            name=conv("ck_mfg_cost_sheet_lines_kind"),
        ),
        Index("ix_mfg_cost_sheet_lines_sheet_id", "sheet_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    sheet_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfg_cost_sheets.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    unit_freight: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    line_total: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    is_missing_price: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # 人工行用它记 per_unit / per_batch;物料行记 per_unit / per_carton
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    batch_breakdown: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )


class MfgCostSheetShare(Base):
    """分享台账:谁,在什么时候,把哪一份,用什么口径,发给了谁。

    分享是**外部副作用**:数字一旦进了对方的聊天窗口就收不回来了。所以这张表记的
    不是"我调用了发消息接口",而是"我发完之后回读,确认那条消息真的在那儿"——
    ``verified_at`` 有值才算数。接口返回 200 不算。
    """

    __tablename__ = "mfg_cost_sheet_shares"
    __table_args__ = (
        CheckConstraint(
            "share_mode IN ('full', 'price_only')",
            name=conv("ck_mfg_cost_sheet_shares_share_mode"),
        ),
        Index("ix_mfg_cost_sheet_shares_sheet_id", "sheet_id"),
        Index(
            "ix_mfg_cost_sheet_shares_factory_created",
            "factory_org_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    factory_org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    sheet_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfg_cost_sheets.id", ondelete="CASCADE"), nullable=False
    )
    share_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    card_token: Mapped[str] = mapped_column(String(8), nullable=False)
    recipient_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # 回读确认那条消息真的存在的时刻;为空 = 发过但没验证上,不算数
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actor_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
