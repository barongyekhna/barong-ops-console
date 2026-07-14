"""F 类目富化纯函数单元测试：关键词解析 / 红线标记 / 查询词构造 / 中文树解析。"""

import pytest

from backend.app.modules.f_series.enrichment.profiles import _parse_products
from backend.app.modules.f_series.enrichment.serper_client import extract_keywords
from backend.app.modules.f_series.enrichment.service import (
    detect_red_flags,
    keyword_query_for_node,
)
from backend.app.modules.f_series.enrichment.sourcing import offer_matches_category
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
    """1688 分销池搜「公文包」会退化返回菜刀/湿巾等热销兜底——标题必须
    真实包含采购词才放行。"""
    profile = {
        "product_type_zh": "公文包",
        "core_keywords_zh": ["公文包", "男士商务包", "supplier product"],
    }
    assert offer_matches_category("头层牛皮男士公文包手提电脑包", profile) is True
    assert offer_matches_category("新款男士商务包大容量单肩", profile) is True
    # 兜底垃圾：单字模糊命中（茶"包"）与完全无关的都拦
    assert offer_matches_category("茶包收纳盒办公桌胶囊咖啡收纳架", profile) is False
    assert offer_matches_category("外贸剁骨刀家用砍骨头刀加厚锰钢", profile) is False
    assert offer_matches_category("湿巾厨房清洁湿巾75%酒精杀菌", profile) is False
    # 英文残留词不作判据；完全没有中文判据时不拦（避免自灭）
    assert offer_matches_category("anything", {"product_type_zh": "", "core_keywords_zh": ["ab"]}) is True


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
