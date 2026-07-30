"""Data contracts for rendering a B2B wholesale line sheet."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class LineSheetItem(BaseModel):
    sku: str
    name: str
    category_path: list[str]
    image_path: str | None
    wholesale_price: Decimal
    msrp: Decimal
    case_pack: int
    moq_units: int
    lead_time_days: int
    variant_note: str | None


class LineSheetMeta(BaseModel):
    brand_name: str
    legal_entity: str
    contact_email: str
    contact_phone: str
    address_lines: list[str]
    currency: str
    edition_label: str
    min_order_value: Decimal
    payment_terms: str
    notes: list[str]


class LineSheetRequest(BaseModel):
    meta: LineSheetMeta
    items: list[LineSheetItem]
