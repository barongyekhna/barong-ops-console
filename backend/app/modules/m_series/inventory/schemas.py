"""M 系列 · 制造库存的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Kind = Literal["part", "product"]
BomMode = Literal["per_unit", "per_carton"]
DocType = Literal["receipt", "production", "shipment", "adjustment"]

SUGGESTED_UNITS = ("个", "条", "根", "套", "张", "米", "kg", "卷", "箱", "包")


def _strip(value: str) -> str:
    return value.strip()


class ItemCreate(BaseModel):
    kind: Kind
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    unit: str = Field(min_length=1, max_length=20)
    note: str | None = Field(default=None, max_length=2000)

    _strip_code = field_validator("code", "name", "unit")(_strip)


class ItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    note: str | None = Field(default=None, max_length=2000)
    is_archived: bool | None = None


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: Kind
    code: str
    name: str
    unit: str
    note: str | None
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
