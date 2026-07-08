from __future__ import annotations

from decimal import Decimal

from r_system_v2.ra.supplier_keyword_skill import (
    build_supplier_keyword_profile,
    evaluate_supplier_alignment,
    sanitize_supplier_alignment,
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


def test_supplier_alignment_uses_rw_amazon_pack_features_when_title_is_vague() -> None:
    product = {
        "title": "Smartwool Unisex Everyday Low Cut No Show Socks, Multipack - Natural - Small",
        "title_zh": "日常低帮隐形袜 男女同款 多双装 自然色 小号",
        "features": {
            "amazon_pack_count": 3,
            "amazon_pack_label": "3双装",
            "amazon_pack_source": "keepa.numberOfItems",
            "amazon_pack_confidence": "high",
            "amazon_pack_requires_alignment": True,
        },
    }
    profile = build_supplier_keyword_profile(None, org_id=None, product=product)

    alignment = evaluate_supplier_alignment(
        product=product,
        keyword_profile=profile,
        supplier_title="低帮隐形袜 1双装 一件代发",
        supplier_snippet=None,
        raw_excerpt=None,
        unit_price_cny=Decimal("2.70"),
    )

    assert profile["pack_count"] == 3
    assert profile["pack_label"] == "3双装"
    assert alignment["match_status"] == "match"
    assert alignment["quantity"]["amazon_pack_count"] == 3
    assert alignment["quantity"]["supplier_pack_count"] == 1
    assert alignment["quantity"]["cost_multiplier"] == 3.0
    assert alignment["adjusted_unit_price_cny"] == 8.1


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


def test_deepseek_alignment_can_reject_generic_product_without_dictionary_rule() -> None:
    product = {
        "brand": "GardenCo",
        "title": "GardenCo Ceramic Self Watering Planter",
        "title_zh": "陶瓷自吸水花盆",
    }
    profile = build_supplier_keyword_profile(None, org_id=None, product=product)
    heuristic = evaluate_supplier_alignment(
        product=product,
        keyword_profile=profile,
        supplier_title="塑料浇水壶 园艺喷壶 一件代发",
        supplier_snippet="不是花盆，是手持浇水工具",
        raw_excerpt=None,
        unit_price_cny=Decimal("18"),
    )

    alignment = sanitize_supplier_alignment(
        {
            "match_status": "mismatch",
            "match_score": 12,
            "match_reason": "亚马逊产品主体是花盆，供应商主体是浇水壶，不是同类产品。",
            "amazon_subject": "陶瓷自吸水花盆",
            "supplier_subject": "浇水壶",
            "same_product_type": False,
            "quantity": {"status": "not_required"},
            "dimensions": {"status": "not_required"},
        },
        heuristic_alignment=heuristic,
        product=product,
        keyword_profile=profile,
        supplier_title="塑料浇水壶 园艺喷壶 一件代发",
        supplier_snippet="不是花盆，是手持浇水工具",
        raw_excerpt=None,
        unit_price_cny=Decimal("18"),
    )

    assert alignment["source"] == "deepseek"
    assert alignment["match_status"] == "mismatch"
    assert alignment["same_product_type"] is False
    assert alignment["supplier_subject"] == "浇水壶"


def test_code_hard_guard_overrides_deepseek_match_for_brand_risk() -> None:
    product = {
        "brand": "BNBZ",
        "title": "BNBZ Neck Fan Portable Cooling Fan",
        "title_zh": "BNBZ 挂脖风扇",
    }
    profile = build_supplier_keyword_profile(None, org_id=None, product=product)
    heuristic = evaluate_supplier_alignment(
        product=product,
        keyword_profile=profile,
        supplier_title="BNBZ 挂脖风扇 原厂同款",
        supplier_snippet=None,
        raw_excerpt=None,
        unit_price_cny=Decimal("50"),
    )

    alignment = sanitize_supplier_alignment(
        {
            "match_status": "match",
            "match_score": 95,
            "match_reason": "产品完全一致。",
            "quantity": {"status": "not_required"},
            "dimensions": {"status": "not_required"},
        },
        heuristic_alignment=heuristic,
        product=product,
        keyword_profile=profile,
        supplier_title="BNBZ 挂脖风扇 原厂同款",
        supplier_snippet=None,
        raw_excerpt=None,
        unit_price_cny=Decimal("50"),
    )

    assert alignment["match_status"] == "mismatch"
    assert "品牌" in alignment["match_reason"]
