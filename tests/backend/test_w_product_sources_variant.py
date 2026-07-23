"""变体 SKU 订单的货源匹配(2026-07-23 实锤修复)。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.modules.w_series.product_sources import (
    _normalized_skus_for_items,
    enrich_items,
    parent_sku_of,
)

pytestmark = pytest.mark.unit


def test_parent_sku_of_recognizes_variant_suffix() -> None:
    assert parent_sku_of("ET-001-BFD8A626") == "ET-001"
    assert parent_sku_of("ET-001") is None
    assert parent_sku_of("B0BYTEST01") is None  # ASIN 不是变体格式


def test_variant_order_items_resolve_parent_source() -> None:
    items = [{"sku": "ET-001-BFD8A626", "name": "Squeeze Ball"}]
    skus = _normalized_skus_for_items([items])
    assert "ET-001" in skus and "ET-001-BFD8A626" in skus

    source = SimpleNamespace(
        sku="ET-001",
        source_url="https://detail.1688.com/offer/x.html",
        supplier_name="厂",
        unit_cost=None,
        currency=None,
        moq=None,
    )
    enriched = enrich_items(items, {"ET-001": source})
    assert enriched[0]["source_url"] == "https://detail.1688.com/offer/x.html"
    assert enriched[0]["source_state"] != "missing"
