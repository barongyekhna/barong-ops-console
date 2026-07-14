"""F 类目富化纯函数单元测试：关键词解析 / 红线标记 / 查询词构造 / 中文树解析。"""

import pytest

from backend.app.modules.f_series.enrichment.profiles import _parse_products
from backend.app.modules.f_series.enrichment.serper_client import extract_keywords
from backend.app.modules.f_series.enrichment.service import (
    detect_red_flags,
    keyword_query_for_node,
)
from backend.app.modules.f_series.enrichment.sourcing import offer_matches_product
from scripts.seed_google_taxonomy_zh import parse as parse_taxonomy_zh

pytestmark = pytest.mark.unit


def test_extract_keywords_three_channels_deduped() -> None:
    raw = {
        "relatedSearches": [
            {"query": "camping shower portable"},
            {"query": "Camping Shower Portable"},  # 大小写重复 → 去重
            {"query": "solar camping shower"},
        ],
        "peopleAlsoAsk": [
            {"question": "How do camping showers work?"},
            {"question": ""},
        ],
        "organic": [
            {"title": "Best Camp Showers of 2026"},
            {"nottitle": "ignored"},
        ],
        "unexpected": "ignored",
    }
    items = extract_keywords(raw)
    texts = [item["keyword_text"] for item in items]
    assert "camping shower portable" in texts
    assert "solar camping shower" in texts
    assert "How do camping showers work?" in texts
    assert "Best Camp Showers of 2026" in texts
    assert len([t for t in texts if t.lower() == "camping shower portable"]) == 1
    types = {item["keyword_type"] for item in items}
    assert types == {"related", "people_also_ask", "organic_title"}


def test_extract_keywords_tolerates_garbage() -> None:
    assert extract_keywords({}) == []
    assert extract_keywords({"relatedSearches": "not-a-list"}) == []


def test_detect_red_flags_category_and_weight() -> None:
    flags = detect_red_flags(
        category_path="Sporting Goods > Hunting > Knives",
        title="folding knife",
        weight_note=None,
    )
    assert flags and flags[0]["type"] == "category_red_line"

    flags = detect_red_flags(
        category_path="Home & Garden > Pool & Spa",
        title="inflatable spa",
        weight_note="毛重 22.5 kg",
    )
    assert flags and flags[0]["type"] == "heavy_weight"

    # 锂电不是红线（用户规则）；普通类目 + 轻重量 → 无标记
    assert (
        detect_red_flags(
            category_path="Sporting Goods > Outdoor Recreation > Camping",
            title="lithium battery camping shower",
            weight_note="0.8kg",
        )
        == []
    )


def test_keyword_query_adds_parent_context_for_generic_names() -> None:
    assert (
        keyword_query_for_node(
            {"name": "Camp Showers", "full_path": "Sporting Goods > Camp Showers"}
        )
        == "Camp Showers"
    )
    assert (
        keyword_query_for_node(
            {
                "name": "Accessories",
                "full_path": "Sporting Goods > Camping Furniture > Accessories",
            }
        )
        == "Camping Furniture Accessories"
    )


def test_taxonomy_zh_parser_takes_leaf_segment() -> None:
    lines = [
        "# Google_Product_Taxonomy_Version: 2021-09-21",
        "632 - 五金/硬件",
        "500096 - 五金/硬件 > 五金泵",
        "",
        "garbage line without separator",
        "abc - 非数字 id 跳过",
    ]
    mapping = parse_taxonomy_zh(lines)
    assert mapping == {"632": "五金/硬件", "500096": "五金泵"}


def test_offer_relevance_gate_blocks_1688_fallback_junk() -> None:
    """1688 分销池无匹配时退化成单字碰瓷+热销兜底——按画像产品名的中文
    2-gram 判定相关性。"""
    assert offer_matches_product("头层牛皮男士公文包手提电脑包", "公文包") is True
    # 单字碰瓷（茶"包"）与完全无关的都拦
    assert offer_matches_product("茶包收纳盒办公桌胶囊咖啡收纳架", "公文包") is False
    assert offer_matches_product("外贸剁骨刀家用砍骨头刀加厚锰钢", "公文包") is False
    assert offer_matches_product("湿巾厨房清洁湿巾75%酒精杀菌", "钛合金叉勺") is False
    # 1688 同类货叫法差异要放行："户外厨具套装" vs 画像"野营炊具套装"（共享"套装"）
    assert offer_matches_product("外贸户外厨具套装露营不锈钢便携", "野营炊具套装") is True
    # 无中文判据时不拦（避免自灭）
    assert offer_matches_product("anything", "abc") is True


def test_profile_parser_tolerates_markdown_fence_and_caps() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": (
                        '```json\n{"products": [{"en": "Camp shower", '
                        '"zh": "露营淋浴", "note_zh": "户外洗澡"}]}\n```'
                    )
                }
            }
        ]
    }
    products = _parse_products(payload)
    assert products == [
        {"en": "Camp shower", "zh": "露营淋浴", "note_zh": "户外洗澡"}
    ]


def test_scoring_moq_dominates_and_smaller_is_higher() -> None:
    """MOQ 是最重加分项（0-50）：越小分越高；未知 MOQ 不得压过已知小单。"""
    from backend.app.modules.f_series.enrichment.scoring import base_components

    tiny = base_components(moq=1, monthly_sales=None, one_piece_hint=True)
    big = base_components(moq=500, monthly_sales=None, one_piece_hint=False)
    unknown = base_components(moq=None, monthly_sales=None, one_piece_hint=False)
    assert tiny["moq_pts"] == 50
    assert tiny["moq_pts"] > unknown["moq_pts"] > big["moq_pts"] >= 0
    assert tiny["opa_pts"] == 10
    assert big["opa_pts"] == 0


def test_scoring_sales_log_scale_caps() -> None:
    from backend.app.modules.f_series.enrichment.scoring import base_components

    zero = base_components(moq=1, monthly_sales=0, one_piece_hint=False)
    mid = base_components(moq=1, monthly_sales=1000, one_piece_hint=False)
    top = base_components(moq=1, monthly_sales=100000, one_piece_hint=False)
    assert zero["sales_pts"] == 0
    assert 0 < mid["sales_pts"] < top["sales_pts"] <= 25


def test_price_points_relative_within_group() -> None:
    from decimal import Decimal

    from backend.app.modules.f_series.enrichment.scoring import _price_points

    low, high = Decimal("10"), Decimal("50")
    assert _price_points(Decimal("10"), low, high) == 15
    assert _price_points(Decimal("50"), low, high) == 0
    assert _price_points(None, low, high) == 8  # 无价给中位
    assert _price_points(Decimal("30"), low, low) == 8  # 组内同价给中位


def test_crossborder_keyword_normalizer_parses_doc_shape() -> None:
    """跨境词搜 keywordQuery 出参（result.result.data[]）防御性解析。"""
    from decimal import Decimal

    from r_system_v2.ra.supplier_api import _normalize_crossborder_keyword_offers

    payload = {
        "result": {
            "result": {
                "totalRecords": 3,
                "data": [
                    {
                        "offerId": 111,
                        "subject": "钛合金叉勺户外餐具",
                        "subjectTrans": "Titanium spork",
                        "imageUrl": "https://cbu01.alicdn.com/x.jpg",
                        "priceInfo": {"price": "12.50", "consignPrice": "15.00"},
                        "monthlySold": 320,
                        "isOnePsale": True,
                        "minOrderQuantity": 2,
                    },
                    {"subject": "无 offerId 无链接应跳过"},
                    {"offerId": 222, "subject": "低价拦截", "priceInfo": {"price": "0.5"}},
                ],
            }
        }
    }
    offers = _normalize_crossborder_keyword_offers(payload, limit=5)
    assert len(offers) == 1
    offer = offers[0]
    assert offer.supplier_url == "https://detail.1688.com/offer/111.html"
    assert offer.unit_price_cny == Decimal("12.50")
    assert offer.moq == 2
    assert offer.monthly_sales == 320
    assert offer.one_piece_hint is True
    assert offer.payload["image_url"] == "https://cbu01.alicdn.com/x.jpg"


def test_acl_denied_detection() -> None:
    from r_system_v2.ra.supplier_api import RASupplierApiError, is_acl_denied

    assert is_acl_denied(
        RASupplierApiError('请求失败：HTTP 400 {"error_code":"gw.APIACLDecline"}')
    )
    assert is_acl_denied(RASupplierApiError("AppKey is not allowed(acl)"))
    assert not is_acl_denied(RASupplierApiError("read timeout"))
