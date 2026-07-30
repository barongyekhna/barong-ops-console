"""类目落不进店型 → 这批货静默消失在批发链路上。

2026-07-30 用户要求做成控制台提示:此前完全没有提示——不报错、不警告,
产品一多根本发现不了自己有一批货压根没进批发页和图册。

**纯函数测试,不碰数据库**,所以放在 unit 通道跑得快。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

def test_coverage_separates_blocked_from_unmapped() -> None:
    """**必须分开这两种**(2026-07-30 用户要求做成控制台提示):

    - `blocked`  = 武器/成人/医疗/烟酒,刻意不做 B2B → 报成"缺规则"会让用户
      来问"我的医疗产品怎么不见了"
    - `unmapped` = 只是还没写映射规则,补一条就能用

    两者都会让产品**静默消失**在批发链路上(不出现在批发页、不进图册),
    此前完全没有提示。
    """
    from backend.app.modules.b2b.wholesale.service import _coverage_for

    covered = _coverage_for(
        [
            "Sporting Goods",
            "Outdoor Recreation",
            "Camping & Hiking",
            "Portable Showers & Privacy Enclosures",
        ]
    )
    assert covered["coverage"] == "covered"
    assert covered["store_types"], "有店型却没报出来"

    for blocked_path in (
        ["Mature", "Weapons"],
        ["Health & Beauty", "Health Care", "Medical Tests"],
        ["Food, Beverages & Tobacco", "Tobacco Products"],
    ):
        assert _coverage_for(blocked_path)["coverage"] == "blocked", blocked_path

    unmapped = _coverage_for(
        ["Business & Industrial", "Science & Laboratory", "Laboratory Equipment"]
    )
    assert unmapped["coverage"] == "unmapped"
    assert unmapped["store_types"] == []


def test_coverage_uses_public_labels_not_chinese() -> None:
    """面板上显示的是店型名;这里跟着对外英文名走,和批发页保持一致口径。"""
    from backend.app.modules.b2b.wholesale.service import _coverage_for

    labels = _coverage_for(["Toys & Games", "Toys", "Executive Toys"])["store_types"]
    assert labels
    for label in labels:
        assert not any("一" <= ch <= "鿿" for ch in label), label


def test_uncategorised_items_are_reported_as_unmapped() -> None:
    """没类目的产品同样会静默消失,不能当成 covered 混过去。"""
    from backend.app.modules.b2b.wholesale.service import _coverage_for

    assert _coverage_for([])["coverage"] == "unmapped"
    assert _coverage_for(["(uncategorised)"])["coverage"] == "unmapped"
