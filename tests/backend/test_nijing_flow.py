"""霓旌的状态机:确认/取消/作废/过期/幂等/门禁/红灯/脑子掉线。全假件,不碰库。"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace as N

import pytest

from backend.app.modules.agent_series.common.memory_store import MemoryStore
from backend.app.modules.agent_series.nijing import worker_main as wm
from backend.app.modules.agent_series.nijing.executor import Card, NeedsClarification, NotAuthorized
from backend.app.modules.agent_series.nijing.intents import Intent

pytestmark = pytest.mark.unit

OWNER = N(id=1, username="boss", role="owner", organization_id=None, is_active=True)
VIEWER = N(id=9, username="v", role="viewer", organization_id=None, is_active=True)
CTX = N(factory_org_id="org_f", org_name="厂")


class FakeDb:
    def __init__(self, users):
        self.users = users

    def get(self, model, key):
        return self.users.get(key)

    def close(self):
        pass


class FakeClient:
    user_id = 100

    def __init__(self):
        self.sent = []
        self.records = {}

    def messages(self, cid, *, limit=20):
        return self.records.get(cid, [])

    def send_message(self, cid, *, text, client_message_id):
        self.sent.append((cid, text))


@pytest.fixture
def worker(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MEMORY_DIR", str(tmp_path))
    store = MemoryStore(username="nijing", index_title="t")
    users = {1: OWNER, 9: VIEWER}
    clock = {"t": 1000.0}
    intents = {}
    executed = []

    def extract(text):
        if text in intents:
            return intents[text]
        return Intent(intent="unsupported")

    def authorize(db, speaker):
        if speaker.role != "owner":
            raise NotAuthorized()
        return CTX

    def build_card(db, ctx, *, intent, speaker, conversation_id, now):
        if intent.item == "螺丝":
            raise NeedsClarification("库里没有叫「螺丝」的")
        return Card("ab12", intent.intent, str(speaker.id), conversation_id, f"【待确认 #ab12】{intent.intent} {intent.item} {intent.qty}", now, item_id="i1", qty=str(intent.qty))

    def execute_card(db, ctx, *, card, speaker, original_text, record_id):
        executed.append((card.card_id, record_id))
        return f"已入库 RC-000009", ["RC-000009"]

    monkeypatch.setattr(wm.executor, "authorize", authorize)
    monkeypatch.setattr(wm.executor, "build_card", build_card)
    monkeypatch.setattr(wm.executor, "execute_card", execute_card)
    monkeypatch.setattr(wm.executor, "stock_reply", lambda db, ctx, intent: "桌腿 380 条")
    monkeypatch.setattr(wm, "_log_operation", lambda **kw: None)
    w = wm.NijingWorker(client=FakeClient(), store=store, session_factory=lambda: FakeDb(users), extract=extract, clock=lambda: clock["t"])
    w.intents = intents
    w.clock_state = clock
    w.executed_calls = executed
    return w


def _say(w, text, *, speaker="1", rid=None, cid="c1"):
    return w.reply_for(conversation_id=cid, speaker_id=speaker, text=text, record_id=rid or f"r-{text}-{speaker}")


def test_write_needs_confirmation_then_executes_once(worker):
    worker.intents["入库1000条桌腿"] = Intent(intent="receipt", item="桌腿", qty=Decimal(1000), unit="条")
    card = _say(worker, "入库1000条桌腿")
    assert card.startswith("【待确认 #ab12】")
    assert worker.executed_calls == []
    ok = _say(worker, "确认", rid="r-confirm-1")
    assert "RC-000009" in ok
    assert worker.executed_calls == [("ab12", "r-confirm-1")]
    # 同一条确认消息重放 → 不二次执行
    assert "已经办过" in _say(worker, "确认", rid="r-confirm-1")
    assert len(worker.executed_calls) == 1
    # 新的「确认」但没有卡
    assert "没有待确认" in _say(worker, "确认", rid="r-confirm-2")


def test_cancel_and_other_message_void_card(worker):
    worker.intents["入库1000条桌腿"] = Intent(intent="receipt", item="桌腿", qty=Decimal(1000))
    _say(worker, "入库1000条桌腿")
    assert _say(worker, "取消") == wm.REPLY_CANCELLED
    _say(worker, "入库1000条桌腿", rid="r2")
    worker.intents["桌腿还剩多少"] = Intent(intent="query_stock", item="桌腿")
    reply = _say(worker, "桌腿还剩多少")
    assert reply.startswith("上一张卡 #ab12 已作废") and "380" in reply
    assert worker.executed_calls == []


def test_card_expires_and_only_speaker_can_confirm(worker):
    worker.intents["入库1000条桌腿"] = Intent(intent="receipt", item="桌腿", qty=Decimal(1000))
    _say(worker, "入库1000条桌腿")
    worker.clock_state["t"] += 31 * 60
    assert "没有待确认" in _say(worker, "确认", rid="late")
    _say(worker, "入库1000条桌腿", rid="again")
    # 别人(即使是 owner 身份)不能确认我开的卡 —— 这里换个 speaker id
    worker.session_factory = lambda: FakeDb({1: OWNER, 2: N(id=2, username="b", role="owner", organization_id=None, is_active=True)})
    assert "只有开卡的人" in _say(worker, "确认", speaker="2")


def test_qty_must_match_text_and_multi_red_offline(worker):
    worker.intents["生产500件餐桌"] = Intent(intent="production", item="餐桌", qty=Decimal(5000))
    assert _say(worker, "生产500件餐桌") == wm.REPLY_NO_QTY
    worker.intents["入库100条桌腿,再生产10套"] = Intent(intent="multi")
    assert _say(worker, "入库100条桌腿,再生产10套") == wm.REPLY_MULTI
    worker.intents["新建一个物料叫螺丝"] = Intent(intent="create_item", item="螺丝")
    assert _say(worker, "新建一个物料叫螺丝") == wm.REPLY_RED
    worker.intents["入库10个螺丝"] = Intent(intent="receipt", item="螺丝", qty=Decimal(10))
    assert "没有叫「螺丝」" in _say(worker, "入库10个螺丝")

    def boom(text):
        raise TimeoutError("AI_PROVIDER_TIMEOUT")

    worker.extract = boom
    assert _say(worker, "入库1000条桌腿", rid="x") == wm.REPLY_OFFLINE
    assert worker.executed_calls == [] and worker.pending == {}


def test_unauthorized_speaker_gets_nothing(worker):
    worker.intents["桌腿还剩多少"] = Intent(intent="query_stock", item="桌腿")
    assert _say(worker, "桌腿还剩多少", speaker="9") == wm.REPLY_NOT_AUTHORIZED
    assert _say(worker, "桌腿还剩多少", speaker="404") == wm.REPLY_NOT_AUTHORIZED


def test_handle_conversation_skips_echo_and_replays(worker):
    client = worker.client
    client.records["c1"] = [
        {"record_id": "a", "sequence": 1, "sender_user_id": "1", "content_type": "text", "content": "桌腿还剩多少"},
        {"record_id": "b", "sequence": 2, "sender_user_id": "100", "content_type": "text", "content": "380"},
    ]
    assert worker.handle_conversation("c1") is False  # 最新来信早于我上次回复
    client.records["c1"].append({"record_id": "c", "sequence": 3, "sender_user_id": "1", "content_type": "text", "content": "桌腿还剩多少"})
    worker.intents["桌腿还剩多少"] = Intent(intent="query_stock", item="桌腿")
    assert worker.handle_conversation("c1") is True
    assert client.sent[-1] == ("c1", "桌腿 380 条")
