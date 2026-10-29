"""她去问卖家重量尺寸(10-29,B 期)的纯逻辑:什么时候该问、问句模板、卖家回复怎么抽成数、写回规格怎么标「卖家口头」、
旺旺页在浏览器线程里怎么发怎么读(假 page/frame)。unit,不连库、不出网、不起 Chromium。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from backend.app.modules.agent_series.suqinghe import browser, pricing, seller_chat
from tests.backend.test_suqinghe_browser import Clock, FakeContext, FakePage, FakeStore, _wait

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 29, 20, 0, tzinfo=UTC)  # 洛杉矶 10-29 13:00


@pytest.fixture(autouse=True)
def _switch_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SQH_SELLER_CHAT", "1")


def _lines(variants):
    return pricing.cost_lines(variants, pricing.assumptions())


# ---------------------------------------------------------------- 什么时候问


def test_needs_ask_follows_the_boss_rule_only_when_the_page_is_untrustworthy() -> None:
    good = [{"name_zh": "黑", "cost_price_cny": 10, "weight_g": 200}, {"name_zh": "红", "cost_price_cny": 10, "weight_g": 260}]
    assert seller_chat.needs_ask({}, _lines(good), now=NOW) is None  # 页面可信:不问
    none = [{"name_zh": "黑", "cost_price_cny": 10}, {"name_zh": "红", "cost_price_cny": 10}]
    assert "没有重量尺寸" in seller_chat.needs_ask({}, _lines(none), now=NOW)
    same = [{"name_zh": "黑", "cost_price_cny": 10, "weight_g": 500}, {"name_zh": "红", "cost_price_cny": 10, "weight_g": 500}]
    assert "疑似乱填" in seller_chat.needs_ask({}, _lines(same), now=NOW)
    partial = [{"name_zh": "黑", "cost_price_cny": 10, "weight_g": 200}, {"name_zh": "红", "cost_price_cny": 10}]
    assert "没写重量" in seller_chat.needs_ask({}, _lines(partial), now=NOW)
    # 在等回复 / 今天问过 / 已回 / 超时 / 没发成:自动不再问;老板驳回点名重量 → 再问一次
    assert seller_chat.needs_ask({"seller_chat": {"status": "asked"}}, _lines(none), now=NOW) is None
    assert seller_chat.needs_ask({"seller_chat": {"asked_day": "2026-10-29"}}, _lines(none), now=NOW) is None
    for status in ("answered", "timeout", "failed"):
        assert seller_chat.needs_ask({"seller_chat": {"status": status}}, _lines(none), now=NOW) is None
    assert "老板" in seller_chat.needs_ask({"seller_chat": {"status": "answered", "requested": True}}, _lines(good), now=NOW)
    assert seller_chat.boss_wants_weight("绿色的重量不对,再问问") and not seller_chat.boss_wants_weight("绿色卖 19.99")


def test_switch_off_never_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQH_SELLER_CHAT", "0")
    assert seller_chat.needs_ask({}, _lines([{"name_zh": "黑", "cost_price_cny": 10}]), now=NOW) is None


def test_question_is_the_fixed_template_and_stays_under_the_wangwang_limit() -> None:
    q = seller_chat.build_question([{"name_zh": "黑色 2000mAh"}, {"name_zh": "红色 4000mAh"}])
    assert q == "您好,我是跨境卖家,想确认一下:黑色 2000mAh、红色 4000mAh 每个的实际包装重量(克)、包装尺寸(长宽高 cm)、一箱装几个?谢谢。"
    many = seller_chat.build_question([{"name_zh": f"规格{i}号超长名字" * 3} for i in range(60)])
    assert len(many) <= seller_chat.QUESTION_MAX and "等共 60 个规格" in many and many.endswith("谢谢。")
    assert seller_chat.build_question([]) == "您好,我是跨境卖家,想确认一下:每个的实际包装重量(克)、包装尺寸(长宽高 cm)、一箱装几个?谢谢。"


# ---------------------------------------------------------------- 回复 → 数 → 规格


def test_parse_answers_keeps_only_sane_numbers_for_known_variants() -> None:
    variants = [{"name_zh": "黑"}, {"name_zh": "红"}]
    data = {
        "answers": [
            {"key": "v1", "weight_g": 350, "dims_cm": [12, 8, 6], "units_per_carton": 50},
            {"key": "v2", "weight_g": 0, "dims_cm": [12, 8], "units_per_carton": "abc"},
            {"key": "v3", "weight_g": 100},
            {"key": "v2", "dims_cm": ["10", "7.5", "5"]},
        ]
    }
    assert seller_chat.parse_answers(data, variants) == {"v1": {"weight_g": 350.0, "dims_cm": [12.0, 8.0, 6.0], "units_per_carton": 50}, "v2": {"dims_cm": [10.0, 7.5, 5.0]}}
    assert seller_chat.parse_answers({"answers": [], "unclear": True}, variants) == {} and seller_chat.parse_answers(None, variants) == {}


def test_apply_answers_marks_seller_said_and_pricing_never_treats_it_as_evidence() -> None:
    variants = [{"name_zh": "黑", "cost_price_cny": 10, "weight_g": 500}, {"name_zh": "红", "cost_price_cny": 10, "weight_g": 500}]
    changed = seller_chat.apply_answers(variants, {"v1": {"weight_g": 350.0, "dims_cm": [12.0, 8.0, 6.0]}, "v2": {"weight_g": 420.0}}, asked_at="2026-10-29T20:00:00+00:00")
    assert changed == 2
    assert variants[0]["source"] == "seller_said" and variants[0]["weight_source_note"] == "卖家口头" and variants[0]["dims_cm"] == [12.0, 8.0, 6.0]
    lines = _lines(variants)
    assert [line.weight_g for line in lines] == [350.0, 420.0]
    assert all(line.weight_note == pricing.SELLER_SAID_NOTE for line in lines)  # 卡上写明「口头说的,没有凭证」
    assert seller_chat.needs_ask({"seller_chat": {"status": "answered"}}, lines, now=NOW) is None
    # 卖家口头说的每个都一样也不算「乱填」(那是页面数据的判定)
    same = [{"name_zh": "黑", "cost_price_cny": 10, "weight_g": 300, "source": "seller_said"}, {"name_zh": "红", "cost_price_cny": 10, "weight_g": 300, "source": "seller_said"}]
    assert not any("乱填" in line.weight_note for line in _lines(same))


def test_new_replies_ignore_our_own_messages_and_what_was_already_there() -> None:
    baseline = [{"nick": "湖南来美电子", "time": "2026-10-29 03:11:12", "text": "亲在吗"}]
    messages = [
        {"self": True, "nick": "无敌小巴龙", "time": "2026-10-29 21:00:00", "text": "您好,我是跨境卖家…"},
        {"self": False, "nick": "湖南来美电子", "time": "2026-10-29 03:11:12", "text": "亲在吗"},
        {"self": False, "nick": "湖南来美电子", "time": "2026-10-29 21:05:00", "text": "2000mAh 的 350 克,一箱 50 个"},
        {"self": False, "nick": "湖南来美电子", "time": "2026-10-29 21:05:01", "text": ""},
    ]
    assert seller_chat.new_replies(messages, baseline) == [{"nick": "湖南来美电子", "time": "2026-10-29 21:05:00", "text": "2000mAh 的 350 克,一箱 50 个"}]
    assert browser.im_url("湖南来美电子", "643348607768") == (
        "https://air.1688.com/app/ocms-fusion-components-1688/def_cbu_web_im/index.html?touid=cnalichn%E6%B9%96%E5%8D%97%E6%9D%A5%E7%BE%8E%E7%94%B5%E5%AD%90&siteid=cnalichn&status=1&offerId=643348607768"
    )


# ---------------------------------------------------------------- 落库那一段(假 db / 假档案)


class FakeDb:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0

    def add(self, row: Any) -> None:
        self.added.append(row)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass


class FakeDossier:
    def __init__(self, draft: dict[str, Any]) -> None:
        self.id, self.offer_id, self.source_url, self.draft = 7, "643348607768", "https://detail.1688.com/offer/643348607768.html", draft


def test_poll_one_waits_then_writes_the_answers_back_and_retires_the_price_card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQH_SELLER_CHAT_POLL_MINUTES", "15")
    asked = NOW - timedelta(minutes=20)
    draft = {
        "variants": [{"name_zh": "黑", "cost_price_cny": 10}, {"name_zh": "红", "cost_price_cny": 10}],
        "seller_chat": {"status": "asked", "asked_at": asked.isoformat(), "checked_at": asked.isoformat(), "im_url": "https://air.1688.com/x", "question": "您好…", "baseline": []},
        "pipeline": {"price": {"card_ref": "ab12"}},
    }
    dossier, db = FakeDossier(draft), FakeDb()
    assert seller_chat.due(draft["seller_chat"], now=NOW) and not seller_chat.due(draft["seller_chat"], now=asked + timedelta(minutes=5))
    # 没回:只记下看过的时间,继续等
    assert seller_chat.poll_one(db, dossier, now=NOW, read=lambda **kw: [{"self": True, "nick": "我", "time": "t", "text": "您好…"}], judge=lambda db, p: {}) == "no_reply"
    assert dossier.draft["seller_chat"]["status"] == "asked" and dossier.draft["seller_chat"]["checked_at"] == NOW.isoformat()
    # 回了但没说到数:继续等
    chat = dossier.draft["seller_chat"]
    chat["checked_at"] = asked.isoformat()
    assert seller_chat.poll_one(db, dossier, now=NOW, read=lambda **kw: [{"self": False, "nick": "卖家", "time": "t2", "text": "亲要多少件?"}], judge=lambda db, p: {"answers": [], "unclear": True}) == "unclear"
    assert dossier.draft["seller_chat"]["status"] == "asked" and dossier.draft["seller_chat"]["replies"][0]["text"] == "亲要多少件?"
    # 回了数:写回规格、作废旧价格卡
    retired: list[str] = []

    class Card:
        status = "pending"

    monkeypatch.setattr(seller_chat.cards, "find_card", lambda db, ref: Card() if ref == "ab12" else None)
    monkeypatch.setattr(seller_chat.cards, "retire", lambda db, card, *, reason: retired.append(reason) or True)
    prompts: list[str] = []

    def judge(db, prompt):
        prompts.append(prompt)
        return '{"answers": [{"key": "v1", "weight_g": 350, "units_per_carton": 50}, {"key": "v2", "weight_g": 420, "dims_cm": [12, 8, 6]}]}'

    dossier.draft["seller_chat"]["checked_at"] = asked.isoformat()
    out = seller_chat.poll_one(db, dossier, now=NOW, read=lambda **kw: [{"self": False, "nick": "卖家", "time": "t3", "text": "黑的 350 克一箱 50,红的 420 克 12×8×6"}], judge=judge)
    assert out == "answered"
    chat = dossier.draft["seller_chat"]
    assert chat["status"] == "answered" and chat["answers"]["v1"]["weight_g"] == 350.0
    assert dossier.draft["variants"][0]["source"] == "seller_said" and dossier.draft["variants"][1]["dims_cm"] == [12.0, 8.0, 6.0]
    assert retired == ["卖家回了重量尺寸,按新数重出"] and "v1: 黑" in prompts[0] and "黑的 350 克" in prompts[0]


def test_poll_one_times_out_after_the_wait_and_the_card_goes_out_as_usual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQH_SELLER_CHAT_WAIT_HOURS", "24")
    draft = {"variants": [], "seller_chat": {"status": "asked", "asked_at": (NOW - timedelta(hours=25)).isoformat(), "checked_at": (NOW - timedelta(hours=1)).isoformat()}}
    dossier = FakeDossier(draft)
    assert seller_chat.poll_one(FakeDb(), dossier, now=NOW, read=lambda **kw: pytest.fail("超时了不该再开旺旺")) == "timeout"
    assert dossier.draft["seller_chat"]["status"] == "timeout"
    assert seller_chat.needs_ask(dossier.draft, _lines([{"name_zh": "黑", "cost_price_cny": 10}]), now=NOW) is None


def test_ask_consumes_the_ledger_and_refunds_when_sending_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    ledger: list[str] = []
    import r_system_v2.ra.quota_ledger as ql

    monkeypatch.setattr(ql, "try_consume", lambda db, provider, *, amount=1: ledger.append(f"+{provider}"))
    monkeypatch.setattr(ql, "refund", lambda db, provider, *, amount=1: ledger.append(f"-{provider}"))
    draft = {"variants": [{"name_zh": "黑", "cost_price_cny": 10}], "supplier": {"name": "湖南来美电子科技有限公司"}}
    dossier, db = FakeDossier(draft), FakeDb()
    sent: list[dict[str, Any]] = []

    def send(**kw):
        sent.append(kw)
        return {"ok": True, "im_url": "https://air.1688.com/x", "login_id": "湖南来美电子", "dump": "/d", "messages": [{"self": True, "nick": "我", "time": "t", "text": kw["text"]}]}

    chat = seller_chat.ask(db, dossier, _lines(draft["variants"]), why="详情页没有重量尺寸", now=NOW, send=send)
    assert ledger == ["+sqh_1688_im"] and sent[0]["login_id"] is None and sent[0]["offer_id"] == "643348607768" and sent[0]["text"].startswith("您好,我是跨境卖家")
    assert chat["status"] == "asked" and chat["asked_day"] == "2026-10-29" and chat["baseline"][0]["text"] == sent[0]["text"]
    assert dossier.draft["supplier"]["login_id"] == "湖南来美电子"  # 从商品页找到的卖家账号记回档案
    assert seller_chat.pending(dossier.draft)

    def fail(**kw):
        raise browser.SellerChatError("点了发送,消息列表里没出现这一条", detail={"dump": "/d2"})

    dossier2 = FakeDossier({"variants": [{"name_zh": "黑", "cost_price_cny": 10}]})
    with pytest.raises(browser.SellerChatError):
        seller_chat.ask(db, dossier2, _lines(dossier2.draft["variants"]), why="x", now=NOW, send=fail)
    assert ledger[-2:] == ["+sqh_1688_im", "-sqh_1688_im"]
    assert dossier2.draft["seller_chat"]["status"] == "failed" and dossier2.draft["seller_chat"]["dump"] == "/d2"


# ---------------------------------------------------------------- 浏览器线程里的旺旺动作(假 page / frame)


class FakeFrame:
    def __init__(self, page: "FakePage", url: str) -> None:
        self.page, self.url, self.name = page, url, ""
        self.typed = ""
        self.messages: list[dict[str, Any]] = [{"self": False, "nick": "卖家", "time": "t0", "text": "亲在吗"}]
        self.clicks: list[str] = []
        self.ready = True

    def wait_for_selector(self, selector: str, timeout: int = 0) -> None:
        if not self.ready:
            raise TimeoutError(selector)

    def click(self, selector: str) -> None:
        self.clicks.append(selector)
        if selector == browser.IM_SELECTORS["send"] and self.typed:
            self.messages.append({"self": True, "nick": "我", "time": "t1", "text": self.typed})
            self.typed = ""

    def locator(self, selector: str) -> Any:
        frame = self

        class Loc:
            def inner_text(self) -> str:
                return frame.typed

        return Loc()

    def evaluate(self, script: str) -> Any:
        return list(self.messages)

    def content(self) -> str:
        return "<html></html>"


class ImPage(FakePage):
    """像真页面:开商品页能找到卖家账号;开旺旺地址后出现 im_core 的 iframe;键盘打字落进 iframe 的输入框。"""

    def __init__(self) -> None:
        super().__init__()
        self.im_frame: FakeFrame | None = None
        self.seller_id: str | None = "湖南来美电子"

        page = self

        class KB:
            def type(self, text: str, delay: int = 0) -> None:
                page.log.append(("type", text))
                if page.im_frame:
                    page.im_frame.typed += text

            def press(self, key: str) -> None:
                page.log.append(("press", key))

        self.keyboard = KB()

    def goto(self, url: str, **kwargs: Any) -> None:
        super().goto(url, **kwargs)
        if browser.IM_PAGE in url:
            self.im_frame = FakeFrame(self, url.replace("def_cbu_web_im/", "def_cbu_web_im_core/"))
            self.frames = [self, self.im_frame]
            self._title = "1688旺旺聊天"

    def evaluate(self, script: str) -> Any:
        return self.seller_id if "sellerLoginId" in script else self._text


@pytest.fixture
def im_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(browser, "browser_dump_dir", lambda: str(tmp_path))
    page = ImPage()
    ctx = FakeContext(page)
    store = FakeStore()
    sess = browser.BrowserSession(store=store, launcher=lambda: ctx, clock=Clock(), detect_blocked=lambda **kw: None)
    sess.start()
    try:
        yield sess, page, ctx, store, tmp_path
    finally:
        sess.stop_flag.set()
        sess.join(timeout=3)


def test_browser_asks_the_seller_in_wangwang_and_reads_the_thread_back(im_session) -> None:
    sess, page, ctx, store, tmp = im_session
    out = sess.ask_seller(offer_url="https://detail.1688.com/offer/643348607768.html", login_id=None, offer_id="643348607768", text="您好,我是跨境卖家,想确认一下:黑 每个的实际包装重量(克)?谢谢。", dossier_id=7)
    assert out["ok"] and out["login_id"] == "湖南来美电子" and out["im_url"] == browser.im_url("湖南来美电子", "643348607768")
    assert [e for e in page.log if e[0] == "goto"] == [("goto", "https://detail.1688.com/offer/643348607768.html"), ("goto", out["im_url"])]  # 没有 login_id 先开商品页找
    assert page.im_frame.clicks == [browser.IM_SELECTORS["input"], browser.IM_SELECTORS["send"]]
    assert out["messages"][-1]["self"] and out["messages"][-1]["text"].startswith("您好,我是跨境卖家")
    assert (Path(out["dump"]) / "before-send.png").exists() and (Path(out["dump"]) / "after-send.png").exists()  # 发前发后各留一张底
    assert sess.status == "idle" and [s["status"] for s in store.states][-2:] == ["asking_seller", "idle"]
    # 读回复:卖家回了一条
    page.im_frame = None
    page.frames = [page]
    original_goto = page.goto

    def goto(url: str, **kw: Any) -> None:
        original_goto(url, **kw)
        page.im_frame.messages.append({"self": False, "nick": "卖家", "time": "t2", "text": "350 克"})

    page.goto = goto
    msgs = sess.read_seller_chat(im_url=out["im_url"])
    assert msgs[-1] == {"self": False, "nick": "卖家", "time": "t2", "text": "350 克"} and sess.status == "idle"


def test_browser_holds_for_the_boss_when_wangwang_wants_a_login(im_session) -> None:
    sess, page, ctx, store, tmp = im_session
    original_goto = page.goto

    def goto(url: str, **kw: Any) -> None:
        original_goto(url, **kw)
        page.url = "https://login.1688.com/member/signin.htm?redirect=" + url
        page.frames = [page]
        page.im_frame = None

    page.goto = goto
    with pytest.raises(browser.SellerChatBlocked):
        sess.ask_seller(offer_url="https://detail.1688.com/offer/1.html", login_id="湖南来美电子", offer_id="1", text="您好", dossier_id=None)
    assert sess.status == "needs_human" and "要登录" in (sess.reason or "")
    assert ("type", "您好") not in page.log  # 没登录就什么都没发
