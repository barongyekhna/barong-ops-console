"""M 系列 · 出货成本明细的请求/响应模型。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

LaborMode = Literal["per_unit", "per_batch"]
PriceSource = Literal["quote", "manual"]
Basis = Literal["actual", "estimate"]
LineKind = Literal["material", "labor"]
ShareMode = Literal["full", "price_only"]

MONEY = {"max_digits": 14, "decimal_places": 4}
QTY = {"max_digits": 14, "decimal_places": 3}


def _strip(value: str) -> str:
    return value.strip()


# ---------------------------------------------------------------- 工序库


class LaborProcessCreate(BaseModel):
    """建工序时必须同时给出首个工价——没有工价的工序算不出成本,
    留着只会让人以为那道工序不要钱。"""

    name: str = Field(min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    rate: Decimal = Field(ge=0, **MONEY)
    effective_date: date | None = None

    _strip_name = field_validator("name")(_strip)


class LaborProcessPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    is_archived: bool | None = None


class LaborRateCreate(BaseModel):
    """改工价 = 新增一条事件,永不改老行。"""

    rate: Decimal = Field(ge=0, **MONEY)
    effective_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class LaborRateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rate: Decimal
    effective_date: date
    note: str | None
    created_by_name: str
    created_at: datetime


class LaborProcessRead(BaseModel):
    id: UUID
    name: str
    note: str | None
    position: int
    is_archived: bool
    # 当前工价;从没定过价就是 None
    rate: Decimal | None = None
    rate_effective_date: date | None = None
    used_by_product_count: int = 0


class LaborProcessListResponse(BaseModel):
    items: list[LaborProcessRead]
    total: int


# ---------------------------------------------------------------- 产品挂接工序


class LaborLineInput(BaseModel):
    process_id: UUID
    mode: LaborMode
    qty: Decimal = Field(gt=0, **QTY)


class LaborReplace(BaseModel):
    lines: list[LaborLineInput] = Field(default_factory=list, max_length=100)

    @field_validator("lines")
    @classmethod
    def _no_duplicate_process(
        cls, lines: list[LaborLineInput]
    ) -> list[LaborLineInput]:
        seen: set[UUID] = set()
        for line in lines:
            if line.process_id in seen:
                raise ValueError("同一道工序在一个产品上只能出现一次")
            seen.add(line.process_id)
        return lines


class LaborLineRead(BaseModel):
    id: UUID
    process_id: UUID
    process_name: str
    mode: LaborMode
    qty: Decimal
    rate: Decimal | None
    position: int


class ProductLaborRead(BaseModel):
    product_id: UUID
    lines: list[LaborLineRead]


# ---------------------------------------------------------------- 价格事件


class SalePriceCreate(BaseModel):
    unit_price: Decimal = Field(ge=0, **MONEY)
    effective_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class SalePriceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    unit_price: Decimal
    effective_date: date
    note: str | None
    created_by_name: str
    created_at: datetime


class SalePriceListResponse(BaseModel):
    items: list[SalePriceRead]
    total: int


class ReferencePriceCreate(BaseModel):
    """供应商报了价但还没进过货的物料。入过库的价格在流水上,不走这里。"""

    unit_price: Decimal = Field(ge=0, **MONEY)
    freight_per_unit: Decimal = Field(default=Decimal("0"), ge=0, **MONEY)
    source: PriceSource = "quote"
    effective_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class ReferencePriceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    unit_price: Decimal
    freight_per_unit: Decimal
    source: PriceSource
    effective_date: date
    created_by_name: str
    created_at: datetime


# ---------------------------------------------------------------- 成本表


class BatchDrawRead(BaseModel):
    """跨批时的拆解:一个加权出来的 12.40 是从哪几批取的。"""

    movement_id: UUID
    qty: Decimal
    unit_price: Decimal | None = None
    unit_freight: Decimal | None = None
    at: datetime
    estimated: bool = False
    extrapolated: bool = False


class CostLineRead(BaseModel):
    kind: LineKind
    code: str | None = None
    name: str
    unit: str
    mode: str | None = None
    bom_qty: Decimal | None = None
    qty: Decimal
    unit_price: Decimal | None = None
    unit_freight: Decimal | None = None
    line_material: Decimal | None = None
    line_freight: Decimal | None = None
    line_total: Decimal | None = None
    missing_price: bool = False
    # batch = 真实入库批次价;reference = 供应商报价(没入过库)
    price_source: str | None = None
    crosses_batches: bool = False
    extrapolated: Decimal | None = None
    estimated_price: bool = False
    batches: list[BatchDrawRead] = Field(default_factory=list)


class CostTotals(BaseModel):
    """缺价时四项全为 None,不是 0。

    前端必须把 None 渲染成 `—` 并显示 ``missing_price_count``,绝不能拿 0 顶——
    一个看着完整的假总价会被直接拿去报价。
    """

    material_total: Decimal | None = None
    freight_total: Decimal | None = None
    labor_total: Decimal | None = None
    unit_cost: Decimal | None = None
    missing_price_count: int = 0


class CostSheetPreview(BaseModel):
    """实时算出来的表,还没定稿落库。改批量数就重算一份。"""

    product_id: UUID
    product_code: str
    product_name: str
    product_unit: str
    batch_qty: Decimal
    basis: Basis
    source_document_id: UUID | None = None
    source_doc_no: str | None = None
    stock: Decimal
    materials: list[CostLineRead]
    labor: list[CostLineRead]
    totals: CostTotals
    sale_price: Decimal | None = None
    unit_margin: Decimal | None = None
    margin_rate: Decimal | None = None
    batch_total: Decimal | None = None
    has_volatile: bool = False
    expires_on: date
    valid_days: int


class ProductCostRow(BaseModel):
    """列表页一行。"""

    product_id: UUID
    code: str
    name: str
    unit: str
    stock: Decimal
    basis: Basis
    unit_cost: Decimal | None = None
    sale_price: Decimal | None = None
    margin_rate: Decimal | None = None
    missing_price_count: int = 0
    bom_line_count: int = 0
    labor_line_count: int = 0


class ProductCostListResponse(BaseModel):
    items: list[ProductCostRow]
    total: int


class CostSheetCreate(BaseModel):
    """定稿:把当前这份实时结果冻成快照。分享的一定是快照,不是实时表。"""

    product_id: UUID
    batch_qty: Decimal = Field(gt=0, **QTY)
    # 本单让价:不回写产品档案的出厂价
    sale_price_override: Decimal | None = Field(default=None, ge=0, **MONEY)
    note: str | None = Field(default=None, max_length=2000)


class CostSheetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sheet_no: str
    product_id: UUID
    product_code: str
    product_name: str
    product_unit: str
    batch_qty: Decimal
    basis: Basis
    expires_on: date
    has_volatile: bool
    missing_price_count: int
    material_total: Decimal | None
    freight_total: Decimal | None
    labor_total: Decimal | None
    unit_cost: Decimal | None
    sale_price: Decimal | None
    actor_name: str
    note: str | None
    created_at: datetime


class CostSheetDetail(CostSheetRead):
    materials: list[CostLineRead] = Field(default_factory=list)
    labor: list[CostLineRead] = Field(default_factory=list)
    shares: list["CostShareRead"] = Field(default_factory=list)


class CostSheetListResponse(BaseModel):
    items: list[CostSheetRead]
    total: int


# ---------------------------------------------------------------- 分享


class CostShareRequest(BaseModel):
    """把一份快照通过 C19 发给人。

    ``share_mode='price_only'`` 时,生成的卡片正文里**根本没有成本数字**——不是前端
    藏起来,所以对方转发出去也漏不了。
    """

    recipient_user_ids: list[int] = Field(min_length=1, max_length=20)
    share_mode: ShareMode = "full"
    message: str | None = Field(default=None, max_length=500)


class CostShareRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    share_mode: ShareMode
    recipient_user_id: str
    recipient_name: str
    conversation_id: str
    message_id: str
    verified_at: datetime | None
    actor_name: str
    created_at: datetime


class CostShareResult(BaseModel):
    """``delivered`` 只在**回读确认那条消息真的存在**之后才为 true。
    接口返回 200 不算数。"""

    sheet_no: str
    share_mode: ShareMode
    delivered: list[CostShareRead]
    failed: list[dict[str, Any]] = Field(default_factory=list)


CostSheetDetail.model_rebuild()
