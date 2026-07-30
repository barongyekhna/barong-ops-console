"""Pydantic contracts for the B2B wholesale catalogue."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 用户拍板(2026-07-27):某个类目里"可出图册"的产品少于 30 个时,
# 不允许拿这个类目去挖客户——目录太薄,第一印象砸了就回不来。
CATEGORY_PROSPECTING_MIN_READY_ITEMS = 30


class PriceTier(BaseModel):
    """阶梯批发价:订够 min_qty 件,单价按 unit_price 算。"""

    model_config = ConfigDict(extra="forbid")

    min_qty: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)


class WholesaleItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    k_product_id: UUID | None = None
    woo_product_id: int | None = None
    sku: str
    product_name: str
    category_path: list[str] = Field(default_factory=list)
    image_url: str | None = None
    msrp: Decimal | None = None
    wholesale_price: Decimal | None = None
    price_tiers: list[PriceTier] = Field(default_factory=list)
    case_pack: int | None = None
    moq_units: int | None = None
    lead_time_days: int | None = None
    variant_note: str | None = None
    notes: str | None = None
    status: str
    needs_review: bool
    review_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def margin_percent(self) -> Decimal | None:
        if self.msrp is None or self.wholesale_price is None or self.msrp == 0:
            return None
        return (self.msrp - self.wholesale_price) / self.msrp * 100


class WholesaleItemListResponse(BaseModel):
    items: list[WholesaleItemRead] = Field(default_factory=list)
    count: int = 0
    pending_count: int = 0
    ready_count: int = 0
    needs_review_count: int = 0


class WholesaleItemPatch(BaseModel):
    """改批发字段。只收批发侧的数据——零售侧(名称/图/零售价)的真相源
    永远是 K 和 Woo,不给从这里改的口子,否则两边一定会漂。"""

    model_config = ConfigDict(extra="forbid")

    wholesale_price: Decimal | None = Field(default=None, ge=0)
    price_tiers: list[PriceTier] | None = None
    case_pack: int | None = Field(default=None, gt=0)
    moq_units: int | None = Field(default=None, gt=0)
    lead_time_days: int | None = Field(default=None, ge=0)
    variant_note: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    clear_review_flag: bool = False

    @field_validator("price_tiers")
    @classmethod
    def _tiers_ascending(
        cls,
        value: list[PriceTier] | None,
    ) -> list[PriceTier] | None:
        if not value:
            return value
        quantities = [tier.min_qty for tier in value]
        if len(set(quantities)) != len(quantities):
            raise ValueError("Price tiers must have distinct minimum quantities.")
        if quantities != sorted(quantities):
            raise ValueError("Price tiers must be ordered by minimum quantity.")
        return value


class WholesaleItemBatchPatchEntry(WholesaleItemPatch):
    item_id: UUID


class WholesaleItemBatchPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WholesaleItemBatchPatchEntry] = Field(default_factory=list)


class CategoryReadiness(BaseModel):
    """一个类目能不能拿去挖客户。"""

    category_path: list[str] = Field(default_factory=list)
    total_items: int = 0
    ready_items: int = 0
    pending_items: int = 0
    needs_review_items: int = 0
    prospecting_unlocked: bool = False
    shortfall: int = 0
    # 这个类目落进了哪些店型（对外英文名）。**空 = 这批货不会出现在任何批发页
    # 上，也不进图册**，而且此前是静默的——产品多了根本发现不了。
    store_types: list[str] = Field(default_factory=list)
    # 空店型的两种原因，必须分开：
    #   blocked  = 目录里**故意屏蔽**（武器/成人/医疗/烟酒），不该做 B2B
    #   unmapped = 只是还没写映射规则，补一条就能用
    coverage: str = "covered"


class CategoryReadinessResponse(BaseModel):
    categories: list[CategoryReadiness] = Field(default_factory=list)
    min_ready_items: int = CATEGORY_PROSPECTING_MIN_READY_ITEMS


class IngestResult(BaseModel):
    created: int = 0
    updated: int = 0
    flagged_for_review: int = 0
    skipped: int = 0


class LineSheetExportRequest(BaseModel):
    """导出图册。按类目发给对的买家,别把 300 个品一股脑丢过去。"""

    model_config = ConfigDict(extra="forbid")

    fmt: str = Field(default="pdf", pattern="^(pdf|csv)$")
    item_ids: list[UUID] | None = None
    # 首选按店型出(一个店型可横跨多个类目);category_prefix 保留给临时切片。
    store_type: str | None = Field(default=None, max_length=64)
    category_prefix: list[str] | None = None
    edition_label: str = Field(default="", max_length=64)
    include_not_ready: bool = False
