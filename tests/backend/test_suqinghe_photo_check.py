"""她先看图再决定问不问「无标货」「实拍图」(10-31 老板拍板:1688 多是白牌,不是每个都问)。unit,不连库、不出网。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.app.modules.agent_series.suqinghe import photo_check, pricing, seller_chat
from tests.backend.test_suqinghe_seller_chat import FakeDb, FakeDossier

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)
GOOD = [{"name_zh": "黑", "cost_price_cny": 10, "weight_g": 200}, {"name_zh": "红", "cost_price_cny": 10, "weight_g": 260}]
NONE = [{"name_zh": "黑", "cost_price_cny": 10}, {"name_zh": "红", "cost_price_cny": 10}]


@pytest.fixture(autouse=True)
def _switch_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SQH_SELLER_CHAT", "1")


def _lines(variants):
    return pricing.cost_lines(variants, pricing.assumptions())


def _audit(branded: bool | None, all_renders: bool | None, brand_text: str = "") -> dict[str, Any]:
    return {"photo_audit": {"branded": branded, "all_renders": all_renders, "brand_text": brand_text, "attempts": 1}}


# ---------------------------------------------------------------- 看图


def test_summarize_branding_on_any_image_and_renders_only_when_none_is_real() -> None:
    assert photo_check.summarize([]) == {"branded": None, "all_renders": None, "brand_text": ""}
    assert photo_check.summarize([{"ok": False}]) ["branded"] is None
    real_clean = [{"ok": True, "real_photo": True, "branding": False}, {"ok": True, "real_photo": False, "branding": False}]
    assert photo_check.summarize(real_clean) == {"branded": False, "all_renders": False, "brand_text": ""}
    renders = [{"ok": True, "real_photo": False, "branding": True, "brand_text": "XINDA"}, {"ok": True, "real_photo": False, "branding": False}]
    assert photo_check.summarize(renders) == {"branded": True, "all_renders": True, "brand_text": "XINDA"}
    # 只看成一张效果图不下「全是效果图」的结论
    assert photo_check.summarize([{"ok": True, "real_photo": False, "branding": False}])["all_renders"] is False


def test_audit_reads_at_most_five_and_a_failed_look_is_not_neutral() -> None:
    calls: list[bytes] = []

    def reader(db, prompt, image):
        calls.append(image)
        return {"real_photo": True, "branding": image == b"b"}

    urls = [f"https://cbu01.alicdn.com/{i}.jpg" for i in range(7)]
    got = photo_check.audit(FakeDb(), urls, download=lambda u: b"b" if u.endswith("1.jpg") else b"x", reader=reader, now=NOW)
    assert len(calls) == photo_check.MAX_IMAGES and got["branded"] is True and got["all_renders"] is False and got["attempts"] == 1
    # 额度降级 / 下不来:没看成 → branded None(不是 False),带 error,下轮再看,最多 3 次
    down = photo_check.audit(FakeDb(), urls[:2], download=lambda u: b"x", reader=lambda db, p, i: {"_ai_degraded": True}, now=NOW)
    assert down["branded"] is None and "额度" in down["error"]
    assert not photo_check.done({"photo_audit": {**down, "attempts": 2}}) and photo_check.done({"photo_audit": {**down, "attempts": 3}})
    assert photo_check.topics({"photo_audit": down}) == {"neutral": False, "photos": False}
    bad = photo_check.audit(FakeDb(), urls[:1], download=lambda u: None, reader=reader, now=NOW)
    assert bad["branded"] is None and bad["images"][0]["error"] == "图下不来"


def test_ensure_writes_the_result_back_once(monkeypatch: pytest.MonkeyPatch) -> None:
    dossier = FakeDossier({"reference_images": ["https://cbu01.alicdn.com/a.jpg", "https://cbu01.alicdn.com/b.jpg"]})
    out = photo_check.ensure(FakeDb(), dossier, download=lambda u: b"x", reader=lambda db, p, i: '{"real_photo": false, "branding": false}')
    assert out["all_renders"] is True and dossier.draft["photo_audit"]["all_renders"] is True
    # 看成了就不再看(不再花钱)
    assert photo_check.ensure(FakeDb(), dossier, download=lambda u: pytest.fail("不该再下图"), reader=None) is out


# ---------------------------------------------------------------- 什么时候问、问什么


def test_ask_plan_only_asks_what_the_pictures_call_for() -> None:
    # 白牌 + 有实拍 + 重量齐:不问(老板:1688 大多白牌,不用每个都问)
    assert seller_chat.ask_plan(_audit(False, False), _lines(GOOD), now=NOW) is None
    # 没看过图:也不问(看不成不当无标,但也不凭空问)
    assert seller_chat.ask_plan({}, _lines(GOOD), now=NOW) is None
    why, topics = seller_chat.ask_plan(_audit(True, False, "XINDA"), _lines(GOOD), now=NOW)
    assert topics == {"weights": False, "neutral": True, "photos": False} and "牌子" in why and "XINDA" in why
    why, topics = seller_chat.ask_plan(_audit(False, True), _lines(GOOD), now=NOW)
    assert topics == {"weights": False, "neutral": False, "photos": True} and "实拍" in why
    # 本来要问重量:顺带加
    why, topics = seller_chat.ask_plan(_audit(True, True), _lines(NONE), now=NOW)
    assert topics == {"weights": True, "neutral": True, "photos": True} and "没有重量尺寸" in why
    # 老板驳回再问重量时,无标/实拍问过就不再问
    draft = {**_audit(True, True), "seller_chat": {"status": "answered", "requested": True, "photo_topics_asked": True}}
    assert seller_chat.ask_plan(draft, _lines(GOOD), now=NOW)[1] == {"weights": True, "neutral": False, "photos": False}
    # 开关关:什么都不问
    import os

    os.environ["SQH_SELLER_CHAT"] = "0"
    try:
        assert seller_chat.ask_plan(_audit(True, True), _lines(NONE), now=NOW) is None
    finally:
        os.environ["SQH_SELLER_CHAT"] = "1"


def test_questions_use_the_boss_wording_word_for_word() -> None:
    v = [{"name_zh": "黑"}, {"name_zh": "红"}]
    # 只问重量:和 10-29 的原模板一字不差
    assert seller_chat.build_question(v, {"weights": True}) == seller_chat.build_question(v) == (
        "您好,我是跨境卖家,想确认一下:黑、红 每个的实际包装重量(克)、包装尺寸(长宽高 cm)、一箱装几个?谢谢。"
    )
    assert seller_chat.build_question(v, {"neutral": True}) == "您好,我是跨境卖家,想确认一下:能发没有印字、没有 logo 的中性货和中性包装吗？谢谢。"
    assert seller_chat.build_question(v, {"photos": True}) == "您好,我是跨境卖家,想确认一下:方便发几张产品实拍照片吗？手机随手拍就行，不要效果图。谢谢。"
    both = seller_chat.build_question(v, {"weights": True, "neutral": True, "photos": True})
    assert both == (
        "您好,我是跨境卖家,想确认一下:1.黑、红 每个的实际包装重量(克)、包装尺寸(长宽高 cm)、一箱装几个?"
        "2.能发没有印字、没有 logo 的中性货和中性包装吗？3.方便发几张产品实拍照片吗？手机随手拍就行，不要效果图。谢谢。"
    )
    many = seller_chat.build_question([{"name_zh": f"规格{i}号超长名字" * 3} for i in range(60)], {"weights": True, "neutral": True, "photos": True})
    assert len(many) <= seller_chat.QUESTION_MAX and many.endswith("不要效果图。谢谢。")


def test_only_a_weight_question_holds_the_price_card() -> None:
    assert seller_chat.pending({"seller_chat": {"status": "asked"}})  # 老底账:问的是重量
    assert not seller_chat.pending({"seller_chat": {"status": "asked", "topics": {"neutral": True}}})
    assert seller_chat.pending({"seller_chat": {"status": "asked", "topics": {"weights": True, "photos": True}}})


# ---------------------------------------------------------------- 回复


def _asked(topics: dict[str, bool]) -> dict[str, Any]:
    asked = NOW - timedelta(minutes=30)
    return {
        "variants": [{"name_zh": "黑", "cost_price_cny": 10}, {"name_zh": "红", "cost_price_cny": 10}],
        "seller_chat": {"status": "asked", "asked_at": asked.isoformat(), "checked_at": asked.isoformat(), "im_url": "https://air.1688.com/x",
                        "question": "您好…", "baseline": [], "topics": topics},
        "pipeline": {"price": {"card_ref": "ab12"}},
    }


def test_neutral_only_reply_is_recorded_as_seller_said_and_never_touches_the_price_card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seller_chat.cards, "find_card", lambda db, ref: pytest.fail("只问无标货不碰价格卡"))
    dossier = FakeDossier(_asked({"weights": False, "neutral": True, "photos": False}))
    out = seller_chat.poll_one(FakeDb(), dossier, now=NOW, read=lambda **kw: [{"self": False, "nick": "卖家", "time": "t", "text": "可以的,中性包装没问题"}],
                               judge=lambda db, p: {"answers": [], "neutral_goods": "yes", "neutral_quote": "可以的,中性包装没问题"})
    assert out == "answered"
    neutral = dossier.draft["neutral_goods"]
    assert neutral["value"] == "yes" and neutral["source"] == "seller_said" and neutral["note"] == "卖家口头" and "中性包装" in neutral["quote"]
    # 没说到:接着等,不追问
    dossier = FakeDossier(_asked({"weights": False, "neutral": True, "photos": False}))
    out = seller_chat.poll_one(FakeDb(), dossier, now=NOW, read=lambda **kw: [{"self": False, "nick": "卖家", "time": "t", "text": "亲在的"}],
                               judge=lambda db, p: {"answers": [], "neutral_goods": "not_answered"})
    assert out == "unclear" and dossier.draft["seller_chat"]["status"] == "asked" and "neutral_goods" not in dossier.draft


def test_photos_sent_back_are_kept_for_the_image_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    pic = tmp_path / "p1.jpg"
    pic.write_bytes(b"\xff\xd8not-really-a-jpeg")
    dossier = FakeDossier(_asked({"weights": False, "neutral": False, "photos": True}))
    out = seller_chat.poll_one(FakeDb(), dossier, now=NOW,
                               read=lambda **kw: [{"self": False, "nick": "卖家", "time": "t", "text": "", "images": [{"url": "https://x/1.jpg", "path": str(pic)}]}],
                               judge=lambda db, p: {"answers": []}, image_reader=lambda db, p, seg: {"text": "", "useful": False})
    assert out == "answered" and dossier.draft["seller_chat"]["seller_photos"] == [str(pic)]


def test_weight_and_neutral_together(monkeypatch: pytest.MonkeyPatch) -> None:
    class Card:
        status = "pending"

    monkeypatch.setattr(seller_chat.cards, "find_card", lambda db, ref: Card())
    monkeypatch.setattr(seller_chat.cards, "retire", lambda db, card, *, reason: True)
    dossier = FakeDossier(_asked({"weights": True, "neutral": True, "photos": False}))
    # 只回了无标、没给重量:记下无标,重量接着等
    out = seller_chat.poll_one(FakeDb(), dossier, now=NOW, read=lambda **kw: [{"self": False, "nick": "卖家", "time": "t", "text": "能发中性的"}],
                               judge=lambda db, p: {"answers": [], "neutral_goods": "yes"})
    assert out == "unclear" and dossier.draft["neutral_goods"]["value"] == "yes" and dossier.draft["seller_chat"]["status"] == "asked"
    dossier.draft["seller_chat"]["checked_at"] = (NOW - timedelta(minutes=30)).isoformat()
    out = seller_chat.poll_one(FakeDb(), dossier, now=NOW, read=lambda **kw: [{"self": False, "nick": "卖家", "time": "t2", "text": "黑 350 克,红 420 克"}],
                               judge=lambda db, p: {"answers": [{"key": "v1", "weight_g": 350}, {"key": "v2", "weight_g": 420}], "neutral_goods": "not_answered"})
    assert out == "answered" and dossier.draft["variants"][0]["weight_g"] == 350.0 and dossier.draft["neutral_goods"]["value"] == "yes"
