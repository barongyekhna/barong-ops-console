"""M 系列 · 制造库存:BOM 展开、负库存拦死、流水求和、单号、快照。

这些测试要真数据库(建表由 integration 通道的 alembic upgrade 完成)。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete

from backend.app.db.session import SessionLocal
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.m_series.inventory import schemas as S
from backend.app.modules.m_series.inventory import service
from backend.app.modules.m_series.inventory.models import (
    MfgBomLine,
    MfgCodeGroup,
    MfgDocCounter,
    MfgDocument,
    MfgItem,
    MfgMovement,
)

pytestmark = pytest.mark.integration

FACTORY_ORG_ID = "org_" + "f" * 32
D = Decimal


def _clear(session) -> None:
    for model in (MfgMovement, MfgDocument, MfgBomLine, MfgItem, MfgCodeGroup, MfgDocCounter):
        session.execute(delete(model))
    session.execute(
        delete(OrganizationRecord).where(
            OrganizationRecord.org_id.in_([FACTORY_ORG_ID, "org_" + "e" * 32])
        )
    )
    session.commit()


@pytest.fixture
def db():
    with SessionLocal() as session:
        _clear(session)
        session.add(
            OrganizationRecord(
                org_id=FACTORY_ORG_ID,
                org_name="测试制造公司",
                org_type="factory",
                owner_user_id="1",
                status="active",
                metadata_json={},
            )
        )
        session.commit()
        yield session
        _clear(session)


@pytest.fixture
def ctx(db) -> service.FactoryContext:
    return service.resolve_factory_context(db)


def _owner() -> User:
    user = User(username="mfg_owner", password_hash="x", role="owner", is_active=True)
    user.id = 1
    return user


def _item(db, ctx, kind, code, unit="个"):
    return service.create_item(
        db, ctx, S.ItemCreate(kind=kind, code=code, name=code, unit=unit)
    )


def _table_setup(db, ctx):
    """桌子 = 1 桌面 + 4 桌腿 + 1 横梁;10 张装 1 个纸箱。"""
    top = _item(db, ctx, "part", "TOP")
    leg = _item(db, ctx, "part", "LEG", "条")
    beam = _item(db, ctx, "part", "BEAM", "根")
    box = _item(db, ctx, "part", "BOX", "个")
    table = _item(db, ctx, "product", "TABLE", "套")
    service.replace_bom(
        db,
        ctx,
        table.id,
        S.BomReplace(
            lines=[
                S.BomLineInput(part_id=top.id, mode="per_unit", qty=D("1")),
                S.BomLineInput(part_id=leg.id, mode="per_unit", qty=D("4")),
                S.BomLineInput(part_id=beam.id, mode="per_unit", qty=D("1")),
                S.BomLineInput(part_id=box.id, mode="per_carton", qty=D("10")),
            ]
        ),
    )
    service.receipt(
        db,
        ctx,
        user=_owner(),
        payload=S.ReceiptCreate(
            lines=[
                S.ReceiptLine(item_id=top.id, qty=D("1000")),
                S.ReceiptLine(item_id=leg.id, qty=D("800")),
                S.ReceiptLine(item_id=beam.id, qty=D("500")),
                S.ReceiptLine(item_id=box.id, qty=D("100")),
            ]
        ),
    )
    return {"top": top, "leg": leg, "beam": beam, "box": box, "table": table}


def _stock(db, ctx, *items):
    s = service.stock_of(db, ctx, [i.id for i in items])
    return [s[i.id] for i in items]


def test_required_for_rounds_cartons_up() -> None:
    assert service.required_for("per_unit", D("4"), D("100")) == D("400")
    assert service.required_for("per_carton", D("10"), D("100")) == D("10")
    assert service.required_for("per_carton", D("10"), D("105")) == D("11")
    assert service.required_for("per_carton", D("50"), D("1")) == D("1")


def test_production_deducts_bom_and_adds_product(db, ctx) -> None:
    it = _table_setup(db, ctx)
    doc = service.production(
        db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=it["table"].id, qty=D("100"))
    )
    assert doc.doc_no == "PR-000001"
    assert _stock(db, ctx, it["top"], it["leg"], it["beam"], it["box"], it["table"]) == [
        D("900"),
        D("400"),
        D("400"),
        D("90"),
        D("100"),
    ]
    snapshot = {row["code"]: row for row in doc.payload_json["bom_snapshot"]}
    assert snapshot["LEG"]["consumed"] == "400.000"
    assert snapshot["BOX"]["mode"] == "per_carton"
    assert snapshot["BOX"]["consumed"] == "10.000"


def test_production_rejects_whole_order_when_any_part_short(db, ctx) -> None:
    it = _table_setup(db, ctx)
    # 800 条腿只够 200 套;201 套差 4 条
    with pytest.raises(service.InsufficientStock) as exc:
        service.production(
            db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=it["table"].id, qty=D("201"))
        )
    shortages = {row.code: row for row in exc.value.shortages}
    assert set(shortages) == {"LEG"}
    assert shortages["LEG"].required == D("804")
    assert shortages["LEG"].short == D("4")
    # 零写入:桌面没被扣,成品没被加,也没有生产单
    assert _stock(db, ctx, it["top"], it["table"]) == [D("1000"), D("0")]
    assert db.query(MfgDocument).filter_by(doc_type="production").count() == 0


def test_preview_reports_feasibility_without_writing(db, ctx) -> None:
    it = _table_setup(db, ctx)
    ok = service.preview_production(db, ctx, it["table"].id, D("200"))
    assert ok.feasible is True
    bad = service.preview_production(db, ctx, it["table"].id, D("201"))
    assert bad.feasible is False
    assert db.query(MfgDocument).count() == 1  # 只有那张入库单


def test_shipment_deducts_and_rejects_overdraw(db, ctx) -> None:
    it = _table_setup(db, ctx)
    service.production(
        db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=it["table"].id, qty=D("100"))
    )
    doc = service.shipment(
        db, ctx, user=_owner(), payload=S.ShipmentCreate(product_id=it["table"].id, qty=D("50"))
    )
    assert doc.doc_no == "SH-000001"
    assert _stock(db, ctx, it["table"]) == [D("50")]
    with pytest.raises(service.InsufficientStock):
        service.shipment(
            db, ctx, user=_owner(), payload=S.ShipmentCreate(product_id=it["table"].id, qty=D("51"))
        )
    assert _stock(db, ctx, it["table"]) == [D("50")]


def test_adjustment_requires_reason_and_blocks_negative(db, ctx) -> None:
    it = _table_setup(db, ctx)
    service.adjustment(
        db,
        ctx,
        user=_owner(),
        payload=S.AdjustmentCreate(item_id=it["leg"].id, qty_delta=D("-10"), reason="盘点少了 10 条"),
    )
    assert _stock(db, ctx, it["leg"]) == [D("790")]
    with pytest.raises(service.InsufficientStock):
        service.adjustment(
            db,
            ctx,
            user=_owner(),
            payload=S.AdjustmentCreate(item_id=it["leg"].id, qty_delta=D("-791"), reason="不可能"),
        )
    with pytest.raises(Exception):
        S.AdjustmentCreate(item_id=it["leg"].id, qty_delta=D("-1"), reason="")


def test_doc_numbers_are_sequential_per_type(db, ctx) -> None:
    it = _table_setup(db, ctx)
    for _ in range(2):
        service.production(
            db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=it["table"].id, qty=D("1"))
        )
    nos = sorted(d.doc_no for d in db.query(MfgDocument).all())
    assert nos == ["PR-000001", "PR-000002", "RC-000001"]


def test_bom_rejects_products_and_duplicates(db, ctx) -> None:
    it = _table_setup(db, ctx)
    other = _item(db, ctx, "product", "DESK")
    with pytest.raises(service.MfgError):
        service.replace_bom(
            db, ctx, other.id,
            S.BomReplace(lines=[S.BomLineInput(part_id=it["table"].id, mode="per_unit", qty=D("1"))]),
        )
    with pytest.raises(ValueError):
        S.BomReplace(
            lines=[
                S.BomLineInput(part_id=it["top"].id, mode="per_unit", qty=D("1")),
                S.BomLineInput(part_id=it["top"].id, mode="per_unit", qty=D("2")),
            ]
        )
    with pytest.raises(service.MfgError):
        service.get_bom(db, ctx, it["top"].id)  # 物料没有 BOM


def test_production_without_bom_is_refused(db, ctx) -> None:
    bare = _item(db, ctx, "product", "BARE")
    with pytest.raises(service.MfgError):
        service.production(
            db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=bare.id, qty=D("1"))
        )


def test_ledger_sums_and_document_detail(db, ctx) -> None:
    it = _table_setup(db, ctx)
    service.production(
        db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=it["table"].id, qty=D("30"))
    )
    service.shipment(
        db, ctx, user=_owner(), payload=S.ShipmentCreate(product_id=it["table"].id, qty=D("12"))
    )
    rows, total = service.item_movements(db, ctx, it["table"].id, limit=50, offset=0)
    assert total == 2
    assert sum(r.qty_delta for r in rows) == D("18")
    docs, n = service.list_documents(db, ctx, doc_type=None, item_id=it["table"].id, limit=50, offset=0)
    assert n == 2 and {d.doc_type for d in docs} == {"production", "shipment"}
    doc, movements = service.get_document(db, ctx, docs[-1].id if docs[-1].doc_type == "production" else docs[0].id)
    assert doc.doc_type == "production"
    assert len(movements) == 5  # 4 物料 + 1 成品
    stock = {r.code: r.stock for r in service.stock_rows(db, ctx)}
    assert stock == {"TOP": D("970"), "LEG": D("680"), "BEAM": D("470"), "BOX": D("97"), "TABLE": D("18")}


def test_duplicate_code_and_archive(db, ctx) -> None:
    _item(db, ctx, "part", "DUP")
    with pytest.raises(service.MfgError):
        _item(db, ctx, "part", "DUP")
    archived = _item(db, ctx, "part", "OLD")
    service.patch_item(db, ctx, archived.id, S.ItemPatch(is_archived=True))
    assert all(i.code != "OLD" for i in service.list_items(db, ctx))
    assert any(i.code == "OLD" for i in service.list_items(db, ctx, include_archived=True))
    with pytest.raises(service.MfgNotFound):
        service.patch_item(db, ctx, uuid4(), S.ItemPatch(name="x"))


def test_shared_part_is_deducted_by_every_product_using_it(db, ctx) -> None:
    """餐桌 A 和餐桌 B 用同一种桌腿、不同桌面:物料是共享的,谁生产谁扣。"""
    leg = _item(db, ctx, "part", "LEG", "条")
    top_a = _item(db, ctx, "part", "TOP-A")
    top_b = _item(db, ctx, "part", "TOP-B")
    table_a = _item(db, ctx, "product", "TABLE-A", "套")
    table_b = _item(db, ctx, "product", "TABLE-B", "套")
    for product, top in ((table_a, top_a), (table_b, top_b)):
        service.replace_bom(
            db, ctx, product.id,
            S.BomReplace(lines=[
                S.BomLineInput(part_id=top.id, mode="per_unit", qty=D("1")),
                S.BomLineInput(part_id=leg.id, mode="per_unit", qty=D("4")),
            ]),
        )
    service.receipt(
        db, ctx, user=_owner(),
        payload=S.ReceiptCreate(lines=[
            S.ReceiptLine(item_id=leg.id, qty=D("100")),
            S.ReceiptLine(item_id=top_a.id, qty=D("50")),
            S.ReceiptLine(item_id=top_b.id, qty=D("50")),
        ]),
    )
    service.production(db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=table_a.id, qty=D("10")))
    service.production(db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=table_b.id, qty=D("10")))
    assert _stock(db, ctx, leg, top_a, top_b, table_a, table_b) == [D("20"), D("40"), D("40"), D("10"), D("10")]
    # 桌腿只剩 20 条 = 5 套;B 要生产 6 套被共享的桌腿拦住,哪怕 B 自己的桌面够
    with pytest.raises(service.InsufficientStock) as exc:
        service.production(db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=table_b.id, qty=D("6")))
    assert [r.code for r in exc.value.shortages] == ["LEG"]
    # 发货只扣成品,不再碰桌腿
    service.shipment(db, ctx, user=_owner(), payload=S.ShipmentCreate(product_id=table_a.id, qty=D("10")))
    assert _stock(db, ctx, leg, table_a) == [D("20"), D("0")]


# ---------------------------------------------------------------- 自动编码


def _group(db, ctx, kind, code, name):
    return service.create_code_group(db, ctx, S.CodeGroupCreate(kind=kind, code=code, name=name))


def _auto(db, ctx, kind, group, name, unit="个"):
    return service.create_item(
        db, ctx, S.ItemCreate(kind=kind, group_id=group.id, name=name, unit=unit)
    )


def test_default_part_groups_are_seeded_once(db, ctx) -> None:
    groups = service.list_code_groups(db, ctx, kind="part")
    codes = [g.code for g in groups]
    assert "PK" in codes and "HW" in codes and len(codes) == len(service.DEFAULT_PART_GROUPS)
    assert service.list_code_groups(db, ctx, kind="product") == []
    # 再列一次不重复预置
    assert len(service.list_code_groups(db, ctx, kind="part")) == len(codes)


def test_product_and_part_codes_follow_separate_rules(db, ctx) -> None:
    """成品 = 系列码-三位;物料 = 大类码-四位;各组各自发号。"""
    tbl = _group(db, ctx, "product", "tbl", "折叠桌")
    assert tbl.code == "TBL"
    pk = next(g for g in service.list_code_groups(db, ctx, kind="part") if g.code == "PK")
    p1 = _auto(db, ctx, "product", tbl, "折叠桌 60cm", "套")
    p2 = _auto(db, ctx, "product", tbl, "折叠桌 80cm", "套")
    m1 = _auto(db, ctx, "part", pk, "五层纸箱")
    m2 = _auto(db, ctx, "part", pk, "彩盒")
    assert (p1.code, p2.code) == ("TBL-001", "TBL-002")
    assert (m1.code, m2.code) == ("PK-0001", "PK-0002")
    assert p1.group_id == tbl.id and p1.group_code == "TBL" and p1.group_name == "折叠桌"
    rows = {r.code: r for r in service.stock_rows(db, ctx)}
    assert rows["TBL-001"].group_name == "折叠桌" and rows["PK-0001"].group_name == "包装材料"
    counts = {g.code: g.item_count for g in service.list_code_groups(db, ctx)}
    assert counts["TBL"] == 2 and counts["PK"] == 2


def test_allocator_skips_numbers_taken_by_manual_codes(db, ctx) -> None:
    tbl = _group(db, ctx, "product", "TBL", "折叠桌")
    _item(db, ctx, "product", "TBL-001", "套")  # 手填占了 001
    assert service.preview_next_code(db, ctx, tbl.id).code == "TBL-002"
    auto = _auto(db, ctx, "product", tbl, "自动的", "套")
    assert auto.code == "TBL-002"
    # 预览不占号
    assert service.preview_next_code(db, ctx, tbl.id).code == "TBL-003"
    assert service.preview_next_code(db, ctx, tbl.id).code == "TBL-003"


def test_group_code_is_unique_across_kinds_and_kind_must_match(db, ctx) -> None:
    _group(db, ctx, "product", "PK", "包装机")  # 与预置大类 PK 撞
    with pytest.raises(service.MfgError):
        service.list_code_groups(db, ctx, kind="part")
        _group(db, ctx, "part", "PK", "包材")
    with pytest.raises(service.MfgError):
        _group(db, ctx, "product", "PR", "撞单据号前缀")
    hw = next(g for g in service.list_code_groups(db, ctx, kind="part") if g.code == "HW")
    with pytest.raises(service.MfgError):
        _auto(db, ctx, "product", hw, "拿物料大类建成品")


def test_manual_code_is_uppercased_and_one_of_code_or_group(db, ctx) -> None:
    item = _item(db, ctx, "part", "tbl-leg")
    assert item.code == "TBL-LEG" and item.group_id is None
    with pytest.raises(ValueError):
        S.ItemCreate(kind="part", name="x", unit="个")
    with pytest.raises(ValueError):
        S.ItemCreate(kind="part", code="X", group_id=uuid4(), name="x", unit="个")


def test_code_can_change_only_before_first_movement(db, ctx) -> None:
    tbl = _group(db, ctx, "product", "TBL", "折叠桌")
    item = _auto(db, ctx, "product", tbl, "桌", "套")
    other = _item(db, ctx, "product", "HTR-001", "套")
    with pytest.raises(service.MfgError):
        service.patch_item(db, ctx, item.id, S.ItemPatch(code="HTR-001"))
    changed = service.patch_item(db, ctx, item.id, S.ItemPatch(code="tbl-x"))
    assert changed.code == "TBL-X" and changed.group_id is None
    service.receipt(
        db, ctx, user=_owner(),
        payload=S.ReceiptCreate(lines=[S.ReceiptLine(item_id=other.id, qty=D("1"))]),
    )
    with pytest.raises(service.MfgError):
        service.patch_item(db, ctx, other.id, S.ItemPatch(code="HTR-002"))


def test_group_code_suggestion(db, ctx) -> None:
    assert service.suggest_group_code(db, ctx, "折叠桌").code == "ZDZ"
    assert service.suggest_group_code(db, ctx, "温控加热棒").code == "WKJ"
    assert service.suggest_group_code(db, ctx, "Camping Shower").code == "CS"
    assert service.suggest_group_code(db, ctx, "Heater").code == "HEA"
    service.list_code_groups(db, ctx, kind="part")
    hint = service.suggest_group_code(db, ctx, "Product Kit")
    assert hint.code == "PK" and hint.taken is True
