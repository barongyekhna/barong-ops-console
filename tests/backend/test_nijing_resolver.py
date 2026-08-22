"""霓旌:物料匹配纯代码,对不上就问。"""

from __future__ import annotations

from types import SimpleNamespace as N

import pytest

from backend.app.modules.agent_series.nijing.resolver import resolve_item, unit_matches

pytestmark = pytest.mark.unit

ITEMS = [
    N(id=1, kind="part", code="TBL-LEG", name="桌腿", unit="条", is_archived=False),
    N(id=2, kind="part", code="TBL-TOP", name="桌面", unit="个", is_archived=False),
    N(id=3, kind="product", code="TBL-001", name="折叠桌", unit="套", is_archived=False),
    N(id=4, kind="product", code="TBL-002", name="餐桌B", unit="套", is_archived=False),
    N(id=5, kind="part", code="OLD-1", name="旧桌腿", unit="条", is_archived=True),
]


def test_exact_code_and_name() -> None:
    assert resolve_item("桌腿", ITEMS).matches[0].code == "TBL-LEG"
    assert resolve_item("tbl-leg", ITEMS).matches[0].code == "TBL-LEG"
    assert resolve_item("TBL 001", ITEMS).matches[0].code == "TBL-001"


def test_many_and_none() -> None:
    many = resolve_item("桌", ITEMS)
    assert many.status == "many" and len(many.matches) == 4
    none = resolve_item("螺丝", ITEMS)
    assert none.status == "none" and len(none.suggestions) == 3


def test_kind_filter_and_archived() -> None:
    assert resolve_item("桌", ITEMS, kinds=("product",)).status == "many"
    assert resolve_item("折叠桌", ITEMS, kinds=("part",)).status == "none"
    assert resolve_item("旧桌腿", ITEMS).status == "none"  # 归档的不参与


def test_unit_matches() -> None:
    assert unit_matches(None, "条")
    assert unit_matches("条", "条")
    assert not unit_matches("个", "条")


def test_bare_name_with_spec_siblings_must_ask() -> None:
    legs = [
        N(id=1, kind="part", code="LEG-STD", name="桌腿", unit="条", is_archived=False),
        N(id=2, kind="part", code="LEG-L", name="桌腿加长", unit="条", is_archived=False),
        N(id=3, kind="part", code="LEG-XL", name="桌腿超长", unit="条", is_archived=False),
    ]
    r = resolve_item("桌腿", legs)
    assert r.status == "many" and {m.code for m in r.matches} == {"LEG-STD", "LEG-L", "LEG-XL"}
    # 点名编码不歧义
    assert resolve_item("LEG-STD", legs).matches[0].code == "LEG-STD"
    # 全带规格也问
    specs = [N(id=i, kind="part", code=f"LEG-{i}", name=f"桌腿 {i}0cm", unit="条", is_archived=False) for i in (6, 7, 8)]
    assert resolve_item("桌腿", specs).status == "many"
    assert resolve_item("桌腿 70cm", specs).matches[0].code == "LEG-7"
