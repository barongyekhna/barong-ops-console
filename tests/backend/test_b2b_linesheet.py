from __future__ import annotations

import csv
import io
import math
import re
import tracemalloc
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image

from backend.app.modules.b2b.linesheet import (
    LineSheetItem,
    LineSheetMeta,
    LineSheetRequest,
    render_csv,
    render_pdf,
)


pytestmark = pytest.mark.unit


EXPECTED_COLUMNS = [
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
]


def _meta(*, notes: list[str] | None = None) -> LineSheetMeta:
    return LineSheetMeta(
        brand_name="Barong Yekhna",
        legal_entity="Guangzhou Longjie E-Commerce Co., Ltd.",
        contact_email="wholesale@barong.example",
        contact_phone="+1 555 0100",
        address_lines=["123 Trade Street", "Los Angeles, CA 90001"],
        currency="USD",
        edition_label="2026 Fall",
        min_order_value=Decimal("500.00"),
        payment_terms="Net 30",
        notes=notes if notes is not None else ["Prices are valid for this edition."],
    )


def _item(
    sku: str,
    category_path: list[str],
    *,
    image_path: str | None = None,
    name: str | None = None,
    variant_note: str | None = "6 colors assorted",
) -> LineSheetItem:
    return LineSheetItem(
        sku=sku,
        name=name or f"Product {sku}",
        category_path=category_path,
        image_path=image_path,
        wholesale_price=Decimal("12.50"),
        msrp=Decimal("25.00"),
        case_pack=6,
        moq_units=12,
        lead_time_days=14,
        variant_note=variant_note,
    )


def _pdf_page_count(pdf: bytes) -> int:
    return pdf.count(b"/Type /Page ")


def test_pdf_groups_by_category_and_sorts_each_group_by_sku() -> None:
    request = LineSheetRequest(
        meta=_meta(),
        items=[
            _item("TOY-9", ["Toys & Games", "Executive Toys"]),
            _item("HOME-2", ["Home", "Lighting"]),
            _item("TOY-1", ["Toys & Games", "Building Toys"]),
            _item("HOME-1", ["Home", "Lighting"]),
        ],
    )

    pdf = render_pdf(request)

    # 2026-07-27 布局:目录页和产品卡顶栏**都只用叶子类目**——完整五级路径
    # 在卡片宽度下会被截断成没用的前缀,对买手也没意义。断言拆两段,本意不变:
    # 分组正确 + 组内按 SKU 排序。
    assert b"Home > Lighting" not in pdf

    toc_in_order = ["Lighting", "Building Toys", "Executive Toys"]
    toc_positions = [pdf.index(value.encode("ascii")) for value in toc_in_order]
    assert toc_positions == sorted(toc_positions)

    skus_in_order = ["SKU HOME-1", "SKU HOME-2", "SKU TOY-1", "SKU TOY-9"]
    sku_positions = [pdf.index(value.encode("ascii")) for value in skus_in_order]
    assert sku_positions == sorted(sku_positions)
    # 目录页排在所有产品页之前
    assert max(toc_positions) < min(sku_positions)

    # 目录整行可点:每个类目一条 GoTo 链接注解
    assert pdf.count(b"/Subtype /Link") == len(toc_in_order)
    assert b"/S /GoTo" in pdf
    assert b"/MediaBox [0 0 612 792]" in pdf


def test_pdf_renders_300_products_in_expected_page_count_and_bounded_memory() -> None:
    items = [
        _item(f"SKU-{index:04d}", ["Catalog", f"Category {index % 3}"])
        for index in range(300)
    ]
    request = LineSheetRequest(meta=_meta(), items=items)

    tracemalloc.start()
    pdf = render_pdf(request)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # One cover, one contents page, ceil(items / 6) product pages, one notes page.
    # 目录页是 2026-07-27 加的——几十页的图册没目录,买手翻不到自己那一类。
    assert _pdf_page_count(pdf) == math.ceil(300 / 6) + 3
    assert peak_bytes < 32 * 1024 * 1024


def test_pdf_missing_images_render_placeholders_without_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.webp"
    request = LineSheetRequest(
        meta=_meta(),
        items=[
            _item("NO-IMAGE", ["Toys"], image_path=None),
            _item("MISSING", ["Toys"], image_path=str(missing)),
        ],
    )

    pdf = render_pdf(request)

    assert pdf.count(b"(No image)") == 2


def test_pdf_reads_webp_and_embeds_a_thumbnail(tmp_path: Path) -> None:
    image_path = tmp_path / "wide-product.webp"
    Image.new("RGBA", (1200, 300), (210, 30, 80, 180)).save(image_path, "WEBP")
    request = LineSheetRequest(
        meta=_meta(),
        items=[_item("WEBP-1", ["Toys"], image_path=str(image_path))],
    )

    pdf = render_pdf(request)
    image_match = re.search(
        rb"/Subtype /Image /Width (\d+) /Height (\d+).*?/Filter /DCTDecode",
        pdf,
    )

    assert image_match is not None
    width, height = (int(value) for value in image_match.groups())
    assert max(width, height) == 600
    assert pdf.count(b"/Subtype /Image") == 1
    assert b"(No image)" not in pdf


def test_csv_has_exact_columns_order_and_sorted_rows() -> None:
    request = LineSheetRequest(
        meta=_meta(),
        items=[
            _item("B-2", ["Toys", "Puzzles"], variant_note=None),
            _item("A-1", ["Home", "Decor"]),
        ],
    )

    decoded = render_csv(request).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(decoded, newline="")))

    assert rows[0] == EXPECTED_COLUMNS
    assert rows[1] == [
        "Home > Decor",
        "A-1",
        "Product A-1",
        "6 colors assorted",
        "12.50",
        "25.00",
        "6",
        "12",
        "14",
        "",
    ]
    assert rows[2][0:4] == ["Toys > Puzzles", "B-2", "Product B-2", ""]
    assert rows[2][-1] == ""


def test_csv_starts_with_utf8_bom() -> None:
    request = LineSheetRequest(meta=_meta(), items=[])

    assert render_csv(request).startswith(b"\xef\xbb\xbf")


def test_rendering_same_request_twice_is_byte_identical(tmp_path: Path) -> None:
    image_path = tmp_path / "deterministic.webp"
    Image.new("RGB", (80, 120), "navy").save(image_path, "WEBP", lossless=True)
    request = LineSheetRequest(
        meta=_meta(notes=["No generated timestamps are included."]),
        items=[_item("STABLE-1", ["Toys"], image_path=str(image_path))],
    )

    assert render_pdf(request) == render_pdf(request)
    assert render_csv(request) == render_csv(request)
