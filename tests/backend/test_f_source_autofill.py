"""F→K 搬运时 1688 货源自动灌入 W-S 货源库(只填空,fail-safe)。"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.unit


class _Absent:
    def scalar(self, _stmt):  # noqa: ANN001
        return None

    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = 0

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def flush(self) -> None:
        self.flushed += 1


class _Present(_Absent):
    def scalar(self, _stmt):  # noqa: ANN001
        return "existing-id"


def test_fill_creates_when_absent() -> None:
    from backend.app.modules.w_series.product_sources import fill_source_if_absent

    db = _Absent()
    created = fill_source_if_absent(
        db,
        sku=" igl-001 ",
        source_url="https://detail.1688.com/offer/x.html",
        supplier_name="供应商甲",
        unit_cost=Decimal("12.50"),
        moq=10,
        notes="F 系列搬 K 时自动灌入",
    )
    assert created is True and len(db.added) == 1 and db.flushed == 1
    row = db.added[0]
    assert row.sku == "IGL-001"
    assert row.source_url == "https://detail.1688.com/offer/x.html"
    assert row.supplier_name == "供应商甲"
    assert row.moq == 10


def test_fill_never_overwrites_manual_record() -> None:
    from backend.app.modules.w_series.product_sources import fill_source_if_absent

    db = _Present()
    created = fill_source_if_absent(
        db,
        sku="IGL-001",
        source_url="https://detail.1688.com/offer/y.html",
    )
    assert created is False and db.added == []


@pytest.mark.parametrize(
    ("sku", "url"),
    [
        ("", "https://detail.1688.com/offer/x.html"),
        (None, "https://detail.1688.com/offer/x.html"),
        ("IGL-001", ""),
        ("IGL-001", None),
        ("IGL-001", "javascript:alert(1)"),
    ],
)
def test_fill_skips_invalid_inputs(sku, url) -> None:
    from backend.app.modules.w_series.product_sources import fill_source_if_absent

    db = _Absent()
    assert fill_source_if_absent(db, sku=sku, source_url=url) is False
    assert db.added == []


def test_hook_is_wired_into_f_import_and_fail_safe() -> None:
    import inspect

    from backend.app.modules.f_series.enrichment import service

    source = inspect.getsource(service.import_candidate_to_k)
    assert "fill_source_if_absent" in source
    # 钩子必须在 savepoint 提交之后、包在 try 里 —— 货源联动失败不打断搬 K
    assert source.index("import_savepoint.commit()") < source.index(
        "fill_source_if_absent"
    )
    tail = source[source.index("import_savepoint.commit()"):]
    assert "except Exception" in tail
