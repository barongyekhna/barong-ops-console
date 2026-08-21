"""霓旌的手 × 真库:以说话人的身份开单,单据 actor 是说话人,note 带 C19 消息 ID。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete

from backend.app.db.session import SessionLocal
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.agent_series.nijing import executor
from backend.app.modules.agent_series.nijing.executor import NeedsClarification, NotAuthorized
from backend.app.modules.agent_series.nijing.intents import Intent
from backend.app.modules.m_series.inventory import schemas as S
from backend.app.modules.m_series.inventory import service
from backend.app.modules.m_series.inventory.models import (
    MfgBomLine,
    MfgDocCounter,
    MfgDocument,
    MfgItem,
    MfgMovement,
)

pytestmark = pytest.mark.integration

FACTORY_ORG_ID = "org_" + "f" * 32
D = Decimal


def _clear(session) -> None:
    for model in (MfgMovement, MfgDocument, MfgBomLine, MfgItem, MfgDocCounter):
        session.execute(delete(model))
    session.execute(delete(OrganizationRecord).where(OrganizationRecord.org_id == FACTORY_ORG_ID))
    session.commit()


@pytest.fixture
def db():
    with SessionLocal() as session:
        _clear(session)
        session.add(OrganizationRecord(org_id=FACTORY_ORG_ID, org_name="测试制造公司", org_type="factory", owner_user_id="1", status="active", metadata_json={}))
        session.commit()
        yield session
        _clear(session)


def _owner() -> User:
    u = User(username="boss", password_hash="x", role="owner", is_active=True)
    u.id = 1
    return u


def _viewer() -> User:
    u = User(username="v", password_hash="x", role="viewer", is_active=True, organization_id=FACTORY_ORG_ID)
    u.id = 9
    return u


def _setup(db, ctx):
    leg = service.create_item(db, ctx, S.ItemCreate(kind="part", code="TBL-LEG", name="桌腿", unit="条"))
    top = service.create_item(db, ctx, S.ItemCreate(kind="part", code="TBL-TOP", name="桌面", unit="个"))
    box = service.create_item(db, ctx, S.ItemCreate(kind="part", code="CTN", name="纸箱", unit="个"))
    table = service.create_item(db, ctx, S.ItemCreate(kind="product", code="TBL-001", name="折叠桌", unit="套"))
    service.replace_bom(db, ctx, table.id, S.BomReplace(lines=[
        S.BomLineInput(part_id=top.id, mode="per_unit", qty=D(1)),
        S.BomLineInput(part_id=leg.id, mode="per_unit", qty=D(4)),
        S.BomLineInput(part_id=box.id, mode="per_carton", qty=D(10)),
    ]))
    service.receipt(db, ctx, user=_owner(), payload=S.ReceiptCreate(lines=[
        S.ReceiptLine(item_id=leg.id, qty=D(80)), S.ReceiptLine(item_id=top.id, qty=D(50)), S.ReceiptLine(item_id=box.id, qty=D(5)),
    ]))
    return leg, top, box, table


def _card(db, ctx, intent, speaker=None):
    return executor.build_card(db, ctx, intent=intent, speaker=speaker or _owner(), conversation_id="c1", now=0.0)


def test_authorize_is_the_same_gate_as_http(db) -> None:
    ctx = executor.authorize(db, _owner())
    assert ctx.factory_org_id == FACTORY_ORG_ID
    with pytest.raises(NotAuthorized):
        executor.authorize(db, _viewer())
    inactive = _owner()
    inactive.is_active = False
    with pytest.raises(NotAuthorized):
        executor.authorize(db, inactive)


def test_full_chain_as_speaker(db) -> None:
    ctx = executor.authorize(db, _owner())
    leg, top, box, table = _setup(db, ctx)

    card = _card(db, ctx, Intent(intent="receipt", item="桌腿", qty=D(1000), unit="条"))
    assert "+1,000 条" in card.text and "80 → 1,080" in card.text
    reply, docs = executor.execute_card(db, ctx, card=card, speaker=_owner(), original_text="今天入库一千条桌腿", record_id="rec-1")
    assert docs == ["RC-000002"] and "1,080" in reply
    doc = db.query(MfgDocument).filter_by(doc_no="RC-000002").one()
    assert doc.actor_user_id == "1" and "c19:rec-1" in (doc.note or "") and "今天入库一千条桌腿" in doc.note

    # 生产:箱规向上取整 + 预演进卡
    card = _card(db, ctx, Intent(intent="production", item="折叠桌", qty=D(15), unit="套"))
    assert "纸箱(CTN) 2 个(按箱,向上取整)" in card.text
    reply, docs = executor.execute_card(db, ctx, card=card, speaker=_owner(), original_text="生产15套折叠桌", record_id="rec-2")
    assert docs == ["PR-000001"]
    stock = {r.code: r.stock for r in service.stock_rows(db, ctx)}
    assert stock == {"TBL-LEG": D(1020), "TBL-TOP": D(35), "CTN": D(3), "TBL-001": D(15)}

    # 缺料:不出卡、不落单
    with pytest.raises(NeedsClarification) as exc:
        _card(db, ctx, Intent(intent="production", item="折叠桌", qty=D(500)))
    assert "缺" in str(exc.value) and db.query(MfgDocument).count() == 3

    # 发货 + 超量
    card = _card(db, ctx, Intent(intent="shipment", item="TBL-001", qty=D(10)))
    executor.execute_card(db, ctx, card=card, speaker=_owner(), original_text="发货10套", record_id="rec-3")
    with pytest.raises(NeedsClarification):
        _card(db, ctx, Intent(intent="shipment", item="折叠桌", qty=D(6)))

    # 单位不符 / 多命中 / 不存在 / 调整没原因
    with pytest.raises(NeedsClarification, match="单位"):
        _card(db, ctx, Intent(intent="receipt", item="桌腿", qty=D(1), unit="个"))
    with pytest.raises(NeedsClarification, match="哪个"):
        _card(db, ctx, Intent(intent="receipt", item="桌", qty=D(1)))
    with pytest.raises(NeedsClarification, match="没有叫"):
        _card(db, ctx, Intent(intent="receipt", item="螺丝", qty=D(1)))
    with pytest.raises(NeedsClarification, match="原因"):
        _card(db, ctx, Intent(intent="adjustment", item="纸箱", qty=D(-1)))

    # 查询
    assert "1,020 条" in executor.stock_reply(db, ctx, Intent(intent="query_stock", item="桌腿"))
    assert "SH-000001" in executor.documents_reply(db, ctx, Intent(intent="query_documents"))


def test_undo_reverses_latest_own_document(db) -> None:
    ctx = executor.authorize(db, _owner())
    leg, top, box, table = _setup(db, ctx)
    card = _card(db, ctx, Intent(intent="production", item="折叠桌", qty=D(10)))
    executor.execute_card(db, ctx, card=card, speaker=_owner(), original_text="生产10套", record_id="rec-p")
    undo = executor.build_undo_card(db, ctx, intent=Intent(intent="undo"), speaker=_owner(), conversation_id="c1", now=0.0)
    assert undo.undo_doc_no == "PR-000001" and len(undo.reversals) == 4
    reply, docs = executor.execute_card(db, ctx, card=undo, speaker=_owner(), original_text="撤销", record_id="rec-u")
    assert len(docs) == 4
    stock = {r.code: r.stock for r in service.stock_rows(db, ctx)}
    assert stock == {"TBL-LEG": D(80), "TBL-TOP": D(50), "CTN": D(5), "TBL-001": D(0)}
    # 冲销单不能再被冲
    with pytest.raises(NeedsClarification, match="冲销单"):
        executor.build_undo_card(db, ctx, intent=Intent(intent="undo", doc_ref=docs[0]), speaker=_owner(), conversation_id="c1", now=0.0)
