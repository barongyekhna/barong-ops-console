"""M 系列 · 制造库存的请求/响应模型。"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["part", "product"]
BomMode = Literal["per_unit", "per_carton"]
DocType = Literal["receipt", "production", "shipment", "adjustment"]

SUGGESTED_UNITS = ("个", "条", "根", "套", "张", "米", "kg", "卷", "箱", "包")


def _strip(value: str) -> str:
    return value.strip()


# 组码:2~4 个大写字母(TBL / PK);手填编码:大写字母数字与连字符
GROUP_CODE_PATTERN = r"^[A-Z]{2,4}$"
MANUAL_CODE_PATTERN = r"^[A-Z0-9][A-Z0-9-]{0,63}$"


def _upper(value: str) -> str:
    return value.strip().upper()


class CodeGroupCreate(BaseModel):
    kind: Kind
    code: str = Field(min_length=2, max_length=4, pattern=GROUP_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=255)

    _upper_code = field_validator("code", mode="before")(
        lambda v: _upper(v) if isinstance(v, str) else v
    )
    _strip_name = field_validator("name")(_strip)


class CodeGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: Kind
    code: str
    name: str
    next_no: int
    is_archived: bool
    item_count: int = 0


class CodeGroupListResponse(BaseModel):
    items: list[CodeGroupRead]
    total: int


class CodeSuggestion(BaseModel):
    code: str
    taken: bool


class NextCodePreview(BaseModel):
    group_id: UUID
    code: str


class ItemCreate(BaseModel):
    """自动编码:给 ``group_id``,编码由系统按组发号;手填:给 ``code``。二选一。"""

    kind: Kind
    group_id: UUID | None = None
    code: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    unit: str = Field(min_length=1, max_length=20)
    note: str | None = Field(default=None, max_length=2000)

    _strip_fields = field_validator("name", "unit")(_strip)

    @field_validator("code", mode="before")
    @classmethod
    def _normalize_code(cls, value: object) -> object:
        if isinstance(value, str):
            value = _upper(value)
            return value or None
        return value

    @model_validator(mode="after")
    def _one_of_code_or_group(self) -> "ItemCreate":
        if (self.code is None) == (self.group_id is None):
            raise ValueError("编码要么选系列/大类自动生成,要么手填,二选一")
        if self.code is not None and not re.fullmatch(
            MANUAL_CODE_PATTERN, self.code
        ):
            raise ValueError("手填编码只能用大写字母、数字和连字符")
        return self


class ItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    note: str | None = Field(default=None, max_length=2000)
    is_archived: bool | None = None
    # 只有还没有任何流水的主档可以改编码
    code: str | None = Field(default=None, min_length=1, max_length=64, pattern=MANUAL_CODE_PATTERN)

    _upper_code = field_validator("code", mode="before")(
        lambda v: _upper(v) if isinstance(v, str) else v
    )


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: Kind
    code: str
    name: str
    unit: str
    note: str | None
    group_id: UUID | None = None
    group_code: str | None = None
    group_name: str | None = None
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class StockRow(ItemRead):
    stock: Decimal
    bom_line_count: int = 0


class StockListResponse(BaseModel):
    items: list[StockRow]
    total: int


class ItemListResponse(BaseModel):
    items: list[ItemRead]
    total: int


class BomLineInput(BaseModel):
    part_id: UUID
    mode: BomMode
    qty: Decimal = Field(gt=0, max_digits=14, decimal_places=3)


class BomReplace(BaseModel):
    lines: list[BomLineInput] = Field(default_factory=list, max_length=200)

    @field_validator("lines")
    @classmethod
    def _no_duplicate_parts(cls, lines: list[BomLineInput]) -> list[BomLineInput]:
        seen: set[UUID] = set()
        for line in lines:
            if line.part_id in seen:
                raise ValueError("同一个物料在配件清单里只能出现一次")
            seen.add(line.part_id)
        return lines


class BomLineRead(BaseModel):
    id: UUID
    part_id: UUID
    part_code: str
    part_name: str
    part_unit: str
    mode: BomMode
    qty: Decimal
    position: int


class BomRead(BaseModel):
    product_id: UUID
    lines: list[BomLineRead]


class ReceiptLine(BaseModel):
    item_id: UUID
    qty: Decimal = Field(gt=0, max_digits=14, decimal_places=3)


class ReceiptCreate(BaseModel):
    lines: list[ReceiptLine] = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class ProductionCreate(BaseModel):
    product_id: UUID
    qty: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    note: str | None = Field(default=None, max_length=2000)


class ShipmentCreate(BaseModel):
    product_id: UUID
    qty: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    note: str | None = Field(default=None, max_length=2000)


class AdjustmentCreate(BaseModel):
    item_id: UUID
    qty_delta: Decimal = Field(max_digits=14, decimal_places=3)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("qty_delta")
    @classmethod
    def _non_zero(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("调整数量不能为 0")
        return value


class RequirementRow(BaseModel):
    item_id: UUID
    code: str
    name: str
    unit: str
    mode: BomMode
    bom_qty: Decimal
    required: Decimal
    available: Decimal
    short: Decimal


class ProductionPreview(BaseModel):
    product_id: UUID
    qty: Decimal
    requirements: list[RequirementRow]
    feasible: bool


class MovementRead(BaseModel):
    id: UUID
    document_id: UUID
    doc_no: str
    doc_type: DocType
    item_id: UUID
    item_code: str
    item_name: str
    item_unit: str
    qty_delta: Decimal
    created_at: datetime


class MovementListResponse(BaseModel):
    items: list[MovementRead]
    total: int


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    doc_type: DocType
    doc_no: str
    actor_user_id: str
    actor_name: str
    note: str | None
    payload_json: dict[str, Any]
    created_at: datetime


class DocumentDetail(DocumentRead):
    movements: list[MovementRead]


class DocumentListResponse(BaseModel):
    items: list[DocumentRead]
    total: int


class ShortageDetail(BaseModel):
    message: str
    shortages: list[RequirementRow]


class FactoryContextRead(BaseModel):
    factory_org_id: str
    org_name: str
    suggested_units: list[str]
