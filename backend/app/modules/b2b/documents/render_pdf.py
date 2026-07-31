"""把 PI 渲染成 PDF。

**复用图册那套自研 PDF 引擎**(`linesheet/render_pdf.py` 的 `_Canvas` /
`_PdfDocument`),不引任何新依赖——那套已经在生产上出过真图册,字体嵌入、
分页、转义都趟过了。

排版原则:**买家最关心的三块要一眼看到**——买什么多少钱、什么时候付、钱汇哪儿。
所以顺序是 行项目 → 合计 → 付款条件 → 收款信息,而不是把条款堆在最后一页。
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Any

from ..linesheet.render_pdf import (
    PAGE_WIDTH,
    _Canvas,
    _fit_text,
    _PdfDocument,
    _wrap_text,
)

_MARGIN = 46
_INK = (0.08, 0.25, 0.38)
_MUTED = (0.36, 0.38, 0.42)


def split_payment(total: Any, deposit_percent: int = 50) -> tuple[Decimal, Decimal]:
    """定金 / 尾款。

    **PI 存在的唯一理由就是告诉买家"现在汇多少"**,而此前单子上只有 TOTAL,
    他得自己除以二——`1814.01 ÷ 2 = 907.005`,汇 907.00 还是 907.01?猜错一分
    就是来回几封邮件。

    **用户拍板(2026-07-30):第三位小数直接舍弃,不四舍五入。** 余下的那一分
    自动落到尾款,所以**永远不会多收客户一分**;两笔加起来永远等于总额。
    """
    try:
        amount = Decimal(str(total))
    except Exception:  # noqa: BLE001
        return Decimal("0"), Decimal("0")
    deposit = (amount * Decimal(deposit_percent) / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN
    )
    return deposit, amount - deposit


def _money(value: Any, currency: str = "USD") -> str:
    try:
        return f"{currency} {Decimal(str(value)):,.2f}"
    except Exception:  # noqa: BLE001 - 单据上宁可显示原值也不要崩
        return f"{currency} {value}"


def _block(
    canvas: _Canvas, x: float, y: float, title: str, lines: list[str], width: float
) -> float:
    canvas.text(x, y, title.upper(), size=7.5, bold=True, color=_MUTED)
    cursor = y - 13
    for line in lines:
        if not line:
            continue
        for wrapped in _wrap_text(str(line), 8.6, width):
            canvas.text(x, cursor, wrapped, size=8.6)
            cursor -= 11
    return cursor


_TITLES = {
    "proforma_invoice": "PROFORMA INVOICE",
    "commercial_invoice": "COMMERCIAL INVOICE",
    "packing_list": "PACKING LIST",
}
_NUMBER_LABELS = {
    "proforma_invoice": "Invoice No.",
    "commercial_invoice": "Invoice No.",
    "packing_list": "Packing List No.",
}


def _freight_line(terms: dict[str, Any], currency: str) -> str:
    """运费那句。**封顶和超出部分都要印出来**——买家到货了才发现要补钱,
    比一开始就说清楚糟糕得多。"""
    delivery = terms.get("delivery_line") or ""
    if not terms.get("free_shipping_applied"):
        return f"Freight: {delivery}."
    cap = terms.get("free_shipping_cap") or ""
    over = terms.get("free_shipping_over_cap") or ""
    base = (
        "Freight: FREE on this first wholesale order - sea freight only, "
        f"{delivery}"
    )
    if cap:
        base += f", up to {currency} {cap} of freight"
    if over:
        base += (
            f". Freight above that cap ({currency} {over}) is shown as a "
            "line item above"
        )
    return base + "."


def render_pdf(document: Any) -> bytes:
    doc_type = getattr(document, "doc_type", "proforma_invoice")
    is_packing = doc_type == "packing_list"
    terms: dict[str, Any] = dict(document.terms_json or {})
    banking: dict[str, Any] = dict(terms.get("banking") or {})
    currency = document.currency or "USD"

    pdf = _PdfDocument()
    canvas = pdf.add_page()
    right = PAGE_WIDTH - _MARGIN

    # ── 抬头 ──
    canvas.text(
        _MARGIN,
        748,
        _TITLES.get(doc_type, "DOCUMENT"),
        size=17,
        bold=True,
        color=_INK,
    )
    canvas.text(
        _MARGIN, 731, str(terms.get("legal_entity") or ""), size=9, bold=True
    )
    cursor = 719
    for line in terms.get("address_lines") or []:
        canvas.text(_MARGIN, cursor, str(line), size=8.2, color=_MUTED)
        cursor -= 10
    canvas.text(_MARGIN, cursor, str(terms.get("contact_email") or ""), size=8.2)
    canvas.text(_MARGIN, cursor - 10, str(terms.get("contact_phone") or ""), size=8.2)

    # 右上角:单号 / 日期 / 有效期。买家汇款附言要写单号,放最显眼处。
    meta_rows: tuple[tuple[str, Any], ...] = (
        (_NUMBER_LABELS.get(doc_type, "No."), document.number),
        ("Date", f"{document.issued_on:%Y-%m-%d}"),
    )
    # **有效期只对报价有意义。** 商业发票和装箱单印"有效期"会让报关的人困惑
    # ——那两张是既成事实的凭证,不是要约。
    if doc_type == "proforma_invoice":
        meta_rows += (("Valid until", f"{document.valid_until:%Y-%m-%d}"),)
    if getattr(document, "source_document_id", None):
        meta_rows += (("Ref. PI", getattr(document, "source_number", "") or ""),)
    meta_rows += (
        ("Country of origin", terms.get("country_of_origin") or "China"),
    )
    row_y = 748
    for label, value in meta_rows:
        canvas.text(right - 200, row_y, f"{label}", size=8, color=_MUTED)
        canvas.text(right - 100, row_y, str(value), size=8.6, bold=True)
        row_y -= 13

    canvas.line(_MARGIN, 676, right, 676, color=_INK)

    # ── 买方 / 送货 ──
    half = (right - _MARGIN) / 2 - 10
    bottom_left = _block(
        canvas,
        _MARGIN,
        662,
        "Bill to",
        [
            document.buyer_company,
            document.buyer_contact or "",
            document.buyer_email or "",
            document.buyer_address or "",
        ],
        half,
    )
    bottom_right = _block(
        canvas,
        _MARGIN + half + 20,
        662,
        "Ship to",
        [document.ship_to or document.buyer_address or "Same as above"],
        half,
    )
    table_top = min(bottom_left, bottom_right) - 14

    # ── 行项目 ──
    col_sku, col_desc, col_qty, col_price, col_total = (
        _MARGIN,
        _MARGIN + 78,
        right - 168,
        right - 116,
        right - 52,
    )
    canvas.rectangle(_MARGIN, table_top - 4, right - _MARGIN, 16, fill=_INK, stroke=_INK)
    head_y = table_top
    for x, label in (
        (col_sku + 4, "SKU"),
        (col_desc, "DESCRIPTION"),
        (col_qty, "QTY"),
        (col_price, "CTN QTY" if is_packing else "UNIT PRICE"),
        (col_total, "CARTONS" if is_packing else "AMOUNT"),
    ):
        canvas.text(x, head_y, label, size=7.6, bold=True, color=(1, 1, 1))

    y = head_y - 20
    for entry in document.items_json or []:
        canvas.text(col_sku + 4, y, _fit_text(str(entry.get("sku") or ""), 8.4, 74), size=8.4)
        name = str(entry.get("name") or "")
        variant = str(entry.get("variant") or "")
        canvas.text(
            col_desc, y, _fit_text(name, 8.4, col_qty - col_desc - 8), size=8.4
        )
        if variant:
            y -= 10
            canvas.text(
                col_desc,
                y,
                _fit_text(variant, 7.6, col_qty - col_desc - 8),
                size=7.6,
                color=_MUTED,
            )
        canvas.text(col_qty, y, str(entry.get("qty") or ""), size=8.4)
        if is_packing:
            per_carton = entry.get("case_pack") or ""
            cartons = entry.get("cartons") or ""
            canvas.text(col_price, y, str(per_carton), size=8.4)
            canvas.text(col_total, y, str(cartons), size=8.4)
        else:
            canvas.text(
                col_price, y, _money(entry.get("unit_price"), currency), size=8.4
            )
            canvas.text(
                col_total, y, _money(entry.get("line_total"), currency), size=8.4
            )
        y -= 16
    canvas.line(_MARGIN, y + 6, right, y + 6, color=(0.8, 0.84, 0.88))

    # ── 合计 ──
    y -= 8
    def _total_row(label: str, value: str, bold: bool = False) -> None:
        nonlocal y
        canvas.text(col_price - 30, y, label, size=8.6, bold=bold, color=_MUTED)
        canvas.text(col_total, y, value, size=8.6, bold=bold)
        y -= 14

    if is_packing:
        # 装箱单不谈钱,谈的是几箱、多重。**没填就印 TBC**,不假装算得出来
        # ——报错的装箱单比没有更麻烦(清关按它核对实物)。
        for label, value in (
            ("Total cartons", document.carton_count),
            ("Gross weight", document.gross_weight_kg),
            ("Net weight", document.net_weight_kg),
        ):
            unit = "" if label == "Total cartons" else " kg"
            _total_row(
                label, f"{value}{unit}" if value is not None else "TBC"
            )
    else:
        _total_row("Subtotal", _money(document.subtotal, currency))
        credit = getattr(document, "sample_credit", None)
        if credit:
            # 抵扣要**印在单子上**,不能只在后台扣掉:买家看到"你说过的样品费
            # 真的退给我了"，比任何一句客套话都管用。
            _total_row("Less: sample credit", f"-{_money(credit, currency)}")
        if document.freight is not None:
            _total_row("Freight", _money(document.freight, currency))
        else:
            canvas.text(
                _MARGIN,
                y + 14,
                "Freight quoted separately.",
                size=7.8,
                color=_MUTED,
            )
        _total_row("TOTAL", _money(document.total, currency), bold=True)
        # 买家真正要的那个数。放在 TOTAL 正下方——他视线停在这里。
        deposit_percent = int(terms.get("deposit_percent") or 50)
        deposit, balance = split_payment(document.total, deposit_percent)
        y -= 4
        _total_row(
            f"Deposit due now ({deposit_percent}%)",
            _money(deposit, currency),
            bold=True,
        )
        _total_row(
            "Balance before dispatch", _money(balance, currency)
        )

    # ── 条款 + 收款信息（买家最需要的两块，放同一屏）──
    y -= 10
    canvas.line(_MARGIN, y, right, y, color=(0.8, 0.84, 0.88))
    y -= 16
    if is_packing:
        _block(
            canvas,
            _MARGIN,
            y,
            "Declaration",
            [
                "The goods described above are packed as listed.",
                f"Country of origin: {terms.get('country_of_origin') or 'China'}.",
                str(terms.get("legal_entity") or ""),
            ],
            right - _MARGIN,
        )
        canvas.line(_MARGIN, 44, right, 44, color=(0.8, 0.84, 0.88))
        canvas.text(
            _MARGIN,
            32,
            _fit_text(
                f"{terms.get('legal_entity') or ''} - {document.number}",
                7.6,
                right - _MARGIN,
            ),
            size=7.6,
            color=_MUTED,
        )
        return pdf.to_bytes()

    terms_bottom = _block(
        canvas,
        _MARGIN,
        y,
        "Payment & delivery",
        [
            str(terms.get("payment_terms") or ""),
            _freight_line(terms, currency),
            str(terms.get("lead_time_note") or ""),
            f"This proforma invoice is valid until {document.valid_until:%Y-%m-%d}.",
        ],
        half,
    )
    bank_lines = [
        f"Beneficiary: {banking.get('beneficiary') or ''}",
        f"Bank: {banking.get('bank_name') or ''}",
        f"SWIFT/BIC: {banking.get('swift') or ''}",
        f"Account: {banking.get('account') or ''}",
    ]
    if banking.get("bank_address"):
        bank_lines.append(f"Bank address: {banking['bank_address']}")
    if banking.get("intermediary"):
        bank_lines.append(f"Intermediary: {banking['intermediary']}")
    bank_lines.append(f"Please quote {document.number} as the payment reference.")
    bank_bottom = _block(
        canvas, _MARGIN + half + 20, y, "Remit to", bank_lines, half
    )

    if document.notes:
        _block(
            canvas,
            _MARGIN,
            min(terms_bottom, bank_bottom) - 12,
            "Notes",
            [document.notes],
            right - _MARGIN,
        )

    canvas.line(_MARGIN, 44, right, 44, color=(0.8, 0.84, 0.88))
    canvas.text(
        _MARGIN,
        32,
        _fit_text(
            f"{terms.get('legal_entity') or ''} - {document.number}", 7.6, right - _MARGIN
        ),
        size=7.6,
        color=_MUTED,
    )
    return pdf.to_bytes()
