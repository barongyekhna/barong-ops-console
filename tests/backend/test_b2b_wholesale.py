"""B2B wholesale catalogue: ingest, gating, and export guards."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete

from backend.app.db.session import SessionLocal
from backend.app.modules.b2b.wholesale import ingest_from_k, service
from backend.app.modules.b2b.wholesale.models import (
    STATUS_PENDING,
    STATUS_READY,
    B2BWholesaleItem,
)
from backend.app.modules.b2b.wholesale.schemas import (
    CATEGORY_PROSPECTING_MIN_READY_ITEMS,
    LineSheetExportRequest,
    PriceTier,
    WholesaleItemPatch,
)

# 这些测试要真数据库(建表由 integration 通道的 alembic upgrade 完成)。
# unit 通道不建库,标 unit 会被整体跳过——踩过一次。
pytestmark = pytest.mark.integration


@pytest.fixture
def db():
    with SessionLocal() as session:
        session.execute(delete(B2BWholesaleItem))
        session.commit()
        yield session
        session.execute(delete(B2BWholesaleItem))
        session.commit()


def _product(sku: str, *, price: str = "25.99", category=None) -> dict:
    return {
        "sku": sku,
        "product_name": f"Product {sku}",
        "msrp": price,
        "category_path": category or ["Toys & Games", "Toys", "Executive Toys"],
    }


def _complete_patch() -> WholesaleItemPatch:
    return WholesaleItemPatch(
        wholesale_price=Decimal("10.50"),
        case_pack=24,
        moq_units=24,
        lead_time_days=15,
    )


def test_ingest_creates_pending_item(db) -> None:
    result = service.ingest_products(db, products=[_product("ET-001")])

    assert result.created == 1
    item = db.query(B2BWholesaleItem).one()
    assert item.status == STATUS_PENDING
    assert item.msrp == Decimal("25.99")
    assert item.category_path == ["Toys & Games", "Toys", "Executive Toys"]
    # 批发侧必须是空的,等人工填
    assert item.wholesale_price is None


def test_filling_wholesale_fields_flips_status_to_ready(db) -> None:
    service.ingest_products(db, products=[_product("ET-002")])
    item = db.query(B2BWholesaleItem).one()

    updated = service.update_item(
        db,
        item_id=item.id,
        patch=_complete_patch(),
    )

    assert updated.status == STATUS_READY
    assert updated.wholesale_fields_complete() is True


def test_reingest_never_overwrites_manual_wholesale_data(db) -> None:
    """重跑一次上架,不许把人辛苦定的批发价清掉。"""
    service.ingest_products(db, products=[_product("ET-003")])
    item = db.query(B2BWholesaleItem).one()
    service.update_item(db, item_id=item.id, patch=_complete_patch())

    service.ingest_products(db, products=[_product("ET-003")])

    db.refresh(item)
    assert item.wholesale_price == Decimal("10.50")
    assert item.case_pack == 24
    assert item.status == STATUS_READY


def test_retail_price_drift_flags_item_for_review(db) -> None:
    """零售价变了必须标待复核——line sheet 上印的 MSRP 不能和网站对不上。"""
    service.ingest_products(db, products=[_product("ET-004", price="25.99")])
    item = db.query(B2BWholesaleItem).one()
    service.update_item(db, item_id=item.id, patch=_complete_patch())

    result = service.ingest_products(
        db,
        products=[_product("ET-004", price="29.99")],
    )

    db.refresh(item)
    assert result.flagged_for_review == 1
    assert item.needs_review is True
    assert "25.99" in (item.review_reason or "")
    assert item.msrp == Decimal("29.99")


def test_price_drift_does_not_flag_items_without_wholesale_price(db) -> None:
    service.ingest_products(db, products=[_product("ET-005", price="25.99")])

    result = service.ingest_products(
        db,
        products=[_product("ET-005", price="31.00")],
    )

    assert result.flagged_for_review == 0


def test_wholesale_price_above_retail_is_rejected(db) -> None:
    service.ingest_products(db, products=[_product("ET-006", price="25.99")])
    item = db.query(B2BWholesaleItem).one()

    with pytest.raises(service.WholesaleValidationError):
        service.update_item(
            db,
            item_id=item.id,
            patch=WholesaleItemPatch(wholesale_price=Decimal("99.00")),
        )


def test_price_tiers_must_be_ordered_and_distinct() -> None:
    with pytest.raises(ValueError):
        WholesaleItemPatch(
            price_tiers=[
                PriceTier(min_qty=200, unit_price=Decimal("9.00")),
                PriceTier(min_qty=50, unit_price=Decimal("10.50")),
            ]
        )
    with pytest.raises(ValueError):
        WholesaleItemPatch(
            price_tiers=[
                PriceTier(min_qty=50, unit_price=Decimal("10.50")),
                PriceTier(min_qty=50, unit_price=Decimal("9.00")),
            ]
        )


def test_category_prospecting_stays_locked_below_threshold(db) -> None:
    """用户拍板:某类目可出图册的品不足 30 个,不许拿它去挖客户。"""
    for index in range(5):
        service.ingest_products(db, products=[_product(f"ET-1{index:02d}")])
    for item in db.query(B2BWholesaleItem).all():
        service.update_item(db, item_id=item.id, patch=_complete_patch())

    readiness = service.category_readiness(db)

    assert len(readiness) == 1
    entry = readiness[0]
    assert entry.ready_items == 5
    assert entry.prospecting_unlocked is False
    assert entry.shortfall == CATEGORY_PROSPECTING_MIN_READY_ITEMS - 5


def test_category_prospecting_unlocks_at_threshold(db) -> None:
    for index in range(CATEGORY_PROSPECTING_MIN_READY_ITEMS):
        service.ingest_products(db, products=[_product(f"ET-2{index:03d}")])
    for item in db.query(B2BWholesaleItem).all():
        service.update_item(db, item_id=item.id, patch=_complete_patch())

    entry = service.category_readiness(db)[0]

    assert entry.ready_items == CATEGORY_PROSPECTING_MIN_READY_ITEMS
    assert entry.prospecting_unlocked is True
    assert entry.shortfall == 0


def test_export_refuses_when_nothing_is_wholesale_ready(db, tmp_path) -> None:
    service.ingest_products(db, products=[_product("ET-300")])

    with pytest.raises(service.WholesaleValidationError):
        service.build_line_sheet_request(
            db,
            payload=LineSheetExportRequest(fmt="pdf"),
            image_dir=Path(tmp_path),
        )


def test_export_builds_request_with_site_matching_identity(db, tmp_path) -> None:
    """图册抬头必须和 /contact/ 页一致,不能再开第二套口径。"""
    service.ingest_products(db, products=[_product("ET-301")])
    item = db.query(B2BWholesaleItem).one()
    service.update_item(db, item_id=item.id, patch=_complete_patch())

    request = service.build_line_sheet_request(
        db,
        payload=LineSheetExportRequest(fmt="pdf", edition_label="2026 Fall"),
        image_dir=Path(tmp_path),
    )

    assert len(request.items) == 1
    assert request.items[0].sku == "ET-301"
    assert request.items[0].wholesale_price == Decimal("10.50")
    assert request.meta.legal_entity == "Guangzhou Longjie E-Commerce Co., Ltd."
    assert request.meta.contact_email == "service@barongyekhna.com"
    assert request.meta.edition_label == "2026 Fall"


def test_export_filters_by_category_prefix(db, tmp_path) -> None:
    service.ingest_products(
        db,
        products=[
            _product("ET-400"),
            _product(
                "PSPE-400",
                price="79.00",
                category=["Sporting Goods", "Outdoor Recreation"],
            ),
        ],
    )
    for item in db.query(B2BWholesaleItem).all():
        service.update_item(db, item_id=item.id, patch=_complete_patch())

    request = service.build_line_sheet_request(
        db,
        payload=LineSheetExportRequest(
            fmt="pdf",
            category_prefix=["Sporting Goods"],
        ),
        image_dir=Path(tmp_path),
    )

    assert [item.sku for item in request.items] == ["PSPE-400"]


def test_ingest_skips_records_without_sku_or_name(db) -> None:
    result = service.ingest_products(
        db,
        products=[
            {"sku": "", "product_name": "No SKU"},
            {"sku": "ET-500", "product_name": ""},
        ],
    )

    assert result.created == 0
    assert result.skipped == 2


def test_variant_note_handles_non_string_columns() -> None:
    """quantity 是整数列——早期版本直接 .strip() 炸过,回灌整批静默失败。"""
    note = ingest_from_k._format_variant_note(
        [
            ("Gold", None, None, 12),
            ("blue", "L", "Deluxe", 12),
            (None, None, None, 24),
        ]
    )

    assert note is not None
    assert "2 colors: Gold, Blue" in note
    assert "Sizes: L" in note
    assert "Styles: Deluxe" in note
    # 装量按数值排序,不是插入顺序
    assert "Pack sizes: 12, 24" in note


def test_variant_note_sorts_pack_sizes_numerically() -> None:
    note = ingest_from_k._format_variant_note(
        [(None, None, None, 2), (None, None, None, 1), (None, None, None, 10)]
    )
    assert note == "Pack sizes: 1, 2, 10"


def test_variant_note_is_none_without_variants() -> None:
    assert ingest_from_k._format_variant_note([]) is None
    assert ingest_from_k._format_variant_note([(None, None, None, None)]) is None
