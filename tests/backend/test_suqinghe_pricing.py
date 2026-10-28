"""苏青禾价格卡(10-26):到手成本、保底价、竞品价分布、模型定价的兜底。unit,不连库、不出网。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.modules.agent_series.suqinghe import pricing

pytestmark = pytest.mark.unit

A = pricing.Assumptions(
    usd_cny=7.2, ship_cny_per_kg=90, ship_cny_per_piece=20, fee_rate=0.0349, fee_fixed_usd=0.49, buyer_shipping_usd=2.99, min_margin=0.30
)
LIVE = json.loads((Path(__file__).parent / "fixtures" / "sqh1688" / "live_drafts_20261026.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("raw", "expected"), [(14.2, 14.99), (14.99, 14.99), (15.0, 15.99), (0.5, 0.99), (14.995, 15.99)])
def test_charm_is_the_smallest_99_not_below(raw: float, expected: float) -> None:
    assert pricing.charm(raw) == expected


def test_floor_price_really_reaches_the_minimum_margin() -> None:
    for cost_cny, kg in ((39.0, 0.17), (9.0, 0.08), (76.0, 2.0), (28.5, 0.26)):
        goods, ship = pricing.costs(cost_cny, kg, A)
        floor = pricing.floor_price(goods, ship, A)
        _, margin = pricing.profit_at(floor, goods, ship, A)
        assert margin >= A.min_margin - 1e-9, (cost_cny, floor, margin)
        _, below = pricing.profit_at(floor - 1, goods, ship, A)
        assert below < A.min_margin  # 再便宜一美元就不够了:保底价不是乱抬的


def test_battery_lines_from_the_real_dossier() -> None:
    lines = pricing.cost_lines(LIVE["643348607768"]["draft"]["variants"], A)
    by_name = {line.name_zh: line for line in lines}
    battery = by_name["2000mah"]
    assert battery.kg == pytest.approx(0.17)  # 实重 0.17 > 体积重 13×9×8/6000=0.156
    assert battery.floor == 11.99
    assert by_name["12V直充充电器"].floor < battery.floor


def test_missing_and_identical_weights_are_called_out() -> None:
    lamp = pricing.cost_lines(LIVE["773137484620"]["draft"]["variants"], A)
    green = [line for line in lamp if "绿色" in line.name_zh][0]
    assert green.weight_g == 260.0 and "没写这个规格的重量" in green.weight_note
    drill = pricing.cost_lines(LIVE["888786557113"]["draft"]["variants"], A)
    assert all("都填了 2000g" in line.weight_note for line in drill)
    assert all(line.kg == 2.0 for line in drill)  # 照卖家填的算,卡上提醒老板核实


def test_competitor_stats_drop_accessories_and_bulk_listings() -> None:
    items = [{"title": f"Drill {i}", "source": "Store", "price": f"${p}"} for i, p in enumerate([39.99, 45.0, 49.99, 52.5, 59.99, 64.0, 3.99, 899.0])]
    items.append({"title": "No price", "price": "See website"})
    stats = pricing.competitor_stats(items, query="cordless drill")
    assert stats["n"] == 6 and stats["min"] == 39.99 and stats["max"] == 64.0
    assert stats["p25"] <= stats["median"] <= stats["p75"]
    assert pricing.competitor_stats([], query="x") == {"query": "x", "n": 0}
    assert pricing.parse_price("$1,299.00") == 1299.0 and pricing.parse_price("From $19.99") == 19.99


def test_model_prices_are_floored_and_axis_unified() -> None:
    lines = pricing.cost_lines(LIVE["643348607768"]["draft"]["variants"], A)
    keys = {line.name_zh: line.key for line in lines}
    plan = {
        "variants": [
            {"key": keys["2000mah"], "include": True, "price": 5.0, "label_en": "2000mAh", "axis": "size"},  # 低于保底
            {"key": keys["12V直充充电器"], "include": False, "price": 9.99, "label_en": "Charger", "axis": "function", "note": "这是充电器"},
            {"key": keys["2500mah"], "include": True, "price": 24.99, "label_en": "2500mAh", "axis": "size"},
        ],
        "questions": ["充电器当配件卖吗?"],
        "summary": "按容量分档",
    }
    priced, questions, summary = pricing.apply_plan(lines, plan, A)
    got = {line.name_zh: line for line in priced}
    assert got["2000mah"].price == got["2000mah"].floor and "抬到保底价" in got["2000mah"].note
    assert got["12V直充充电器"].include is False
    assert got["2500mah"].price == 24.99 and got["2500mah"].margin > A.min_margin
    assert got["1500mah"].price == got["1500mah"].floor and "模型没给价" in got["1500mah"].note
    assert {line.axis for line in priced} == {"size"}
    assert questions == ["充电器当配件卖吗?"] and summary == "按容量分档"


def test_garbage_from_the_model_still_gives_a_safe_price_for_everything() -> None:
    lines = pricing.cost_lines(LIVE["888786557113"]["draft"]["variants"], A)
    priced, questions, _ = pricing.apply_plan(lines, {"content": "不知道"}, A)
    assert all(line.include and line.price == line.floor for line in priced)
    assert questions == []


def test_price_card_text_reads_like_a_price_list() -> None:
    lines = pricing.cost_lines(LIVE["643348607768"]["draft"]["variants"], A)
    keys = {line.name_zh: line.key for line in lines}
    priced, _, _ = pricing.apply_plan(
        lines, {"variants": [{"key": keys["12V直充充电器"], "include": False, "note": "这是充电器,不是电池"}]}, A
    )
    text = pricing.lines_text(priced)
    assert "✗" in text and "这是充电器,不是电池" in text
    assert "• 2000mAh Battery(2000mah):进价 ¥39,到手成本 $" in text and "建议 $11.99" in text
    assert "中位 $14.99" in pricing.competitors_text({"query": "q", "n": 3, "median": 14.99, "p25": 12, "p75": 16, "min": 9, "max": 20})
    assert "没拿到" in pricing.competitors_text({"query": "q", "n": 0, "error": "预算用完"})


STAKE_TITLES = [  # 10-28 真实的谷歌购物结果:单根、整包、商用大号混在一起
    ("10\" Steel Tent Stakes", 6.95),
    ("Everbilt 9 in. Tent Stake", 4.81),
    ("Coghlan's Heavy Duty Tent Stake", 5.49),
    ("Mapskey Tent Stakes Heavy Duty Galvanized 12 Pack", 14.98),
    ("AAGUT 16 Straight Rebar Stakes Heavy Duty Ground Anchors", 27.99),
    ("16 Pcs 8 inch Heavy Duty Metal Threaded Tent Stakes", 25.99),
    ("R-30-8P 8-Pack 11.81-Inch Steel Tent Stakes", 35.95),
    ("12 Pack Galvanized Steel Tent Stakes", 6.51),
    ("Pack of 10 Heavy Duty Tent Pegs", 19.99),
    ("1\" x 20\" Commercial Grade Steel Tent Stake", 50.09),
]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("10\" Steel Tent Stakes", 1),
        ("AAGUT 16 Straight Rebar Stakes", 1),  # 没写 pack/pcs 的数字不猜
        ("16 Pcs 8 inch Heavy Duty Tent Stakes", 16),
        ("R-30-8P 8-Pack 11.81-Inch Steel Tent Stakes", 8),
        ("Pack of 10 Heavy Duty Tent Pegs", 10),
        ("Set of 6 Aluminum Pegs", 6),
        ("Tent Stakes (12-Count)", 12),
        ("1 Pack Tent Stake", 1),
        ("1000 pcs wholesale", 1),  # 上千件是整箱,不当零售包装
        ("", 1),
        (None, 1),
    ],
)
def test_pack_count_only_trusts_explicit_pack_words(title, expected) -> None:
    assert pricing.pack_count(title) == expected


def test_competitor_stats_fold_multipacks_into_unit_prices() -> None:
    """单根 $5、12 支装 $15 混在一起:listing 中位还是老样子,但另给按件折算的分布,主流件数和多件装占比写明。"""
    stats = pricing.competitor_stats([{"title": t, "source": "Store", "price": f"${p}"} for t, p in STAKE_TITLES], query="tent stakes heavy duty")
    assert stats["n"] == 10
    unit = stats["unit"]
    assert unit["n"] == 10 and unit["median"] < stats["median"] / 2  # 按件折算后中位掉到一两美元
    assert unit["pack_mode"] == 12 and unit["multi_share"] == 0.5  # 5/10 是多件装,件数各异 → 取多件装的中位件数
    by_title = {row["title"]: row for row in stats["samples"]}
    assert by_title["16 Pcs 8 inch Heavy Duty Metal Threaded Tent Stakes"]["pack"] == 16 and by_title["16 Pcs 8 inch Heavy Duty Metal Threaded Tent Stakes"]["unit_price"] == 1.62
    assert by_title["Everbilt 9 in. Tent Stake"]["pack"] == 1 and by_title["Everbilt 9 in. Tent Stake"]["unit_price"] == 4.81
    assert pricing.unit_text(unit) == f"按件折算中位 ${unit['median']}/件,主流 12 件装(50% 是多件装)"
    # 全是单件的:unit 还在(pack_mode 1、占比 0),卡上那半句就空
    singles = pricing.competitor_stats([{"title": f"Drill {i}", "price": p} for i, p in enumerate([39.99, 45.0, 49.99, 52.5])], query="drill")
    assert singles["unit"]["pack_mode"] == 1 and singles["unit"]["multi_share"] == 0 and singles["unit"]["p25"] == singles["p25"]
    assert pricing.unit_text(singles["unit"]) == "" and pricing.unit_text(None) == ""


def test_price_prompt_shows_packs_per_unit_and_asks_like_for_like() -> None:
    lines = pricing.cost_lines(LIVE["643348607768"]["draft"]["variants"], A)
    stats = pricing.competitor_stats([{"title": t, "source": "Store", "price": f"${p}"} for t, p in STAKE_TITLES], query="tent stakes heavy duty")
    extra = pricing.price_prompt_extra(lines, stats, A, boss_reason=None)
    assert "(16 件装,$1.62/件)" in extra and "按件折算中位 $" in extra and "主流 12 件装" in extra
    assert "先折成每件的价再比" in pricing.PRICE_ASK and "单件进价不能直接对整包售价" in pricing.PRICE_ASK
