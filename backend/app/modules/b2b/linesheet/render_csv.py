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
    "MSRP",
    "Case Pack",
    "MOQ (units)",
    "Lead Time (days)",
    "Order Qty",
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
                _decimal_text(item.msrp),
                item.case_pack,
                item.moq_units,
                item.lead_time_days,
                "",
            )
        )

    return output.getvalue().encode("utf-8-sig")
