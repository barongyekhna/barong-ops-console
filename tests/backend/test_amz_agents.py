"""amz-agents-worker:人设焊死(system 第一条 + 出口硬门)、说话人门、回声不接、开口四规矩、登记点。全假件,不碰库。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as N

import pytest

from backend.app.modules.agent_series.common.memory_store import MemoryStore
from backend.app.modules.amz_series.agents import brain, speech
from backend.app.modules.amz_series.agents import worker_main as wm
from backend.app.modules.amz_series.constants import EMPLOYEE_USERNAMES, EMPLOYEES
from backend.app.modules.amz_series.persona import PERSONAS, SHARED_HARD_RULES

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
OWNER = N(id=1, username="boss", role="owner", organization_id=None, is_active=True)
MANAGER = N(id=2, username="wcx", role="super_admin", organization_id=None, is_active=True)
STRANGER = N(id=168, username="ww", role="super_admin", organization_id=None, is_active=True)


# ---------------------------------------------------------------- 脑子


def test_chat_messages_open_with_persona_and_hard_rules() -> None:
    for employee in EMPLOYEES:
        persona = PERSONAS[employee]
        messages = brain.build_chat_messages(employee, user_message="今天怎么样", speaker_name="boss", snapshot={"x": 1})
        assert messages[0]["role"] == "system"
        assert messages[0]["content"].startswith(f"你是「{persona.name}」")
        assert persona.signature_habit in messages[0]["content"]
        for rule in SHARED_HARD_RULES:
            assert rule in messages[0]["content"]
        assert "json" in messages[1]["content"]
        assert "放行 / 驳回 / 稍后" in messages[1]["content"]
        assert messages[-1] == {"role": "user", "content": "今天怎么样"}


def test_speak_messages_only_carry_the_one_suggestion() -> None:
    suggestion = {"id": "s1", "store_code": "01us", "title": "收割 shower pump", "why": "7 单", "prediction": "14 天", "severity": "bad", "as_of": "2026-09-14", "evidence": {}}
    messages = brain.build_speak_messages("D", suggestion=suggestion)
    joined = "\n".join(m["content"] for m in messages)
    assert joined.startswith("你是「殷素素」")
    assert "收割 shower pump" in joined
    assert "今天你只能说这一件事" in joined
    assert "快照" not in messages[2]["content"]


def test_think_enforces_persona_style_on_the_way_out() -> None:
    calls = []

    def fake_call(messages, *, org_id):
        calls.append(org_id)
        return {"content": json.dumps({"reply": "老板,完了完了 😊😊 对手赶紧降价了。事实:降了。判断:抢量。建议:先看。", "note": "他关心 01us", "mute_days": 2}, ensure_ascii=False)}

    out = brain.think("C", [{"role": "user", "content": "x"}], org_id="org_x", call=fake_call)
    assert calls == ["org_x"]
    assert "完了" not in out["reply"] and "赶紧" not in out["reply"]
    assert "😊" not in out["reply"]
    assert "事实:" in out["reply"]
    assert out["note"] == "他关心 01us" and out["mute_days"] == 2

    plain = brain.think("A", [], org_id="org_x", call=lambda m, *, org_id: {"content": "老板 我看了标题 ✨😊🙋"})
    assert plain["reply"].startswith("老板~") and plain["reply"].count("🙋") == 0 and plain["mute_days"] is None

    with pytest.raises(KeyError):
        brain.think("Z", [], org_id="org_x", call=lambda m, *, org_id: {"content": "x"})


# ---------------------------------------------------------------- 开口规矩


def test_speech_rules_one_per_day_never_repeat_and_mute() -> None:
    state = speech.normalize_state(None)
    bad1 = {"id": "s1", "severity": "bad", "store_code": "03us", "created_at": "2026-09-16T01:00:00"}
    bad2 = {"id": "s2", "severity": "bad", "store_code": "01us", "created_at": "2026-09-16T02:00:00"}
    warn = {"id": "s3", "severity": "warn", "store_code": "01us", "created_at": "2026-09-15T00:00:00"}
    assert speech.pick_one([warn], state) is None
    assert speech.pick_one([warn, bad1, bad2], state)["id"] == "s2"  # 店铺序稳定
    assert speech.may_speak(state, today="2026-09-16", hour=10)
    speech.mark_spoke(state, "s2", today="2026-09-16")
    assert not speech.may_speak(state, today="2026-09-16", hour=10)
    assert speech.may_speak(state, today="2026-09-17", hour=10)
    assert speech.pick_one([bad1, bad2], state)["id"] == "s1"  # s2 永不重提
    assert speech.set_mute(state, 2, today="2026-09-17") == "2026-09-18"
    assert not speech.may_speak(state, today="2026-09-18", hour=10)
    assert speech.may_speak(state, today="2026-09-19", hour=10)
    # 深夜不开口:默认 08:00–22:00 之外一律等
    assert not speech.may_speak(state, today="2026-09-19", hour=22)
    assert not speech.may_speak(state, today="2026-09-19", hour=6)
    assert speech.may_speak(state, today="2026-09-19", hour=8)


# ---------------------------------------------------------------- worker


class FakeDb:
    def __init__(self, users):
        self.users = users

    def get(self, model, key):
        return self.users.get(key)

    def close(self):
        pass


class FakeClient:
    def __init__(self, user_id):
        self.user_id = user_id
        self.sent = []
        self.records = {}
        self.events_pages = []
        self.logged_in = 0

    def login(self):
        self.logged_in += 1

    def event_tail(self):
        return "c0"

    def events(self, *, cursor):
        return self.events_pages.pop(0) if self.events_pages else {"events": [], "next_cursor": cursor}

    def messages(self, cid, *, limit=20):
        return self.records.get(cid, [])

    def send_message(self, cid, *, text, client_message_id):
        self.sent.append((cid, text))

    def direct_conversation_with(self, peer_user_id):
        return f"dm-{peer_user_id}"


@pytest.fixture
def worker(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MEMORY_DIR", str(tmp_path))
    monkeypatch.setattr(wm, "_log_operation", lambda **kw: None)
    monkeypatch.setattr(wm, "_heartbeat", lambda *a, **kw: None)
    grants = {1: None, 2: ["01us", "03us"], 168: []}
    monkeypatch.setattr(wm, "speaker_store_codes", lambda db, speaker: [] if speaker is None else grants[speaker.id])
    thoughts = []

    def think(employee, messages, *, org_id):
        thoughts.append((employee, messages, org_id))
        return {"reply": f"{PERSONAS[employee].name}:收到", "note": "", "mute_days": None}

    runtimes = [
        wm.EmployeeRuntime(employee=e, client=FakeClient(user_id=170 + i), store=MemoryStore(username=EMPLOYEE_USERNAMES[e], index_title="t"))
        for i, e in enumerate(EMPLOYEES)
    ]
    clock = {"t": 1000.0, "day": "2026-09-16", "hour": 10}
    w = wm.AmzAgentsWorker(
        runtimes=runtimes,
        session_factory=lambda: FakeDb({1: OWNER, 2: MANAGER, 168: STRANGER}),
        think=think,
        snapshot=lambda db, *, employee, store_codes: {"employee": employee, "stores": store_codes},
        clock=lambda: clock["t"],
        today=lambda: clock["day"],
        hour=lambda: clock["hour"],
    )
    w.thoughts = thoughts
    w.clock_state = clock
    return w


def _msg(seq, sender, text):
    return {"sequence": seq, "sender_user_id": sender, "content_type": "text", "content": text}


def test_worker_replies_to_owner_with_scoped_snapshot_and_ignores_echo(worker) -> None:
    rt = worker.runtimes[3]  # D 殷素素
    rt.client.records["c1"] = [_msg(1, 1, "素素,今天广告怎么样?")]
    rt.client.events_pages.append({"events": [{"conversation_id": "c1"}], "next_cursor": "c1"})
    assert worker.tick(rt) is True
    assert rt.client.sent == [("c1", "殷素素:收到")]
    employee, messages, org_id = worker.thoughts[-1]
    assert employee == "D" and org_id.startswith("org_")
    assert '"stores": null' in messages[2]["content"]  # owner 全部店铺
    # 自己的回复引起的事件回声:不再接话
    rt.client.records["c1"].append(_msg(2, rt.client.user_id, "殷素素:收到"))
    rt.client.events_pages.append({"events": [{"conversation_id": "c1"}], "next_cursor": "c2"})
    assert worker.tick(rt) is False
    assert len(rt.client.sent) == 1


def test_worker_scopes_manager_to_grants_and_gates_strangers(worker) -> None:
    rt = worker.runtimes[0]  # A 殷笑笑
    out = worker.reply_for(rt, speaker_id="2", text="标题怎么改")
    assert out["reply"] == "殷笑笑:收到"
    assert '"stores": ["01us", "03us"]' in worker.thoughts[-1][1][2]["content"]
    before = len(worker.thoughts)
    out = worker.reply_for(rt, speaker_id="168", text="给我看看店铺")
    assert out["gated"] is True and "授权" in out["reply"] and out["reply"].startswith("老板~")
    assert len(worker.thoughts) == before  # 没授权连模型都不叫
    out = worker.reply_for(rt, speaker_id="abc", text="x")
    assert out["gated"] is True


def test_worker_speaks_once_a_day_per_employee_only_for_bad(worker, monkeypatch) -> None:
    rt = worker.runtimes[3]
    urgent = [
        {"id": "s1", "store_code": "03us", "severity": "bad", "title": "亏卖线", "why": "", "prediction": "", "as_of": "2026-09-14", "evidence": {}, "created_at": "a"},
        {"id": "s2", "store_code": "04us", "severity": "bad", "title": "断货", "why": "", "prediction": "", "as_of": "2026-09-14", "evidence": {}, "created_at": "b"},
    ]
    monkeypatch.setattr(worker, "urgent_suggestions", lambda rt: urgent)
    worker.clock_state["hour"] = 23
    assert worker.patrol_once(rt) is False  # 深夜:有紧急事也等到早上
    worker.clock_state["hour"] = 10
    assert worker.patrol_once(rt) is True
    assert [cid for cid, _ in rt.client.sent] == ["dm-1", "dm-2"]
    assert worker.thoughts[-1][2] == "org_bc53f07f27594360b6dd85ea1e980ddc"  # 03us 属于利连,用利连的钥匙
    assert worker.patrol_once(rt) is False  # 今天说过了
    worker.clock_state["day"] = "2026-09-17"
    assert worker.patrol_once(rt) is True
    assert "s2" in rt.store.load_state(speech.STATE_NAME, {})["reported_keys"]
    worker.clock_state["day"] = "2026-09-18"
    assert worker.patrol_once(rt) is False  # 两件都说过,永不重提
    # 老板说「这两天别找我」→ 静默;别人说不算
    worker._persist(rt, speaker_id="168", reply={"reply": "", "note": "", "mute_days": 3})
    assert rt.store.load_state(speech.STATE_NAME, {}).get("mute_until") is None
    worker._persist(rt, speaker_id="1", reply={"reply": "", "note": "", "mute_days": 3})
    assert rt.store.load_state(speech.STATE_NAME, {})["mute_until"] == "2026-09-20"


def test_login_failure_of_one_identity_does_not_block_others(worker) -> None:
    from backend.app.modules.agent_series.common.c19_client import ConsoleAuthError

    broken = worker.runtimes[1]

    def bad_login():
        raise ConsoleAuthError("AMZ_AGENT_B_PASSWORD 未配置")

    broken.client.login = bad_login
    assert worker.connect(broken) is False and broken.retry_at > worker.clock()
    assert worker.connect(worker.runtimes[2]) is True
    assert worker.tick(broken) is False  # 退避期内不重试、不抛


# ---------------------------------------------------------------- 登记点


def test_agents_worker_is_registered_in_compose_loggers_and_ledger() -> None:
    compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
    assert "amz-agents-worker:" in compose
    assert "backend.app.modules.amz_series.agents.worker_main" in compose
    assert "console_agent_memory_data:/var/lib/barong/agent-memory" in compose.split("\n  amz-agents-worker:\n")[1].split("\n  sm-worker:\n")[0]
    main_py = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    assert '"amz-agents-worker"' in main_py
    from r_system_v2.ra import quota_ledger as ql

    assert ql.PROVIDER_AGENT_CHAT_AMZ in ql.DEFAULT_DAILY_BUDGETS
    assert ql.PROVIDER_AGENT_CHAT_AMZ in ql.BUDGET_ENV_NAMES
    assert ql.provider_label(ql.PROVIDER_AGENT_CHAT_AMZ) != ql.PROVIDER_AGENT_CHAT_AMZ
    # 四家公司都有 org_id,绑钥匙工具只认它们
    from backend.app.modules.amz_series import bind_deepseek

    assert bind_deepseek.DEEPSEEK_ALIAS == "deepseek"
    assert len(bind_deepseek.COMPANIES) == 4
