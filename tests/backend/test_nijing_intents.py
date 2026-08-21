"""霓旌:中文数字归一 + 模型 JSON 校验。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.app.modules.agent_series.nijing.intents import (
    chinese_to_number,
    numbers_in_text,
    parse_intent,
    qty_supported_by_text,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("text", "expected"),
    [("一千", 1000), ("两百五十", 250), ("两百五", 250), ("三万二", 32000), ("一万五", 15000),
     ("十", 10), ("十五", 15), ("一百零五", 105), ("两千零八", 2008), ("一百二", 120), ("五百", 500)],
)
def test_chinese_numbers(text, expected) -> None:
    assert chinese_to_number(text) == expected


def test_numbers_in_text_mixed() -> None:
    assert Decimal(1000) in numbers_in_text("今天入库一千条桌腿")
    assert {Decimal(1000), Decimal("1500.0")} <= numbers_in_text("发 1,000 套, 再来 1.5k")
    assert Decimal(30000) in numbers_in_text("入库3万个")
    assert numbers_in_text("桌腿还剩多少") == set()


def test_qty_must_appear_in_text() -> None:
    assert qty_supported_by_text(Decimal(500), "生产500件餐桌")
    assert qty_supported_by_text(Decimal(-5), "纸箱少了 5 个")
    assert not qty_supported_by_text(Decimal(5000), "生产500件餐桌")  # 模型听岔了
    assert not qty_supported_by_text(None, "生产一些")


def test_parse_intent_shapes() -> None:
    good = {"intent": "receipt", "item": "桌腿", "qty": "1000", "unit": "条", "note": None, "reason": None, "doc_ref": None}
    assert parse_intent(good).qty == Decimal(1000)
    assert parse_intent({"content": '{"intent":"shipment","item":"TBL-001","qty":20}'}).intent == "shipment"
    assert parse_intent({"content": "我觉得你想入库"}).intent == "unsupported"
    assert parse_intent({"choices": []}).intent == "unsupported"
    assert parse_intent({"intent": "teleport"}).intent == "unsupported"
    assert parse_intent({"intent": "receipt", "qty": "abc"}).qty is None
    assert parse_intent({"intent": "receipt", "qty": 10**12}).qty is None
    assert parse_intent("plain").intent == "unsupported"
