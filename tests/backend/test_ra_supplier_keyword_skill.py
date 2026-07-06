from __future__ import annotations

from decimal import Decimal

from r_system_v2.ra.supplier_keyword_skill import (
    build_supplier_keyword_profile,
    evaluate_supplier_alignment,
)


def test_supplier_keyword_profile_removes_brand_and_keeps_core_product() -> None:
    product = {
        "asin": "B0GJYJFJQR",
        "brand": "BNBZ",
        "title": "BNBZ Neck Fan Portable Cooling Fan 2 Pack",
        "title_zh": "BNBZ 挂脖风扇 2只装",
        "category": "Outdoor Recreation",
    }

    profile = build_supplier_keyword_profile(None, org_id=None, product=product)
    queries = [
        query
        for platform_queries in profile["search_queries"].values()
        for query in platform_queries
    ]

    assert profile["product_type_zh"] == "挂脖风扇"
    assert profile["pack_count"] == 2
    assert all("BNBZ" not in query for query in queries)
    assert any("挂脖风扇" in query for query in queries)


def test_supplier_alignment_rejects_neck_fan_to_waist_fan_mismatch() -> None:
    product = {
        "brand": "BNBZ",
        "title": "BNBZ Neck Fan Portable Cooling Fan",
        "title_zh": "BNBZ 挂脖风扇",
    }
    profile = build_supplier_keyword_profile(None, org_id=None, product=product)

    alignment = evaluate_supplier_alignment(
        product=product,
        keyword_profile=profile,
        supplier_title="挂腰电风扇随身制冷小空调扇",
        supplier_snippet="腰挂式风扇",
        raw_excerpt=None,
        unit_price_cny=Decimal("49.90"),
    )

    assert alignment["match_status"] == "mismatch"
    assert "产品形态冲突" in alignment["match_reason"]


def test_supplier_alignment_applies_pack_count_multiplier() -> None:
    product = {
        "title": "Garden Solar Light 10 Pack",
        "title_zh": "太阳能庭院灯 10只装",
    }
    profile = build_supplier_keyword_profile(None, org_id=None, product=product)

    alignment = evaluate_supplier_alignment(
        product=product,
        keyword_profile=profile,
        supplier_title="太阳能庭院灯 5只装 一件代发",
        supplier_snippet=None,
        raw_excerpt=None,
        unit_price_cny=Decimal("30"),
    )

    assert alignment["match_status"] == "match"
    assert alignment["adjusted_unit_price_cny"] == 60.0
    assert alignment["quantity"]["cost_multiplier"] == 2.0


def test_supplier_alignment_blocks_size_priced_product_without_supplier_size() -> None:
    product = {
        "title": "Sun Shade Sail 10 x 12 ft",
        "title_zh": "遮阳帆 10 x 12 ft",
    }
    profile = build_supplier_keyword_profile(None, org_id=None, product=product)

    alignment = evaluate_supplier_alignment(
        product=product,
        keyword_profile=profile,
        supplier_title="户外遮阳帆 防晒遮阳篷 一件代发",
        supplier_snippet=None,
        raw_excerpt=None,
        unit_price_cny=Decimal("80"),
    )

    assert alignment["match_status"] == "review"
    assert "尺寸" in alignment["match_reason"]
