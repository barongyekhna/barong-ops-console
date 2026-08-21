"""把模型的 JSON 变成可信的意图:形状校验 + 数量必须在原文里出现。

模型只负责「听懂」。它说的数量要能在用户原话里(中文数字归一后)找到,
找不到就问回去——500 听成 5000 这种错,不能靠模型自觉。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

IntentName = Literal[
    "receipt",
    "production",
    "shipment",
    "adjustment",
    "query_stock",
    "query_documents",
    "undo",
    "create_item",
    "edit_bom",
    "archive",
    "chitchat",
    "multi",
    "unsupported",
]

WRITE_INTENTS = frozenset({"receipt", "production", "shipment", "adjustment"})
RED_INTENTS = frozenset({"create_item", "edit_bom", "archive"})


class Intent(BaseModel):
    intent: IntentName
    item: str | None = None
    qty: Decimal | None = None
    unit: str | None = None
    note: str | None = None
    reason: str | None = None
    doc_ref: str | None = None

    @field_validator("item", "unit", "note", "reason", "doc_ref", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text[:200] or None

    @field_validator("qty", mode="before")
    @classmethod
    def _qty(cls, value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return None
        try:
            dec = Decimal(str(value).replace(",", ""))
        except (InvalidOperation, ValueError):
            return None
        if not dec.is_finite() or abs(dec) > Decimal("1000000000"):
            return None
        return dec


UNSUPPORTED = Intent(intent="unsupported")


def parse_intent(result: Any) -> Intent:
    """路由器可能返回解析好的 dict / {"content": raw} / 原始响应,只认第一种形状。"""
    payload: Any = result
    if isinstance(result, dict) and "content" in result and "intent" not in result:
        import json

        raw = result["content"]
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return UNSUPPORTED
    if not isinstance(payload, dict) or "intent" not in payload:
        return UNSUPPORTED
    try:
        return Intent.model_validate(payload)
    except ValidationError:
        return UNSUPPORTED


# ---------------------------------------------------------------- 中文数字归一

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_BIG = {"万": 10_000, "亿": 100_000_000}
_CN_CHARS = "".join(_CN_DIGITS) + "".join(_CN_UNITS) + "".join(_CN_BIG)
_CN_RE = re.compile(f"[{_CN_CHARS}]+")
_ARABIC_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?\s*[kKwW万]?")


def chinese_to_number(text: str) -> int | None:
    """一千→1000;两百五十→250;两百五→250(口语);三万二→32000;一万五→15000;一百零五→105。"""
    if not text:
        return None
    total = 0
    section = 0
    number = 0
    last_unit = 0  # 最近一个量词的值,用来解「两百五」这种省略
    for ch in text:
        if ch in ("零", "〇"):
            number = 0
            last_unit = 0
        elif ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if number == 0 and unit == 10 and section == 0:
                number = 1  # 十 / 十五
            section += number * unit
            number = 0
            last_unit = unit
        elif ch in _CN_BIG:
            section += number
            total += (section or 1) * _CN_BIG[ch]
            section = 0
            number = 0
            last_unit = _CN_BIG[ch]
        else:
            return None
    if number:
        if last_unit >= 100:
            section += number * (last_unit // 10)
        else:
            section += number
    total += section
    if total == 0 and not any(z in text for z in ("零", "〇")):
        return None
    return total


def numbers_in_text(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for match in _ARABIC_RE.finditer(text or ""):
        raw = match.group(0).replace(",", "").replace(" ", "")
        mult = 1
        if raw and raw[-1] in "kK":
            mult, raw = 1000, raw[:-1]
        elif raw and raw[-1] in "wW万":
            mult, raw = 10_000, raw[:-1]
        try:
            found.add(Decimal(raw) * mult)
        except InvalidOperation:
            continue
    for match in _CN_RE.finditer(text or ""):
        value = chinese_to_number(match.group(0))
        if value is not None:
            found.add(Decimal(value))
    # 「一万五」这类:阿拉伯 + 万 的混合已在上面;中文整段在 chinese_to_number
    return found


def qty_supported_by_text(qty: Decimal | None, text: str) -> bool:
    """模型说的数量必须能在原话里找到。"""
    if qty is None:
        return False
    candidates = numbers_in_text(text)
    target = abs(qty)
    return any(c == target for c in candidates)
