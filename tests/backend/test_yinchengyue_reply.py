"""殷承岳的回复语法:后端 render 出来的卡,前端同款正则必须能原样解析回去。"""

from __future__ import annotations

import re

import pytest

from backend.app.modules.agent_series.yinchengyue.classifier import Candidate, CategoryVerdict
from backend.app.modules.agent_series.yinchengyue.reply import (
    CARD_MARKER_PREFIX,
    REPLY_CHITCHAT,
    REPLY_NEED_DETAIL,
    REPLY_OFFLINE,
    card_id_for,
    is_chitchat,
    render_verdict,
)

pytestmark = pytest.mark.unit

# 与 frontend/src/modules/c19/c19CategoryCard.ts 一字不差的三条正则。
CARD_HEAD = re.compile(r"^【类目 #([0-9a-f]{4})】(.+)$")
CARD_MARKER = re.compile(r"^⟦category:([0-9a-f]{4})⟧$")
FIELD = re.compile(r"^(路径|中文|原因|备选|置信)[：:]\s*(.*)$")

LEAF = Candidate(id="1014", name="Camping Cookware", full_path="Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Cookware", name_zh="露营炊具", level=4, is_leaf=True)
ALT = Candidate(id="1015", name="Portable Cooking Stoves", full_path="Sporting Goods > Outdoor Recreation > Camping & Hiking > Portable Cooking Stoves", name_zh="便携式炉具", level=4, is_leaf=True)


def _parse(content: str) -> dict:
    lines = content.split("\n")
    marker = CARD_MARKER.match(lines[-1].strip())
    head = CARD_HEAD.match(lines[0].strip())
    assert marker and head and marker.group(1) == head.group(1)
    fields: dict[str, list[str]] = {}
    for line in lines[1:-1]:
        m = FIELD.match(line.strip())
        assert m, f"非法行: {line!r}"
        fields.setdefault(m.group(1), []).append(m.group(2))
    return {"id": head.group(1), "leaf": head.group(2), **fields}


def test_render_ok_card_roundtrips_through_frontend_grammar():
    verdict = CategoryVerdict(status="ok", chosen=LEAF, path=["Sporting Goods", "Outdoor Recreation", "Camping & Hiking", "Camping Cookware"], confidence="high", reason_zh="户外炉具加锅具套装,\n属于露营烹饪器具。", alternates=[(ALT, "以炉头为主时")], shortlist_size=12)
    text = render_verdict(verdict, record_id="rec-1")
    parsed = _parse(text)
    assert parsed["leaf"] == "Camping Cookware"
    assert parsed["路径"] == ["Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Cookware"]
    assert parsed["中文"] == ["露营炊具"]
    assert parsed["原因"] == ["户外炉具加锅具套装, 属于露营烹饪器具。"]  # 多行原因被压成一行
    assert parsed["备选"] == ["Portable Cooking Stoves — 以炉头为主时"]
    assert parsed["置信"] == ["高"]
    assert parsed["id"] == card_id_for("1014", "rec-1")
    assert text.endswith(f"{CARD_MARKER_PREFIX}{parsed['id']}⟧")
    assert len(text) < 3900


def test_card_id_is_stable_per_record_and_differs_across_records():
    assert card_id_for("1014", "r1") == card_id_for("1014", "r1")
    assert card_id_for("1014", "r1") != card_id_for("1014", "r2")
    assert re.fullmatch(r"[0-9a-f]{4}", card_id_for("1014", "r1"))


def test_render_truncates_long_reason_and_falls_back_to_full_path():
    verdict = CategoryVerdict(status="ok", chosen=LEAF, path=[], confidence="medium", reason_zh="很长" * 400)
    text = render_verdict(verdict, record_id="r")
    parsed = _parse(text)
    assert len(parsed["原因"][0]) <= 300 and parsed["原因"][0].endswith("…")
    assert parsed["路径"][0] == LEAF.full_path
    assert parsed["置信"] == ["中"]
    assert "备选" not in parsed


def test_render_none_and_offline_are_plain_text_without_marker():
    assert render_verdict(CategoryVerdict(status="none"), record_id="r") == REPLY_NEED_DETAIL
    assert render_verdict(CategoryVerdict(status="offline"), record_id="r") == REPLY_OFFLINE
    assert CARD_MARKER_PREFIX not in REPLY_NEED_DETAIL and CARD_MARKER_PREFIX not in REPLY_OFFLINE
    assert "谷歌" in REPLY_CHITCHAT and "一次一个" in REPLY_CHITCHAT


@pytest.mark.parametrize("text_in", ["你好", "在吗?", "Hi!", "谢谢~", "你是谁", "嗯", "", "  "])
def test_greetings_are_chitchat(text_in):
    assert is_chitchat(text_in)


@pytest.mark.parametrize("text_in", ["保温杯", "露营炊具套装是什么类目", "solar lantern", "这个是哪个类目:304不锈钢真空保温杯"])
def test_product_questions_are_not_chitchat(text_in):
    assert not is_chitchat(text_in)
