from __future__ import annotations

from r_system_v2.ra.relevance import classify_product_relevance


def test_relevance_blocks_accessory_when_query_wants_main_product() -> None:
    relevance = classify_product_relevance(
        "餐桌",
        {
            "title": "Waterproof Tablecloth for Dining Party",
            "title_zh": "防水餐桌布",
            "category": "Tablecloths",
        },
    )

    assert relevance.status == "accessory_only"
    assert relevance.should_process is False


def test_relevance_allows_accessory_when_query_asks_for_accessory() -> None:
    relevance = classify_product_relevance(
        "桌布",
        {
            "title": "Waterproof Tablecloth for Dining Party",
            "title_zh": "防水餐桌布",
            "category": "Tablecloths",
        },
    )

    assert relevance.status in {"exact_match", "variant_match"}
    assert relevance.should_process is True


def test_relevance_blocks_consumable_for_pet_bed_query() -> None:
    relevance = classify_product_relevance(
        "宠物窝",
        {
            "title": "Dog Treats Chicken Flavor",
            "title_zh": "宠物鸡肉零食",
            "category": "Pet Food",
        },
    )

    assert relevance.status == "consumable_only"
    assert relevance.should_process is False


def test_relevance_keeps_label_machine_for_shop_context() -> None:
    relevance = classify_product_relevance(
        "标签机",
        {
            "title": "Bakery Coffee Shop Label Maker Printer",
            "title_zh": "店铺标签打印机",
            "category": "Office Products",
        },
    )

    assert relevance.status in {"exact_match", "variant_match"}
    assert relevance.should_process is True


def test_relevance_blocks_replacement_part_when_query_wants_main_product() -> None:
    relevance = classify_product_relevance(
        "收纳架",
        {
            "title": "Replacement Shelf Bracket Compatible with Storage Rack",
            "title_zh": "置物架替换支架",
            "category": "Hardware Parts",
        },
    )

    assert relevance.status == "replacement_part_only"
    assert relevance.should_process is False
