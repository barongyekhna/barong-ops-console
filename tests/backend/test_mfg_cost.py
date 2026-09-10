"""M 系列 · 出货成本明细:先进先出取价、成本冻结、缺价拒绝出数、有效期。

这些测试要真数据库(建表由 integration 通道的 alembic upgrade 完成)。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete

from backend.app.db.session import SessionLocal
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.m_series.cost import models as C
from backend.app.modules.m_series.cost import schemas as CS
from backend.app.modules.m_series.cost import service as cost
from backend.app.modules.m_series.cost.fifo import Batch, draw, queue_after_consumption
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

FACTORY_ORG_ID = "org_" + "c" * 32
RECIPIENT_ID = 90210
D = Decimal


def _clear(session) -> None:
    for model in (
        C.MfgCostSheetShare,
        C.MfgCostSheetLine,
        C.MfgCostSheet,
        C.MfgLaborLine,
        C.MfgLaborRate,
        C.MfgLaborProcess,
        C.MfgItemPrice,
        C.MfgSalePrice,
        MfgMovement,
        MfgDocument,
        MfgBomLine,
        MfgItem,
        MfgCodeGroup,
        MfgDocCounter,
    ):
        session.execute(delete(model))
    session.execute(
        delete(OrganizationRecord).where(OrganizationRecord.org_id == FACTORY_ORG_ID)
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
    user = User(username="cost_owner", password_hash="x", role="owner", is_active=True)
    user.id = 1
    return user


def _item(db, ctx, kind, code, unit="个", is_volatile=False):
    return service.create_item(
        db,
        ctx,
        S.ItemCreate(
            kind=kind, code=code, name=code, unit=unit, is_volatile=is_volatile
        ),
    )


def _receive(db, ctx, item, qty, price, freight="0"):
    return service.receipt(
        db,
        ctx,
        user=_owner(),
        payload=S.ReceiptCreate(
            lines=[
                S.ReceiptLine(
                    item_id=item.id,
                    qty=D(qty),
                    unit_price=None if price is None else D(price),
                    freight_total=D(freight),
                )
            ]
        ),
    )


def _simple_product(db, ctx, *, volatile_wire=False):
    """一个成品 = 2 米电线 + 1 个外壳。"""
    wire = _item(db, ctx, "part", "WIRE", "米", is_volatile=volatile_wire)
    shell = _item(db, ctx, "part", "SHELL", "个")
    product = _item(db, ctx, "product", "LAMP", "套")
    service.replace_bom(
        db,
        ctx,
        product.id,
        S.BomReplace(
            lines=[
                S.BomLineInput(part_id=wire.id, mode="per_unit", qty=D("2")),
                S.BomLineInput(part_id=shell.id, mode="per_unit", qty=D("1")),
            ]
        ),
    )
    return wire, shell, product


# ---------------------------------------------------------------- 纯函数


def _batch(qty, price, days_ago, mid=None):
    return Batch(
        movement_id=mid or uuid4(),
        qty=D(qty),
        unit_price=None if price is None else D(price),
        unit_freight=D("0"),
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )


def test_queue_head_advances_as_stock_is_consumed():
    batches = [_batch("100", "10", 3), _batch("100", "20", 2), _batch("100", "30", 1)]

    # 一件没消耗:队头是第一批
    assert queue_after_consumption(batches, D("0"))[0].unit_price == D("10")
    # 吃掉 100:队头前进到第二批
    assert queue_after_consumption(batches, D("100"))[0].unit_price == D("20")
    # 吃掉 150:队头是第二批,且只剩 50
    rest = queue_after_consumption(batches, D("150"))
    assert rest[0].unit_price == D("20")
    assert rest[0].qty == D("50.000")


def test_draw_uses_oldest_batch_first_not_newest():
    """用户的原话:先发最早生产的,就该用最早那批的价。"""
    batches = [_batch("100", "10", 3), _batch("100", "30", 1)]
    result = draw(batches, consumed=D("0"), need=D("50"))
    assert result.unit_price == D("10.0000")
    assert not result.crosses_batches


def test_draw_weights_across_batches_and_keeps_the_breakdown():
    batches = [_batch("100", "10", 3), _batch("100", "20", 1)]
    result = draw(batches, consumed=D("0"), need=D("150"))
    # 100 件 @10 + 50 件 @20 = 1500 / 150 = 10
    assert result.unit_price == D("13.3333")
    assert result.crosses_batches
    assert len(result.breakdown()) == 2


def test_unpriced_batch_makes_the_whole_line_missing_not_zero():
    """盘盈进来的料没有采购价。取到它 → 缺价,绝不当 0 算。"""
    batches = [_batch("100", None, 2)]
    result = draw(batches, consumed=D("0"), need=D("10"))
    assert result.has_missing_price
    assert result.unit_price is None


def test_shortfall_is_extrapolated_from_the_newest_batch():
    """库存不够不是缺价:预估表回答的是"再买要花多少",不是"我现在能不能生产"。"""
    batches = [_batch("10", "10", 3), _batch("10", "30", 1)]
    result = draw(batches, consumed=D("0"), need=D("30"))
    assert result.drawn_from_stock == D("20.000")
    assert result.extrapolated == D("10.000")
    assert result.rows[-1].is_extrapolated
    assert result.rows[-1].unit_price == D("30")


# ---------------------------------------------------------------- 入库分批


def test_two_prices_in_one_receipt_stay_two_batches(db, ctx):
    """同一张单上 12.40 和 13.60 的两批电线绝不能被合并成一批——
    合并了,先进先出立刻就算不准。"""
    wire = _item(db, ctx, "part", "WIRE", "米")
    service.receipt(
        db,
        ctx,
        user=_owner(),
        payload=S.ReceiptCreate(
            lines=[
                S.ReceiptLine(item_id=wire.id, qty=D("100"), unit_price=D("12.40")),
                S.ReceiptLine(item_id=wire.id, qty=D("100"), unit_price=D("13.60")),
            ]
        ),
    )
    movements = list(
        db.scalars(
            service.select(MfgMovement).where(MfgMovement.item_id == wire.id)
        )
    )
    assert len(movements) == 2
    assert {m.unit_price for m in movements} == {D("12.4000"), D("13.6000")}


def test_same_price_lines_still_merge(db, ctx):
    wire = _item(db, ctx, "part", "WIRE", "米")
    service.receipt(
        db,
        ctx,
        user=_owner(),
        payload=S.ReceiptCreate(
            lines=[
                S.ReceiptLine(item_id=wire.id, qty=D("100"), unit_price=D("12.40")),
                S.ReceiptLine(item_id=wire.id, qty=D("50"), unit_price=D("12.40")),
            ]
        ),
    )
    movements = list(
        db.scalars(
            service.select(MfgMovement).where(MfgMovement.item_id == wire.id)
        )
    )
    assert len(movements) == 1
    assert movements[0].qty_delta == D("150.000")


def test_freight_total_is_divided_into_unit_freight(db, ctx):
    """运费按整批总额录,除法由系统做——让人做除法就是让人犯错。"""
    wire = _item(db, ctx, "part", "WIRE", "米")
    _receive(db, ctx, wire, "100", "10", freight="200")
    movement = db.scalar(
        service.select(MfgMovement).where(MfgMovement.item_id == wire.id)
    )
    assert movement.unit_freight == D("2.0000")


# ---------------------------------------------------------------- 成本冻结


def test_production_freezes_cost_at_the_moment_of_production(db, ctx):
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "1000", "10")
    _receive(db, ctx, shell, "1000", "5")

    doc = service.production(
        db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=product.id, qty=D("100"))
    )
    snapshot = doc.payload_json["cost_snapshot"]

    # 100 套 × (2 米 × 10 + 1 个 × 5) = 2500
    assert snapshot["material_total"] == "2500.0000"
    assert snapshot["unit_cost"] == "25.0000"
    assert snapshot["missing_price_count"] == 0


def test_frozen_cost_does_not_move_when_prices_change_later(db, ctx):
    """铜价翻倍不能改写上个月那批货的成本。"""
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "1000", "10")
    _receive(db, ctx, shell, "1000", "5")
    doc = service.production(
        db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=product.id, qty=D("100"))
    )
    before = doc.payload_json["cost_snapshot"]["unit_cost"]

    _receive(db, ctx, wire, "1000", "40")  # 铜价翻两番
    db.refresh(doc)
    assert doc.payload_json["cost_snapshot"]["unit_cost"] == before


def test_second_production_run_eats_the_next_batch(db, ctx):
    """第一批吃完了,第二次生产就该用第二批的价。"""
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "200", "10")
    _receive(db, ctx, wire, "200", "30")
    _receive(db, ctx, shell, "1000", "5")

    first = service.production(
        db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=product.id, qty=D("100"))
    )
    second = service.production(
        db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=product.id, qty=D("100"))
    )

    # 第一次:200 米 @10 → 单位物料 20 + 外壳 5 = 25
    assert first.payload_json["cost_snapshot"]["unit_cost"] == "25.0000"
    # 第二次:第一批已耗尽,吃第二批 @30 → 60 + 5 = 65
    assert second.payload_json["cost_snapshot"]["unit_cost"] == "65.0000"


def test_cost_snapshot_records_which_batches_were_eaten(db, ctx):
    """一个加权出来的数字,必须留下它是从哪几批来的。"""
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "100", "10")
    _receive(db, ctx, wire, "100", "20")
    _receive(db, ctx, shell, "1000", "5")

    doc = service.production(
        db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=product.id, qty=D("75"))
    )
    wire_row = next(
        r for r in doc.payload_json["cost_snapshot"]["materials"] if r["code"] == "WIRE"
    )
    # 需要 150 米:100 @10 + 50 @20 = 2000 / 150 = 13.3333
    assert wire_row["crosses_batches"] is True
    assert len(wire_row["batches"]) == 2
    assert wire_row["unit_price"] == "13.3333"


# ---------------------------------------------------------------- 缺价


def test_missing_price_refuses_to_total_instead_of_counting_as_zero(db, ctx):
    """最重要的一条:缺价绝不当 0 算。一个看着完整的假总价会被直接拿去报价。"""
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "1000", "10")
    _receive(db, ctx, shell, "1000", None)  # 外壳没记价格

    preview = cost.preview_sheet(db, ctx, product_id=product.id, batch_qty=D("10"))

    assert preview.totals.missing_price_count == 1
    assert preview.totals.unit_cost is None
    assert preview.totals.material_total is None
    shell_row = next(r for r in preview.materials if r.code == "SHELL")
    assert shell_row.missing_price is True


def test_sale_price_and_margin_survive_missing_cost(db, ctx):
    """出厂价是人填的,不依赖成本——缺价时它照常显示,只是毛利算不出来。"""
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, shell, "1000", None)
    cost.set_sale_price(
        db, ctx, product.id, user=_owner(), payload=CS.SalePriceCreate(unit_price=D("100"))
    )

    preview = cost.preview_sheet(db, ctx, product_id=product.id, batch_qty=D("10"))
    assert preview.sale_price == D("100.0000")
    assert preview.unit_margin is None
    assert preview.margin_rate is None


# ---------------------------------------------------------------- 人工


def test_per_batch_labour_is_spread_over_the_run_size(db, ctx):
    """调机费 1000 元:100 件时每件 10 元,1000 件时每件 1 元。
    这一条直接决定小单能不能接。"""
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "10000", "10")
    _receive(db, ctx, shell, "10000", "5")

    setup = cost.create_process(
        db, ctx, user=_owner(), payload=CS.LaborProcessCreate(name="调机", rate=D("1000"))
    )
    cost.replace_product_labor(
        db,
        ctx,
        product.id,
        CS.LaborReplace(
            lines=[
                CS.LaborLineInput(process_id=setup.id, mode="per_batch", qty=D("1"))
            ]
        ),
    )

    small = cost.preview_sheet(db, ctx, product_id=product.id, batch_qty=D("100"))
    large = cost.preview_sheet(db, ctx, product_id=product.id, batch_qty=D("1000"))

    assert small.totals.unit_cost == D("35.0000")  # 25 料 + 10 摊销
    assert large.totals.unit_cost == D("26.0000")  # 25 料 + 1 摊销


def test_labour_rate_change_is_a_new_row_not_an_edit(db, ctx):
    process = cost.create_process(
        db, ctx, user=_owner(), payload=CS.LaborProcessCreate(name="组装", rate=D("8"))
    )
    cost.add_labor_rate(
        db, ctx, process.id, user=_owner(), payload=CS.LaborRateCreate(rate=D("9.5"))
    )
    rates = cost.list_labor_rates(db, ctx, process.id)
    assert len(rates) == 2
    assert {r.rate for r in rates} == {D("8.0000"), D("9.5000")}


# ---------------------------------------------------------------- 出厂价 / 有效期


def test_sale_price_change_is_a_new_row_and_latest_wins(db, ctx):
    _, _, product = _simple_product(db, ctx)
    cost.set_sale_price(
        db, ctx, product.id, user=_owner(), payload=CS.SalePriceCreate(unit_price=D("100"))
    )
    cost.set_sale_price(
        db, ctx, product.id, user=_owner(), payload=CS.SalePriceCreate(unit_price=D("120"))
    )
    history = cost.list_sale_prices(db, ctx, product.id)
    assert len(history) == 2
    assert history[0].unit_price == D("120.0000")


def test_volatile_material_shortens_the_quote_validity(db, ctx):
    """全表取最短:只要用到一个波动料,整张表就是 7 天。"""
    wire, shell, product = _simple_product(db, ctx, volatile_wire=True)
    _receive(db, ctx, wire, "1000", "10")
    _receive(db, ctx, shell, "1000", "5")

    preview = cost.preview_sheet(db, ctx, product_id=product.id, batch_qty=D("10"))
    assert preview.has_volatile is True
    assert preview.valid_days == 7


def test_without_volatile_material_validity_is_thirty_days(db, ctx):
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "1000", "10")
    _receive(db, ctx, shell, "1000", "5")

    preview = cost.preview_sheet(db, ctx, product_id=product.id, batch_qty=D("10"))
    assert preview.has_volatile is False
    assert preview.valid_days == 30


# ---------------------------------------------------------------- 两种成色


def test_stocked_product_reads_the_frozen_cost_not_todays_prices(db, ctx):
    """有货就读那批生产时冻结的成本,不拿今天的料价重算。"""
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "1000", "10")
    _receive(db, ctx, shell, "1000", "5")
    service.production(
        db, ctx, user=_owner(), payload=S.ProductionCreate(product_id=product.id, qty=D("100"))
    )
    _receive(db, ctx, wire, "1000", "40")  # 之后铜价暴涨

    preview = cost.preview_sheet(db, ctx, product_id=product.id, batch_qty=D("10"))
    assert preview.basis == "actual"
    assert preview.totals.unit_cost == D("25.0000")
    assert preview.source_doc_no is not None


def test_unproduced_product_is_marked_estimate(db, ctx):
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "1000", "10")
    _receive(db, ctx, shell, "1000", "5")

    preview = cost.preview_sheet(db, ctx, product_id=product.id, batch_qty=D("10"))
    assert preview.basis == "estimate"
    assert preview.totals.unit_cost == D("25.0000")


# ---------------------------------------------------------------- 快照定稿


def test_sheet_snapshot_survives_a_later_rename_and_price_change(db, ctx):
    """发出去的数字再也不能变。"""
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "1000", "10")
    _receive(db, ctx, shell, "1000", "5")
    cost.set_sale_price(
        db, ctx, product.id, user=_owner(), payload=CS.SalePriceCreate(unit_price=D("100"))
    )

    sheet = cost.create_sheet(
        db,
        ctx,
        user=_owner(),
        payload=CS.CostSheetCreate(product_id=product.id, batch_qty=D("10")),
    )
    frozen_cost = sheet.unit_cost

    # 事后改名 + 涨价
    service.patch_item(db, ctx, wire.id, S.ItemPatch(name="镀锡铜线"))
    _receive(db, ctx, wire, "1000", "99")

    detail = cost.get_sheet(db, ctx, sheet.id)
    assert detail.unit_cost == frozen_cost
    assert any(line.name == "WIRE" for line in detail.materials)


def test_sheet_numbers_are_sequential(db, ctx):
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "1000", "10")
    _receive(db, ctx, shell, "1000", "5")
    first = cost.create_sheet(
        db, ctx, user=_owner(), payload=CS.CostSheetCreate(product_id=product.id, batch_qty=D("1"))
    )
    second = cost.create_sheet(
        db, ctx, user=_owner(), payload=CS.CostSheetCreate(product_id=product.id, batch_qty=D("1"))
    )
    assert first.sheet_no == "CS-000001"
    assert second.sheet_no == "CS-000002"


# ---------------------------------------------------------------- 分享


class _FakeConversation:
    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id


class _FakeRecord:
    def __init__(self, record_id: str, content: str) -> None:
        self.id = record_id
        self.content = content


class _FakePage:
    def __init__(self, items) -> None:
        self.items = items


class _FakeConversationService:
    def create_direct_conversation(self, db, *, payload, actor):
        return _FakeConversation(f"conv_{'a' * 32}")


class _FakeMessageService:
    """假的 C19。``deliver`` 决定回读时那条消息在不在会话里。"""

    def __init__(self, *, deliver: bool = True) -> None:
        self.deliver = deliver
        self.sent: list[str] = []

    async def send_message(self, db, *, actor, conversation_id, payload, store):
        self.sent.append(payload.content)
        return _FakeRecord("rec_1", payload.content)

    async def list_message_history(
        self, db, *, actor, conversation_id, limit, cursor, store
    ):
        if not self.deliver:
            return _FakePage([])
        return _FakePage([_FakeRecord("rec_1", self.sent[-1])])


class _FakeDirectRequest:
    def __init__(self, *, peer_user_id: int) -> None:
        self.peer_user_id = peer_user_id


class _FakeMessageRequest:
    def __init__(self, *, client_message_id: str, content_type: str, content: str) -> None:
        self.client_message_id = client_message_id
        self.content_type = content_type
        self.content = content


def _share(db, ctx, sheet_id, *, mode="full", deliver=True, user=None):
    from types import SimpleNamespace

    from backend.app.modules.m_series.cost import share as share_mod

    messages = _FakeMessageService(deliver=deliver)
    result = asyncio.run(
        share_mod.share_sheet(
            db,
            ctx,
            sheet_id,
            user=user or _owner(),
            payload=CS.CostShareRequest(
                recipient_user_ids=[RECIPIENT_ID], share_mode=mode
            ),
            store=object(),
            conversation_service=_FakeConversationService(),
            message_service=messages,
            conversation_schemas=SimpleNamespace(
                DirectConversationCreateRequest=_FakeDirectRequest
            ),
            message_schemas=SimpleNamespace(
                MessageCreateRequest=_FakeMessageRequest
            ),
        )
    )
    return result, messages


def _ready_sheet(db, ctx):
    wire, shell, product = _simple_product(db, ctx)
    _receive(db, ctx, wire, "1000", "10")
    _receive(db, ctx, shell, "1000", "5")
    cost.set_sale_price(
        db, ctx, product.id, user=_owner(), payload=CS.SalePriceCreate(unit_price=D("100"))
    )
    return cost.create_sheet(
        db,
        ctx,
        user=_owner(),
        payload=CS.CostSheetCreate(product_id=product.id, batch_qty=D("10")),
    )


def test_full_share_writes_the_ledger_only_after_read_back(db, ctx):
    sheet = _ready_sheet(db, ctx)
    result, _ = _share(db, ctx, sheet.id)

    assert len(result.delivered) == 1
    assert not result.failed
    rows = list(db.scalars(service.select(C.MfgCostSheetShare)))
    assert len(rows) == 1
    # 回读确认过才算送达。接口返回 200 不算数。
    assert rows[0].verified_at is not None


def test_send_that_cannot_be_read_back_is_not_recorded_as_shared(db, ctx):
    """发送接口没报错,但回读时消息不在会话里——绝不能记成「已分享」。"""
    sheet = _ready_sheet(db, ctx)
    result, _ = _share(db, ctx, sheet.id, deliver=False)

    assert not result.delivered
    assert len(result.failed) == 1
    assert "回读" in result.failed[0]["error"]
    assert list(db.scalars(service.select(C.MfgCostSheetShare))) == []


def test_price_only_card_contains_no_cost_figures_at_all(db, ctx):
    """这条口径的全部意义:成本数字压根不进这条消息,所以转发也漏不出去。"""
    sheet = _ready_sheet(db, ctx)
    _, messages = _share(db, ctx, sheet.id, mode="price_only")

    content = messages.sent[0]
    assert "出厂价 100.00" in content
    assert "料|" not in content
    assert "工|" not in content
    assert "计：" not in content
    assert "毛利" not in content
    # 单位成本是 25.00,这个数字绝不能出现在仅出厂价的卡片里
    assert "25.00" not in content


def test_full_card_carries_the_cost_breakdown(db, ctx):
    sheet = _ready_sheet(db, ctx)
    _, messages = _share(db, ctx, sheet.id, mode="full")

    content = messages.sent[0]
    assert "料|" in content
    assert "单位成本 25.00" in content
    assert "毛利率 75.0%" in content
    assert content.rstrip().endswith("⟧")


def test_card_head_and_marker_tokens_match(db, ctx):
    """头尾标记对不上,前端就不认这张卡,整条消息退化成带竖线的纯文本。"""
    sheet = _ready_sheet(db, ctx)
    _, messages = _share(db, ctx, sheet.id)

    lines = messages.sent[0].split("\n")
    head = next(line for line in lines if line.startswith("【出货明细 #"))
    marker = lines[-1]
    token = head.split("#")[1].split("】")[0]
    assert marker == f"⟦cost:{token}⟧"
