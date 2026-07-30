"""Dependency-light, deterministic PDF rendering for wholesale line sheets.

The PDF writer is intentionally small.  Pillow is used only to decode local
product images and create bounded JPEG thumbnails; the PDF structure itself is
written with the Python standard library.  This avoids native cairo/pango
dependencies and keeps dates or other run-specific metadata out of the file.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from PIL import Image, ImageOps

from .schemas import LineSheetItem, LineSheetMeta, LineSheetRequest


PAGE_WIDTH = 612
PAGE_HEIGHT = 792
PRODUCTS_PER_PAGE = 6

_MARGIN = 36
_CONTENT_TOP = 724
_CONTENT_BOTTOM = 52
_COLUMN_GAP = 12
_ROW_GAP = 8
_CARD_WIDTH = (PAGE_WIDTH - 2 * _MARGIN - _COLUMN_GAP) / 2
_CARD_HEIGHT = (_CONTENT_TOP - _CONTENT_BOTTOM - 2 * _ROW_GAP) / 3


def _sorted_items(items: list[LineSheetItem]) -> list[LineSheetItem]:
    return sorted(items, key=lambda item: (tuple(item.category_path), item.sku))


def _category_text(item: LineSheetItem) -> str:
    return " > ".join(item.category_path) or "Uncategorized"


def _category_band_text(item: LineSheetItem) -> str:
    """卡片顶栏用叶子类目。

    完整路径可能有五级(Sporting Goods > Outdoor Recreation > Camping &
    Hiking > Portable Toilets & Showers > Portable Showers & Privacy
    Enclosures),在卡片宽度下必然被截断成一串没用的前缀。叶子才是买家真正
    关心的那个词;完整路径放在目录页。
    """
    if not item.category_path:
        return "Uncategorized"
    return item.category_path[-1]


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _pdf_number(value: float | int) -> str:
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


# 产品名/变体里常混进排版字符(非断行连字符、弯引号、省略号)。cp1252 编不了
# 的会变成问号,图册上出现 "Jack?o'?lantern" 很难看。先归一成 ASCII 等价物。
_TYPOGRAPHIC_FALLBACKS = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u2026": "...", "\u00a0": " ", "\u202f": " ", "\u2009": " ",
}


def _normalize_typography(value: str) -> str:
    for source, target in _TYPOGRAPHIC_FALLBACKS.items():
        if source in value:
            value = value.replace(source, target)
    return value


def _pdf_string(value: str) -> str:
    """Encode a string for a WinAnsi PDF literal string."""

    encoded = _normalize_typography(value).encode("cp1252", errors="replace")
    escaped: list[str] = []
    for byte in encoded:
        if byte in (ord("("), ord(")"), ord("\\")):
            escaped.append("\\" + chr(byte))
        elif byte < 32 or byte >= 127:
            escaped.append(f"\\{byte:03o}")
        else:
            escaped.append(chr(byte))
    return "".join(escaped)


def _character_width(character: str, font_size: float) -> float:
    if character in " ilI.,:;'|!":
        factor = 0.28
    elif character in "MW@%&#":
        factor = 0.88
    elif character.isupper() or character.isdigit():
        factor = 0.62
    else:
        factor = 0.50
    return factor * font_size


def _text_width(value: str, font_size: float) -> float:
    value = _normalize_typography(value)
    return sum(_character_width(character, font_size) for character in value)


def _fit_text(value: str, font_size: float, max_width: float) -> str:
    if _text_width(value, font_size) <= max_width:
        return value
    suffix = "..."
    available = max_width - _text_width(suffix, font_size)
    fitted: list[str] = []
    width = 0.0
    for character in value:
        character_width = _character_width(character, font_size)
        if width + character_width > available:
            break
        fitted.append(character)
        width += character_width
    return "".join(fitted).rstrip() + suffix


def _wrap_text(value: str, font_size: float, max_width: float) -> list[str]:
    """Wrap text by words, splitting an overlong word when necessary."""

    normalized = " ".join(value.split())
    if not normalized:
        return []

    lines: list[str] = []
    current = ""
    for word in normalized.split(" "):
        candidate = word if not current else f"{current} {word}"
        if _text_width(candidate, font_size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        while _text_width(word, font_size) > max_width:
            split_at = 1
            while (
                split_at < len(word)
                and _text_width(word[: split_at + 1], font_size) <= max_width
            ):
                split_at += 1
            lines.append(word[:split_at])
            word = word[split_at:]
        current = word
    if current:
        lines.append(current)
    return lines


@dataclass(frozen=True)
class _ImageAsset:
    name: str
    width: int
    height: int
    jpeg_bytes: bytes


@dataclass
class _Page:
    commands: list[str] = field(default_factory=list)
    image_names: set[str] = field(default_factory=set)
    # (x0, y0, x1, y1, 目标页序号) —— 目录页靠它做可点击跳转。
    links: list[tuple[float, float, float, float, int]] = field(
        default_factory=list
    )


class _Canvas:
    def __init__(self, page: _Page) -> None:
        self.page = page

    def _add(self, command: str) -> None:
        self.page.commands.append(command + "\n")

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        size: float = 10,
        bold: bool = False,
        color: tuple[float, float, float] = (0.12, 0.14, 0.17),
    ) -> None:
        font = "F2" if bold else "F1"
        self._add(
            "BT "
            f"/{font} {_pdf_number(size)} Tf "
            f"{_pdf_number(color[0])} {_pdf_number(color[1])} "
            f"{_pdf_number(color[2])} rg "
            f"1 0 0 1 {_pdf_number(x)} {_pdf_number(y)} Tm "
            f"({_pdf_string(value)}) Tj ET"
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        color: tuple[float, float, float] = (0.75, 0.77, 0.80),
        width: float = 1,
    ) -> None:
        self._add(
            f"{_pdf_number(color[0])} {_pdf_number(color[1])} "
            f"{_pdf_number(color[2])} RG {_pdf_number(width)} w "
            f"{_pdf_number(x1)} {_pdf_number(y1)} m "
            f"{_pdf_number(x2)} {_pdf_number(y2)} l S"
        )

    def rectangle(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: tuple[float, float, float] | None = None,
        stroke: tuple[float, float, float] | None = (0.78, 0.80, 0.83),
        line_width: float = 0.8,
    ) -> None:
        operations: list[str] = []
        if fill is not None:
            operations.append(
                f"{_pdf_number(fill[0])} {_pdf_number(fill[1])} "
                f"{_pdf_number(fill[2])} rg"
            )
        if stroke is not None:
            operations.append(
                f"{_pdf_number(stroke[0])} {_pdf_number(stroke[1])} "
                f"{_pdf_number(stroke[2])} RG {_pdf_number(line_width)} w"
            )
        operation = "B" if fill is not None and stroke is not None else "f" if fill else "S"
        operations.append(
            f"{_pdf_number(x)} {_pdf_number(y)} {_pdf_number(width)} "
            f"{_pdf_number(height)} re {operation}"
        )
        self._add(" ".join(operations))

    def image(
        self,
        asset: _ImageAsset,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        scale = min(width / asset.width, height / asset.height)
        draw_width = asset.width * scale
        draw_height = asset.height * scale
        draw_x = x + (width - draw_width) / 2
        draw_y = y + (height - draw_height) / 2
        self.page.image_names.add(asset.name)
        self._add(
            "q "
            f"{_pdf_number(draw_width)} 0 0 {_pdf_number(draw_height)} "
            f"{_pdf_number(draw_x)} {_pdf_number(draw_y)} cm "
            f"/{asset.name} Do Q"
        )


    def link(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        target_page_index: int,
    ) -> None:
        """在这块矩形上加一个跳到指定页的链接。"""
        self.page.links.append((x0, y0, x1, y1, target_page_index))


class _PdfDocument:
    def __init__(self) -> None:
        self.pages: list[_Page] = []
        self.images: list[_ImageAsset] = []
        self._image_cache: dict[str, _ImageAsset | None] = {}

    def add_page(self) -> _Canvas:
        page = _Page()
        self.pages.append(page)
        return _Canvas(page)

    def image_for_path(self, image_path: str | None) -> _ImageAsset | None:
        if not image_path:
            return None
        if image_path in self._image_cache:
            return self._image_cache[image_path]

        asset: _ImageAsset | None = None
        if os.path.isabs(image_path) and os.path.isfile(image_path):
            try:
                with Image.open(image_path) as source:
                    normalized = ImageOps.exif_transpose(source)
                    normalized.thumbnail((600, 600), Image.Resampling.LANCZOS)
                    if normalized.mode in ("RGBA", "LA") or "transparency" in normalized.info:
                        rgba = normalized.convert("RGBA")
                        rgb = Image.new("RGB", rgba.size, "white")
                        rgb.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        rgb = normalized.convert("RGB")

                    encoded = io.BytesIO()
                    rgb.save(
                        encoded,
                        format="JPEG",
                        quality=85,
                        optimize=False,
                        progressive=False,
                        subsampling=2,
                    )
                    asset = _ImageAsset(
                        name=f"Im{len(self.images) + 1}",
                        width=rgb.width,
                        height=rgb.height,
                        jpeg_bytes=encoded.getvalue(),
                    )
            except Exception:
                # A missing, unreadable, truncated, or unsupported local image is
                # represented by the same placeholder as an absent image.
                asset = None

        self._image_cache[image_path] = asset
        if asset is not None:
            self.images.append(asset)
        return asset

    @staticmethod
    def _stream(dictionary: str, data: bytes) -> bytes:
        return (
            f"<< {dictionary} /Length {len(data)} >>\nstream\n".encode("ascii")
            + data
            + b"\nendstream"
        )

    def to_bytes(self) -> bytes:
        image_object_ids = {
            asset.name: 5 + index for index, asset in enumerate(self.images)
        }
        first_content_id = 5 + len(self.images)
        page_object_ids = [
            first_content_id + page_index * 2 + 1
            for page_index in range(len(self.pages))
        ]

        objects: list[bytes] = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            (
                f"<< /Type /Pages /Count {len(self.pages)} /Kids "
                f"[{' '.join(f'{object_id} 0 R' for object_id in page_object_ids)}] >>"
            ).encode("ascii"),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        ]

        for asset in self.images:
            objects.append(
                self._stream(
                    f"/Type /XObject /Subtype /Image /Width {asset.width} "
                    f"/Height {asset.height} /ColorSpace /DeviceRGB "
                    "/BitsPerComponent 8 /Filter /DCTDecode",
                    asset.jpeg_bytes,
                )
            )

        for page_index, page in enumerate(self.pages):
            content = "".join(page.commands).encode("ascii")
            content_object_id = first_content_id + page_index * 2
            xobjects = " ".join(
                f"/{name} {image_object_ids[name]} 0 R"
                for name in sorted(
                    page.image_names,
                    key=lambda value: int(value.removeprefix("Im")),
                )
            )
            resources = f"/Font << /F1 3 0 R /F2 4 0 R >>"
            if xobjects:
                resources += f" /XObject << {xobjects} >>"
            annots = ""
            if page.links:
                entries = []
                for x0, y0, x1, y1, target_index in page.links:
                    if not 0 <= target_index < len(page_object_ids):
                        continue
                    target_id = page_object_ids[target_index]
                    entries.append(
                        "<< /Type /Annot /Subtype /Link "
                        f"/Rect [{_pdf_number(x0)} {_pdf_number(y0)} "
                        f"{_pdf_number(x1)} {_pdf_number(y1)}] "
                        "/Border [0 0 0] "
                        f"/A << /S /GoTo /D [{target_id} 0 R /Fit] >> >>"
                    )
                if entries:
                    annots = f" /Annots [{' '.join(entries)}]"
            objects.append(self._stream("", content))
            objects.append(
                (
                    f"<< /Type /Page /Parent 2 0 R "
                    f"/MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                    f"/Resources << {resources} >>{annots} "
                    f"/Contents {content_object_id} 0 R >>"
                ).encode("ascii")
            )

        output = io.BytesIO()
        output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for object_id, value in enumerate(objects, start=1):
            offsets.append(output.tell())
            output.write(f"{object_id} 0 obj\n".encode("ascii"))
            output.write(value)
            output.write(b"\nendobj\n")

        xref_offset = output.tell()
        output.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        output.write(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.write(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.write(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("ascii")
        )
        return output.getvalue()


def _draw_header(canvas: _Canvas, meta: LineSheetMeta) -> None:
    canvas.text(
        _MARGIN,
        767,
        _fit_text(meta.brand_name, 12, 165),
        size=12,
        bold=True,
        color=(0.08, 0.25, 0.38),
    )
    canvas.text(
        210,
        767,
        _fit_text(meta.legal_entity, 9, PAGE_WIDTH - _MARGIN - 210),
        size=9,
        bold=True,
    )
    canvas.text(
        _MARGIN,
        750,
        _fit_text(meta.contact_email, 8.5, 300),
        size=8.5,
        color=(0.32, 0.35, 0.39),
    )
    canvas.text(
        350,
        750,
        _fit_text(meta.contact_phone, 8.5, PAGE_WIDTH - _MARGIN - 350),
        size=8.5,
        color=(0.32, 0.35, 0.39),
    )
    canvas.line(_MARGIN, 738, PAGE_WIDTH - _MARGIN, 738, color=(0.08, 0.25, 0.38))


def _draw_footer(
    canvas: _Canvas,
    meta: LineSheetMeta,
    page_number: int,
    page_count: int,
) -> None:
    canvas.line(_MARGIN, 44, PAGE_WIDTH - _MARGIN, 44)
    canvas.text(_MARGIN, 26, f"Page {page_number} of {page_count}", size=8)
    terms = (
        f"Minimum order: {meta.currency} ${_money(meta.min_order_value)}"
        f"  |  Payment terms: {meta.payment_terms}"
    )
    canvas.text(
        135,
        26,
        _fit_text(terms, 8, PAGE_WIDTH - _MARGIN - 135),
        size=8,
        color=(0.32, 0.35, 0.39),
    )


def _draw_cover(canvas: _Canvas, meta: LineSheetMeta) -> None:
    canvas.text(
        _MARGIN,
        680,
        "WHOLESALE LINE SHEET",
        size=25,
        bold=True,
        color=(0.08, 0.25, 0.38),
    )
    canvas.text(_MARGIN, 638, meta.edition_label, size=18, bold=True)
    canvas.line(_MARGIN, 620, 300, 620, color=(0.80, 0.63, 0.25), width=2)
    canvas.text(_MARGIN, 582, "Ship-from / business address", size=10, bold=True)
    y = 562
    for address_line in meta.address_lines:
        for line in _wrap_text(address_line, 10, 430) or [""]:
            canvas.text(_MARGIN, y, line, size=10, color=(0.32, 0.35, 0.39))
            y -= 15
    canvas.text(_MARGIN, y - 24, "Ordering information", size=10, bold=True)
    canvas.text(
        _MARGIN,
        y - 44,
        f"Currency: {meta.currency}",
        size=10,
    )
    canvas.text(
        _MARGIN,
        y - 61,
        f"Minimum order value: ${_money(meta.min_order_value)}",
        size=10,
    )
    canvas.text(_MARGIN, y - 78, f"Payment terms: {meta.payment_terms}", size=10)


def _draw_placeholder(
    canvas: _Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    canvas.rectangle(
        x,
        y,
        width,
        height,
        fill=(0.92, 0.93, 0.94),
        stroke=(0.72, 0.74, 0.77),
    )
    canvas.line(x + 12, y + 12, x + width - 12, y + height - 12, color=(0.78, 0.79, 0.81))
    canvas.line(x + 12, y + height - 12, x + width - 12, y + 12, color=(0.78, 0.79, 0.81))
    label = "No image"
    canvas.text(
        x + (width - _text_width(label, 8)) / 2,
        y + height / 2 - 3,
        label,
        size=8,
        bold=True,
        color=(0.42, 0.44, 0.47),
    )


def _draw_product_card(
    canvas: _Canvas,
    document: _PdfDocument,
    item: LineSheetItem,
    *,
    index_on_page: int,
    starts_category: bool,
) -> None:
    column = index_on_page % 2
    row = index_on_page // 2
    x = _MARGIN + column * (_CARD_WIDTH + _COLUMN_GAP)
    top = _CONTENT_TOP - row * (_CARD_HEIGHT + _ROW_GAP)
    bottom = top - _CARD_HEIGHT
    canvas.rectangle(x, bottom, _CARD_WIDTH, _CARD_HEIGHT, fill=(1, 1, 1))

    if starts_category:
        canvas.rectangle(
            x,
            top - 18,
            _CARD_WIDTH,
            18,
            fill=(0.08, 0.25, 0.38),
            stroke=(0.08, 0.25, 0.38),
        )
        canvas.text(
            x + 7,
            top - 13,
            _fit_text(_category_band_text(item), 8, _CARD_WIDTH - 14),
            size=8,
            bold=True,
            color=(1, 1, 1),
        )

    image_x = x + (_CARD_WIDTH - 112) / 2
    image_y = top - 108
    image_width = 112
    image_height = 84
    image = document.image_for_path(item.image_path)
    if image is None:
        _draw_placeholder(canvas, image_x, image_y, image_width, image_height)
    else:
        canvas.image(image, image_x, image_y, image_width, image_height)

    text_x = x + 8
    text_width = _CARD_WIDTH - 16
    canvas.text(
        text_x,
        top - 122,
        _fit_text(f"SKU {item.sku}", 9, text_width),
        size=9,
        bold=True,
        color=(0.08, 0.25, 0.38),
    )
    name_lines = _wrap_text(item.name, 9, text_width)
    if len(name_lines) > 2:
        name_lines = [name_lines[0], _fit_text(name_lines[1] + "...", 9, text_width)]
    for line_number, line in enumerate(name_lines[:2]):
        canvas.text(text_x, top - 137 - line_number * 11, line, size=9, bold=True)

    canvas.text(
        text_x,
        top - 164,
        _fit_text(
            f"Wholesale ${_money(item.wholesale_price)}    MSRP ${_money(item.msrp)}",
            8.3,
            text_width,
        ),
        size=8.3,
    )
    canvas.text(
        text_x,
        top - 179,
        _fit_text(
            f"Case pack {item.case_pack}    Lead time {item.lead_time_days} days",
            8.3,
            text_width,
        ),
        size=8.3,
    )
    if item.variant_note:
        canvas.text(
            text_x,
            top - 194,
            _fit_text(item.variant_note, 8.3, text_width),
            size=8.3,
            color=(0.36, 0.38, 0.42),
        )


def _draw_toc(
    canvas: _Canvas,
    meta: LineSheetMeta,
    entries: list[tuple[str, int, int]],
) -> None:
    """目录页:叶子类目 + 品数 + 页码,**整行可点直接跳过去**。

    买手翻几十页的图册,能直接跳到自己那一类,决定了他会不会看下去。
    类目用叶子名(和产品卡顶栏一致),完整路径对他没意义。
    """
    canvas.text(_MARGIN, 690, "Contents", size=18, bold=True)
    canvas.text(
        _MARGIN,
        672,
        f"{sum(count for _, count, _ in entries)} products "
        f"in {len(entries)} categories  ·  click a line to jump",
        size=9,
        color=(0.36, 0.38, 0.42),
    )
    y = 646
    for label, count, page in entries:
        if y < _CONTENT_BOTTOM + 16:
            break
        canvas.text(
            _MARGIN,
            y,
            _fit_text(label, 10, PAGE_WIDTH - 2 * _MARGIN - 110),
            size=10,
            color=(0.08, 0.25, 0.38),
        )
        canvas.text(
            PAGE_WIDTH - _MARGIN - 96,
            y,
            f"{count} items",
            size=9,
            color=(0.36, 0.38, 0.42),
        )
        canvas.text(
            PAGE_WIDTH - _MARGIN - 24,
            y,
            f"p.{page}",
            size=10,
            bold=True,
            color=(0.08, 0.25, 0.38),
        )
        # 整行热区:目标页序号 = 页码 - 1(页码从 1 开始)。
        canvas.link(_MARGIN - 4, y - 4, PAGE_WIDTH - _MARGIN, y + 12, page - 1)
        y -= 18


def _notes_pages(notes: Iterable[str]) -> list[list[str]]:
    lines: list[str] = []
    for note in notes:
        wrapped = _wrap_text(note, 10, PAGE_WIDTH - 2 * _MARGIN - 22) or [""]
        lines.append(f"- {wrapped[0]}")
        lines.extend(f"  {line}" for line in wrapped[1:])
        lines.append("")

    lines_per_page = 39
    if not lines:
        return [[]]
    return [
        lines[start : start + lines_per_page]
        for start in range(0, len(lines), lines_per_page)
    ]


def _draw_notes(canvas: _Canvas, lines: list[str], continuation: bool) -> None:
    title = "Notes (continued)" if continuation else "Notes"
    canvas.text(
        _MARGIN,
        700,
        title,
        size=20,
        bold=True,
        color=(0.08, 0.25, 0.38),
    )
    if not lines:
        canvas.text(
            _MARGIN,
            668,
            "No additional notes.",
            size=10,
            color=(0.36, 0.38, 0.42),
        )
        return
    y = 668
    for line in lines:
        canvas.text(_MARGIN + (0 if line.startswith("-") else 12), y, line, size=10)
        y -= 15


def render_pdf(request: LineSheetRequest) -> bytes:
    """Render a deterministic US Letter PDF from a line-sheet request.

    The cover and notes each have their own page. Product pages contain exactly
    six slots (two columns by three rows), except for the final partial page.
    """

    items = _sorted_items(request.items)
    product_chunks = [
        items[start : start + PRODUCTS_PER_PAGE]
        for start in range(0, len(items), PRODUCTS_PER_PAGE)
    ]
    notes_pages = _notes_pages(request.meta.notes)
    # 页序:封面(1) + 目录(2) + 产品页 + notes 页
    page_count = 2 + len(product_chunks) + len(notes_pages)

    toc_entries: list[tuple[str, int, int]] = []
    for chunk_index, chunk in enumerate(product_chunks):
        for item in chunk:
            label = _category_band_text(item)
            if toc_entries and toc_entries[-1][0] == label:
                previous = toc_entries[-1]
                toc_entries[-1] = (previous[0], previous[1] + 1, previous[2])
            else:
                toc_entries.append((label, 1, chunk_index + 3))

    document = _PdfDocument()

    page_number = 1
    cover = document.add_page()
    _draw_header(cover, request.meta)
    _draw_cover(cover, request.meta)
    _draw_footer(cover, request.meta, page_number, page_count)

    page_number += 1
    toc_page = document.add_page()
    _draw_header(toc_page, request.meta)
    _draw_toc(toc_page, request.meta, toc_entries)
    _draw_footer(toc_page, request.meta, page_number, page_count)

    previous_category: tuple[str, ...] | None = None
    for chunk in product_chunks:
        page_number += 1
        canvas = document.add_page()
        _draw_header(canvas, request.meta)
        for index_on_page, item in enumerate(chunk):
            category = tuple(item.category_path)
            starts_category = category != previous_category
            _draw_product_card(
                canvas,
                document,
                item,
                index_on_page=index_on_page,
                starts_category=starts_category,
            )
            previous_category = category
        _draw_footer(canvas, request.meta, page_number, page_count)

    for note_page_index, note_lines in enumerate(notes_pages):
        page_number += 1
        canvas = document.add_page()
        _draw_header(canvas, request.meta)
        _draw_notes(canvas, note_lines, continuation=note_page_index > 0)
        _draw_footer(canvas, request.meta, page_number, page_count)

    return document.to_bytes()
