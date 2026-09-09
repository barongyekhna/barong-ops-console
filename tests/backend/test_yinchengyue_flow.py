"""殷承岳的常驻流程:只答最新一条、不答自己、同一条只答一次、闲聊不调模型、脑子掉线有话说。全假件,不碰库。"""

from __future__ import annotations

import pytest

from backend.app.modules.agent_series.common.memory_store import MemoryStore
from backend.app.modules.agent_series.yinchengyue import worker_main as wm
from backend.app.modules.agent_series.yinchengyue.classifier import Candidate, CategoryVerdict
from backend.app.modules.agent_series.yinchengyue.reply import REPLY_CHITCHAT, REPLY_NEED_DETAIL, REPLY_OFFLINE

pytestmark = pytest.mark.unit

LEAF = Candidate(id="1014", name="Camping Cookware", full_path="Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Cookware", name_zh="露营炊具", level=4, is_leaf=True)


class FakeDb:
    closed = 0

    def close(self):
        FakeDb.closed += 1


class FakeClient:
    user_id = 200

    def __init__(self):
        self.sent = []
        self.records = {}
        self.events_pages = []

    def messages(self, cid, *, limit=20):
        return self.records.get(cid, [])

    def send_message(self, cid, *, text, client_message_id):
        assert client_message_id.startswith("ycy-")
        self.sent.append((cid, text))

    def events(self, *, cursor=None):
        return self.events_pages.pop(0) if self.events_pages else {"events": [], "next_cursor": cursor}


def _rec(seq, sender, content, *, kind="text", rid=None):
    return {"sequence": seq, "sender_user_id": sender, "content_type": kind, "content": content, "record_id": rid or f"r{seq}"}


@pytest.fixture
def worker(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MEMORY_DIR", str(tmp_path))
    store = MemoryStore(username="yinchengyue", index_title="t")
    logs = []
    monkeypatch.setattr(wm, "_log_operation", lambda **kw: logs.append(kw))
    verdicts = {}
    classify_calls = []

    def classify(db, text):
        classify_calls.append(text)
        return verdicts.get(text, CategoryVerdict(status="none"))

    w = wm.YinchengyueWorker(client=FakeClient(), store=store, session_factory=FakeDb, classify=classify, clock=lambda: 0.0)
    w.verdicts = verdicts
    w.classify_calls = classify_calls
    w.logs = logs
    return w


def test_answers_latest_incoming_only_once_and_marks_before_send(worker):
    worker.verdicts["露营炊具套装"] = CategoryVerdict(status="ok", chosen=LEAF, path=["Sporting Goods", "Camping Cookware"], confidence="high", reason_zh="户外炉具", shortlist_size=9)
    worker.client.records["c1"] = [_rec(1, 7, "老问题"), _rec(2, 7, "露营炊具套装", rid="r-ask")]
    assert worker.handle_conversation("c1") is True
    cid, text = worker.client.sent[-1]
    assert cid == "c1" and text.startswith("【类目 #") and "Camping Cookware" in text
    assert worker.classify_calls == ["露营炊具套装"]  # 只答最新的那条,老问题不追答
    assert "r-ask" in worker.answered and worker.store.load_state("answered", []) == ["r-ask"]
    answer_log = [l for l in worker.logs if l["action"] == "agent.category.answer"][-1]
    assert answer_log["details"]["chosen_id"] == "1014" and answer_log["details"]["confidence"] == "high"
    # 同一条消息再来一次(事件重放)→ 不再答
    assert worker.handle_conversation("c1") is False
    assert len(worker.client.sent) == 1


def test_skips_when_my_reply_is_already_the_latest(worker):
    worker.client.records["c1"] = [_rec(1, 7, "保温杯"), _rec(2, 200, "【类目 #ab12】Thermoses")]
    assert worker.handle_conversation("c1") is False
    assert worker.classify_calls == []
    worker.client.records["c2"] = [_rec(1, 7, "照片", kind="image"), _rec(2, 7, "文件", kind="file")]
    assert worker.handle_conversation("c2") is False


def test_chitchat_does_not_touch_the_model(worker):
    worker.client.records["c1"] = [_rec(1, 7, "你好")]
    assert worker.handle_conversation("c1") is True
    assert worker.client.sent[-1][1] == REPLY_CHITCHAT
    assert worker.classify_calls == []
    assert worker.logs[-1]["action"] == "agent.chat.reply" and worker.logs[-1]["details"]["kind"] == "chitchat"


def test_none_and_offline_verdicts_have_plain_text_replies(worker):
    worker.verdicts["一个东西"] = CategoryVerdict(status="none", shortlist_size=0)
    worker.verdicts["太阳能露营灯"] = CategoryVerdict(status="offline", error="extract: TimeoutError()")
    worker.client.records["c1"] = [_rec(1, 7, "一个东西", rid="r-vague")]
    worker.client.records["c2"] = [_rec(1, 8, "太阳能露营灯", rid="r-lamp")]
    worker.handle_conversation("c1")
    worker.handle_conversation("c2")
    assert worker.client.sent[0][1] == REPLY_NEED_DETAIL
    assert worker.client.sent[1][1] == REPLY_OFFLINE
    actions = [(l["action"], l["result"]) for l in worker.logs]
    assert ("agent.category.none", "success") in actions
    assert ("agent.category.answer", "failure") in actions
    assert FakeDb.closed >= 2  # 每次判定的会话都关掉了


def test_run_once_dedupes_conversations_and_advances_cursor(worker):
    worker.verdicts["保温杯"] = CategoryVerdict(status="ok", chosen=LEAF, path=["x"], confidence="low", reason_zh="")
    worker.client.records["c1"] = [_rec(1, 7, "保温杯")]
    worker.client.events_pages = [{"events": [{"conversation_id": "c1"}, {"conversation_id": "c1"}, {"conversation_id": "c9"}], "next_cursor": "cur-2"}]
    assert worker.run_once() is True
    assert worker.cursor == "cur-2"
    assert len(worker.client.sent) == 1  # c1 两条事件只处理一次;c9 没消息不发
    assert worker.run_once() is False
