"""店型层:图册按店型出、一次只跑一个店型、30 品门槛按店型算。

背景(2026-07-28 用户提的问题):"产品类目多了以后我不知道你这个怎么 hold 得住,
一个产品找五六种买家,十个产品就得有五六十个买家类型,我回复都不知道该怎么回复"。
这一层就是答案——买家类型不跟产品数涨,而同时在跑的线被硬性卡住。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete

from backend.app.db.session import SessionLocal
from backend.app.modules.b2b.prospects.models import B2BProspect
from backend.app.modules.b2b.store_types import service
from backend.app.modules.b2b.store_types.models import (
    OUTREACH_ACTIVE,
    B2BStoreType,
    B2BStoreTypeCategory,
)
from backend.app.modules.b2b.store_types.schemas import (
    StoreTypeCreate,
    StoreTypePatch,
)
from backend.app.modules.b2b.wholesale import service as wholesale_service
from backend.app.modules.b2b.wholesale.models import B2BWholesaleItem
from backend.app.modules.b2b.wholesale.schemas import (
    CATEGORY_PROSPECTING_MIN_READY_ITEMS,
    LineSheetExportRequest,
    WholesaleItemPatch,
)

# 要真库,unit 通道不建库会整体跳过。
pytestmark = pytest.mark.integration

TOYS = ["Toys & Games", "Toys", "Executive Toys"]
OUTDOOR = ["Sporting Goods", "Outdoor Recreation", "Camping & Hiking"]


@pytest.fixture
def db():
    with SessionLocal() as session:
        _wipe(session)
        yield session
        _wipe(session)


def _wipe(session) -> None:
    session.execute(delete(B2BStoreTypeCategory))
    session.execute(delete(B2BStoreType))
    session.execute(delete(B2BWholesaleItem))
    session.execute(delete(B2BProspect))
    session.commit()


def _make_type(db, key: str, label: str) -> B2BStoreType:
    return service.create_store_type(
        db, payload=StoreTypeCreate(key=key, label=label)
    )


def _stock(db, count: int, *, category: list[str], prefix: str) -> None:
    """建 count 个填全批发价的品。"""
    wholesale_service.ingest_products(
        db,
        products=[
            {
                "sku": f"{prefix}-{index:03d}",
                "product_name": f"Item {prefix}{index}",
                "msrp": "25.99",
                "category_path": category,
            }
            for index in range(count)
        ],
    )
    for item in db.query(B2BWholesaleItem).all():
        if item.sku.startswith(prefix) and item.wholesale_price is None:
            wholesale_service.update_item(
                db,
                item_id=item.id,
                patch=WholesaleItemPatch(
                    wholesale_price=Decimal("10.50"),
                    case_pack=24,
                    moq_units=24,
                    lead_time_days=15,
                ),
            )


def test_one_store_type_spans_several_categories(db) -> None:
    """礼品店同时吃玩具和户外——他是一个买家买两样,不是两个买家。"""
    _make_type(db, "gift_shop", "礼品店")
    service.add_category(db, key="gift_shop", category_prefix=["Toys & Games"])
    service.add_category(db, key="gift_shop", category_prefix=["Sporting Goods"])
    _stock(db, 3, category=TOYS, prefix="ET")
    _stock(db, 2, category=OUTDOOR, prefix="PS")

    entry = next(r for r in service.list_store_types(db) if r.key == "gift_shop")

    assert entry.total_items == 5
    assert entry.ready_items == 5
    assert len(entry.categories) == 2


def test_new_products_land_in_the_sheet_without_remapping(db) -> None:
    """挂的是前缀不是全路径:新叶子类目的品自动进图册,不用每次手挂。"""
    _make_type(db, "gift_shop", "礼品店")
    service.add_category(db, key="gift_shop", category_prefix=["Toys & Games"])
    _stock(db, 1, category=TOYS, prefix="ET")
    _stock(db, 1, category=["Toys & Games", "Puzzles"], prefix="PZ")

    entry = next(r for r in service.list_store_types(db) if r.key == "gift_shop")

    assert entry.total_items == 2


def test_cannot_start_outreach_below_the_thirty_item_gate(db) -> None:
    """用户定的门槛,从'按类目'改成'按店型'算。"""
    _make_type(db, "gift_shop", "礼品店")
    service.add_category(db, key="gift_shop", category_prefix=["Toys & Games"])
    _stock(db, 5, category=TOYS, prefix="ET")

    with pytest.raises(service.StoreTypeError) as caught:
        service.patch_store_type(
            db,
            key="gift_shop",
            patch=StoreTypePatch(outreach_status=OUTREACH_ACTIVE),
        )

    assert "5" in str(caught.value)
    assert str(CATEGORY_PROSPECTING_MIN_READY_ITEMS) in str(caught.value)


def test_cannot_start_outreach_without_categories(db) -> None:
    _make_type(db, "hardware_store", "五金店")

    with pytest.raises(service.StoreTypeError) as caught:
        service.patch_store_type(
            db,
            key="hardware_store",
            patch=StoreTypePatch(outreach_status=OUTREACH_ACTIVE),
        )

    assert "类目" in str(caught.value)


def test_only_one_store_type_may_run_at_a_time(db) -> None:
    """结构性保护:用户一个人处理回复,同时开几条线他本人就是瓶颈。"""
    for key, label, category, prefix in (
        ("gift_shop", "礼品店", TOYS, "ET"),
        ("outdoor_store", "户外店", OUTDOOR, "PS"),
    ):
        _make_type(db, key, label)
        service.add_category(db, key=key, category_prefix=category[:1])
        _stock(db, CATEGORY_PROSPECTING_MIN_READY_ITEMS, category=category,
               prefix=prefix)

    service.patch_store_type(
        db, key="gift_shop", patch=StoreTypePatch(outreach_status=OUTREACH_ACTIVE)
    )

    with pytest.raises(service.StoreTypeError) as caught:
        service.patch_store_type(
            db,
            key="outdoor_store",
            patch=StoreTypePatch(outreach_status=OUTREACH_ACTIVE),
        )

    assert "礼品店" in str(caught.value)
    assert service.active_store_type_keys(db) == ["gift_shop"]


def test_pausing_the_running_line_frees_the_slot(db) -> None:
    for key, label, category, prefix in (
        ("gift_shop", "礼品店", TOYS, "ET"),
        ("outdoor_store", "户外店", OUTDOOR, "PS"),
    ):
        _make_type(db, key, label)
        service.add_category(db, key=key, category_prefix=category[:1])
        _stock(db, CATEGORY_PROSPECTING_MIN_READY_ITEMS, category=category,
               prefix=prefix)

    service.patch_store_type(
        db, key="gift_shop", patch=StoreTypePatch(outreach_status=OUTREACH_ACTIVE)
    )
    service.patch_store_type(
        db, key="gift_shop", patch=StoreTypePatch(outreach_status="paused")
    )
    service.patch_store_type(
        db,
        key="outdoor_store",
        patch=StoreTypePatch(outreach_status=OUTREACH_ACTIVE),
    )

    assert service.active_store_type_keys(db) == ["outdoor_store"]


def test_line_sheet_exports_by_store_type_across_categories(db, tmp_path) -> None:
    from pathlib import Path

    _make_type(db, "gift_shop", "礼品店")
    service.add_category(db, key="gift_shop", category_prefix=["Toys & Games"])
    service.add_category(db, key="gift_shop", category_prefix=["Sporting Goods"])
    _stock(db, 2, category=TOYS, prefix="ET")
    _stock(db, 1, category=OUTDOOR, prefix="PS")
    # 五金不在礼品店的名单里,不许混进图册
    _stock(db, 1, category=["Hardware", "Tools"], prefix="HW")

    request = wholesale_service.build_line_sheet_request(
        db,
        payload=LineSheetExportRequest(fmt="pdf", store_type="gift_shop"),
        image_dir=Path(tmp_path),
    )

    skus = sorted(item.sku for item in request.items)
    assert skus == ["ET-000", "ET-001", "PS-000"]


def test_line_sheet_refuses_store_type_without_categories(db, tmp_path) -> None:
    from pathlib import Path

    _make_type(db, "hardware_store", "五金店")
    _stock(db, 1, category=TOYS, prefix="ET")

    with pytest.raises(wholesale_service.WholesaleValidationError):
        wholesale_service.build_line_sheet_request(
            db,
            payload=LineSheetExportRequest(fmt="pdf", store_type="hardware_store"),
            image_dir=Path(tmp_path),
        )


def test_prefix_matcher_is_a_prefix_not_a_substring(db) -> None:
    prefixes = [["Toys & Games"]]
    assert service.matches_any_prefix(TOYS, prefixes) is True
    assert service.matches_any_prefix(["Toys & Games"], prefixes) is True
    assert service.matches_any_prefix(OUTDOOR, prefixes) is False
    # 空前缀列表谁都不匹配,别让"没挂类目"变成"全都要"
    assert service.matches_any_prefix(TOYS, []) is False


def test_deleting_a_running_store_type_is_refused(db) -> None:
    _make_type(db, "gift_shop", "礼品店")
    service.add_category(db, key="gift_shop", category_prefix=["Toys & Games"])
    _stock(db, CATEGORY_PROSPECTING_MIN_READY_ITEMS, category=TOYS, prefix="ET")
    service.patch_store_type(
        db, key="gift_shop", patch=StoreTypePatch(outreach_status=OUTREACH_ACTIVE)
    )

    with pytest.raises(service.StoreTypeError):
        service.delete_store_type(db, key="gift_shop")


# --------------------------------------------------------------------------
# 内置映射目录:上架即落位,用户不用判断"这个类目对应什么店型"
# --------------------------------------------------------------------------


def test_catalog_maps_one_category_into_several_store_types() -> None:
    """捏捏球既进礼品店也进玩具店——同一件货本来就能卖给几种店。"""
    from backend.app.modules.b2b.store_types import catalog

    labels = [s["label"] for s in catalog.store_types_for_category(TOYS)]

    assert "礼品/新奇店" in labels
    assert "玩具店" in labels


def test_catalog_prefix_swallows_unseen_leaf_categories() -> None:
    """谷歌以后新增叶子类目也自动归位,不用回来补表。"""
    from backend.app.modules.b2b.store_types import catalog

    made_up = ["Hardware", "Tools", "Some Brand New Leaf Google Adds In 2027"]
    labels = [s["label"] for s in catalog.store_types_for_category(made_up)]

    assert labels == ["五金店"]


def test_catalog_never_maps_weapons_or_adult_categories() -> None:
    """用户点名排除的两类,加上监管重的品类,永不落进任何店型。"""
    from backend.app.modules.b2b.store_types import catalog

    for blocked in (
        ["Mature", "Weapons"],
        ["Mature", "Erotic", "Erotic Games"],
        ["Business & Industrial", "Law Enforcement", "Handcuffs"],
        ["Arts & Entertainment", "Hobbies & Creative Arts", "Collectibles",
         "Collectible Weapons", "Collectible Guns"],
        ["Food, Beverages & Tobacco", "Tobacco Products"],
        ["Health & Beauty", "Health Care", "Medical Tests"],
    ):
        assert catalog.is_blocked(blocked) is True
        assert catalog.store_types_for_category(blocked) == []


def test_catalog_templates_all_carry_the_city_placeholder() -> None:
    """模板漏了 {city} 就会对同一个词跑遍所有城市,白烧额度。"""
    from backend.app.modules.b2b.store_types import catalog

    for spec in catalog.STORE_TYPE_CATALOG:
        for template in (*spec["queries_en"], *spec["queries_es"]):
            assert "{city}" in template, f"{spec['key']}: {template}"
        assert spec["queries_en"], spec["key"]
        assert spec["queries_es"], spec["key"]


def test_uploading_a_product_materialises_its_store_types(db) -> None:
    created = service.ensure_store_types_for_category(db, category_path=TOYS)

    assert set(created) == {"gift_shop", "toy_store"}
    rows = {row.key: row for row in service.list_store_types(db)}
    # 建出来时把该店型全部类目前缀一次挂齐,以后的品自动进来
    gift_prefixes = {
        " > ".join(c.category_prefix) for c in rows["gift_shop"].categories
    }
    assert "Toys & Games" in gift_prefixes
    assert "Home & Garden > Decor" in gift_prefixes
    assert rows["gift_shop"].newly_added is True


def test_materialising_is_idempotent(db) -> None:
    service.ensure_store_types_for_category(db, category_path=TOYS)
    again = service.ensure_store_types_for_category(db, category_path=TOYS)

    assert again == []
    assert len(service.list_store_types(db)) == 2


def test_blocked_category_materialises_nothing(db) -> None:
    created = service.ensure_store_types_for_category(
        db, category_path=["Mature", "Weapons"]
    )

    assert created == []
    assert service.list_store_types(db) == []


def test_new_store_type_gets_prospect_queries_in_both_languages(db) -> None:
    """新店型要能立刻拿去挖客户,墨西哥的词必须是西班牙语。"""
    from backend.app.modules.b2b.prospects.models import B2BProspectQuery

    service.ensure_store_types_for_category(db, category_path=["Hardware", "Tools"])

    rows = (
        db.query(B2BProspectQuery)
        .filter(B2BProspectQuery.store_type == "hardware_store")
        .all()
    )
    by_country = {row.country: row for row in rows}
    assert set(by_country) == {"US", "CA", "MX"}
    assert by_country["MX"].language == "es"
    assert "ferretería" in by_country["MX"].query_template
    assert by_country["US"].language == "en"


def test_materialising_many_products_in_one_transaction_does_not_duplicate(db) -> None:
    """回灌一整批产品时,前面新建的行还没提交,后面的查重必须看得见。

    session 是 autoflush=False 的,不显式 flush 就会重复插入撞唯一键,
    把整批回灌炸掉——2026-07-28 回灌 6 个真实产品时实际发生过。
    """
    from backend.app.modules.b2b.prospects.models import B2BProspectQuery

    # 同一个 category 连着落位多次 = 模拟一批同类目产品
    for _ in range(6):
        service.ensure_store_types_for_category(
            db, category_path=TOYS, commit=False
        )
    db.commit()

    links = db.query(B2BStoreTypeCategory).all()
    keys = [
        (link.store_type_id, link.category_key) for link in links
    ]
    assert len(keys) == len(set(keys)), "类目挂载出现重复"

    queries = db.query(B2BProspectQuery).all()
    combos = [
        (row.store_type, row.country, row.query_template) for row in queries
    ]
    assert len(combos) == len(set(combos)), "查询模板出现重复"


def test_materialising_mixed_categories_in_one_transaction(db) -> None:
    """一批里混着不同类目(捏捏球 + 花洒),两边都要干净落位。"""
    for path in (TOYS, OUTDOOR, TOYS, OUTDOOR):
        service.ensure_store_types_for_category(db, category_path=path, commit=False)
    db.commit()

    rows = {r.key: r for r in service.list_store_types(db)}
    assert set(rows) == {"gift_shop", "toy_store", "outdoor_store", "vanlife_store"}
    links = db.query(B2BStoreTypeCategory).all()
    keys = [(link.store_type_id, link.category_key) for link in links]
    assert len(keys) == len(set(keys))
