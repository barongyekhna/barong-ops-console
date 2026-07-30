"""Deterministic CSV rendering for B2B wholesale line sheets."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from .schemas import LineSheetItem, LineSheetRequest


CSV_COLUMNS = (
    "Category",
    "SKU",
    "Product Name",
    "Variant",
    "Wholesale Price",
    "Volume Pricing",
    "MSRP",
    "Case Pack",
    "MOQ (units)",
    "Lead Time (days)",
    "Order Qty",
)


def tier_text(item: LineSheetItem) -> str:
    """`100+ $16.50 | 500+ $15.00`。没有阶梯价就留空,不写 "N/A" 之类的噪音。

    **在这里再排一次序**,不依赖上游传进来是有序的:乱序印出来
    `500+ $2.00 | 100+ $2.20` 读着像涨价,买手会当成写错了。
    """
    return " | ".join(
        f"{qty}+ ${_decimal_text(price)}"
        for qty, price in sorted(item.price_tiers or [])
    )


def _sorted_items(items: list[LineSheetItem]) -> list[LineSheetItem]:
    """Return items in category-path/SKU order without mutating the request."""

    return sorted(items, key=lambda item: (tuple(item.category_path), item.sku))


def _decimal_text(value: Decimal) -> str:
    """Use ordinary decimal notation and never scientific notation."""

    return format(value, "f")


def render_csv(request: LineSheetRequest) -> bytes:
    """Render an Excel-friendly UTF-8 CSV, including its BOM."""

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)

    for item in _sorted_items(request.items):
        writer.writerow(
            (
                " > ".join(item.category_path),
                item.sku,
                item.name,
                item.variant_note or "",
                _decimal_text(item.wholesale_price),
                tier_text(item),
                _decimal_text(item.msrp),
                item.case_pack,
                item.moq_units,
                item.lead_time_days,
                "",
            )
        )

    return output.getvalue().encode("utf-8-sig")
