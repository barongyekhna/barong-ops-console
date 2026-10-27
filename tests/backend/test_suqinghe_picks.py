"""第⑥步:她自己找货(从 F 的候选池里挑)。

验收不看实现:池子只给能开页面、没踩红线、不在她手上的候选;一天几张、攒多了不发;
批 = F 候选 approved + 同一个链接排队建档 → 建进 K 后 F 候选 imported_to_k;驳 = F 候选 rejected 带原因;
老板在 F 页面上先处理过的,卡作废。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.modules.agent_series.suqinghe import cards, dossiers, picks
from backend.app.modules.agent_series.suqinghe.constants import CANDIDATE_CARD_KIND, DOSSIER_CARD_KIND
from backend.app.modules.agent_series.suqinghe.models import SqhCard, SqhDossier
from backend.app.modules.f_series.enrichment.models import FCategoryCandidate
from backend.app.services.data_isolation import without_org_data_isolation
from tests.backend.test_suqinghe_cards_api import OWNER, _login, people  # noqa: F401 —— 同一套人
from tests.backend.test_suqinghe_dossiers_api import OFFER, T0, URL, _build_approved, _process, clean  # noqa: F401

pytestmark = pytest.mark.integration

PREFIX = "sqh-pick-test"
CATEGORY = "Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Cookware & Dinnerware"


def _candidate(**over: Any) -> FCategoryCandidate:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "category_id": "1016",
        "category_path": CATEGORY,
        "title": f"{PREFIX} 户外套锅组合露营炊具",
        "source": "alibaba1688",
        "source_url": URL,
        "image_url": "https://cbu01.alicdn.com/img/ibank/test.jpg",
        "price_cny": Decimal("25.00"),
        "moq": 1,
        "status": "pending_review",
        "automation_blocked": False,
        "score": 80,
        "score_json": {"moq": 1, "monthly_sales": 300, "total": 80},
        "profile_product_zh": "野营炊具套装",
        "profile_product_en": "Camping Cookware Set",
    }
    fields.update(over)
    return FCategoryCandidate(**fields)


@pytest.fixture
def f_pool(clean):  # noqa: F811
    def wipe():
        with without_org_data_isolation(), SessionLocal() as db:
            db.execute(delete(FCategoryCandidate).where(FCategoryCandidate.title.like(f"{PREFIX}%")))
            db.commit()

    wipe()
    yield clean
    wipe()


def _add(rows: list[FCategoryCandidate]) -> list[str]:
    with without_org_data_isolation(), SessionLocal() as db:
        db.add_all(rows)
        db.commit()
        return [str(r.id) for r in rows]


def _f(cid: str) -> FCategoryCandidate:
    with without_org_data_isolation(), SessionLocal() as db:
        row = db.get(FCategoryCandidate, cid)
        db.expunge(row)
        return row


def _judge_picking(ids: list[str], *, query: str = "camping cookware set"):
    def judge(db, ask, extra):
        assert "候选:" in extra and "店里已有的品" in extra and "老板对之前选品卡的决定" in extra
        return {"picks": [{"id": cid, "reason": "起订 1、月销 300,轻小件。", "risks": ["铝材质要核实是否阳极氧化"], "us_query": query} for cid in ids]}

    return judge


def _shopping_ok(db, query):
    return {"query": query, "n": 12, "min": 9.99, "p25": 15.0, "median": 22.5, "p75": 29.0, "max": 60.0, "samples": [{"title": "x", "price": 22.5}]}


# ---------------------------------------------------------------- 池子和解析


def test_pool_only_gives_openable_unflagged_untaken_candidates(f_pool) -> None:
    good, short, flagged, taken = _add(
        [
            _candidate(),
            _candidate(source_url="https://s.click.1688.com/abc"),
            _candidate(source_url="https://detail.1688.com/offer/777000111.html", automation_blocked=True),
            _candidate(source_url="https://detail.1688.com/offer/777000222.html"),
        ]
    )
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url="https://detail.1688.com/offer/777000222.html", actor_user_id=str(f_pool["owner"]), channel="web")
        db.commit()
    with without_org_data_isolation(), SessionLocal() as db:
        ids = {str(r.id) for r in picks.pool(db) if r.title.startswith(PREFIX)}
    assert ids == {good}, (ids, short, flagged, taken)


def test_pool_caps_each_category(f_pool) -> None:
    _add([_candidate(source_url=f"https://detail.1688.com/offer/7780001{i:02d}.html", score=90 - i) for i in range(5)])
    with without_org_data_isolation(), SessionLocal() as db:
        scores = [r.score for r in picks.pool(db, per_category=2) if r.title.startswith(PREFIX)]
    assert scores == [90, 89]


def test_parse_picks_only_trusts_pool_ids_and_clean_queries() -> None:
    a, b = str(uuid4()), str(uuid4())
    result = {
        "picks": [
            {"id": a, "reason": "好", "risks": ["带电"], "us_query": "Best Camping Pot 2026"},
            {"id": "not-in-pool", "reason": "x", "us_query": "camping pot"},
            {"id": a, "reason": "重复", "us_query": "camping pot"},
            {"id": b, "reason": "也好", "risks": [], "us_query": "camping cookware"},
        ]
    }
    out = picks.parse_picks(result, pool_ids={a, b}, limit=5, fallback_query={a: "Camping Cookware Set"})
    assert [p.f_candidate_id for p in out] == [a, b]
    assert out[0].us_query == "camping cookware set"  # 夸张词的查询不要,用画像英文名顶上
    assert out[0].risks == ("带电",)
    assert out[1].us_query == "camping cookware"
    assert len(picks.parse_picks(result, pool_ids={a, b}, limit=1)) == 1
    assert picks.parse_picks({"content": "not json"}, pool_ids={a}, limit=3) == []


def test_card_text_reads_like_a_person_and_holds_the_weight_question() -> None:
    row = _candidate()
    pick = picks.Pick(f_candidate_id=str(row.id), reason="起订 1,轻。", risks=("带磁",), us_query="camping cookware set")
    text = picks.build_card_text(row, pick, _shopping_ok(None, "camping cookware set"), picks.pricing.assumptions())
    assert text["title"].startswith("选品:")
    assert "¥25.0" in text["conclusion"] and "$3.47" in text["conclusion"] and "中位 $22.5" in text["conclusion"]
    assert "重量" in text["why"] and "风险:带磁" in text["why"]
    assert text["evidence"]["offer_id"] == OFFER and text["evidence"]["recheck"] == {"type": CANDIDATE_CARD_KIND, "f_candidate_id": str(row.id)}
    assert "samples" not in text["evidence"]["competitors"]
    assert text["confidence"] == "medium"  # 中位 22.5 / 进价 3.47 ≈ 6.5 倍,但有一条风险 → 中
    no_risk = picks.Pick(f_candidate_id=str(row.id), reason="", risks=(), us_query="")
    assert picks.build_card_text(row, no_risk, {"query": "", "n": 0}, picks.pricing.assumptions())["confidence"] == "medium"
    assert picks.confidence_for(goods_usd=3.47, median=22.5, risks=0) == "high"
    assert picks.confidence_for(goods_usd=10.0, median=20.0, risks=0) == "low"


# ---------------------------------------------------------------- 挑一轮


def test_run_picks_makes_cards_once_per_candidate_within_daily_quota(f_pool, monkeypatch) -> None:
    monkeypatch.setenv("SQH_PICKS_PER_DAY", "1")
    now = datetime.now(UTC)  # 卡的 created_at 是库里的 now(),「今天」要按真实时间算
    cid, other = _add([_candidate(), _candidate(source_url="https://detail.1688.com/offer/777000333.html", score=70)])
    with without_org_data_isolation(), SessionLocal() as db:
        first = picks.run_picks(db, now=now, judge=_judge_picking([cid, other]), shopping=_shopping_ok)
        again = picks.run_picks(db, now=now, judge=_judge_picking([other]), shopping=_shopping_ok)
        card = db.scalar(select(SqhCard).where(SqhCard.kind == CANDIDATE_CARD_KIND))
        assert first["cards"] == [card.ref] and first["skipped"] is None
        assert again == {"cards": [], "skipped": "today_done"}  # 一天的量到了
        assert card.status == "pending" and card.dedupe_key == f"candidate:{cid}"
        assert card.evidence["f_candidate_id"] == cid and card.evidence["competitors"]["median"] == 22.5
        assert card.evidence["us_query"] == "camping cookware set"
        assert card.data_fingerprint  # 老板在 F 页面上先处理了就作废
        # 第二天:同一个候选不再发(dedupe),另一个能发
        tomorrow = picks.run_picks(db, now=now + timedelta(days=1), judge=_judge_picking([cid, other]), shopping=_shopping_ok)
        refs = [c.ref for c in db.scalars(select(SqhCard).where(SqhCard.kind == CANDIDATE_CARD_KIND).order_by(SqhCard.id))]
        assert tomorrow["cards"] == refs[1:] and len(refs) == 2


def test_run_picks_stops_when_boss_has_too_many_pending(f_pool, monkeypatch) -> None:
    monkeypatch.setenv("SQH_PICKS_MAX_PENDING", "1")
    cid, other = _add([_candidate(), _candidate(source_url="https://detail.1688.com/offer/777000444.html")])
    now = datetime.now(UTC)
    with without_org_data_isolation(), SessionLocal() as db:
        assert picks.run_picks(db, now=now, judge=_judge_picking([cid]), shopping=_shopping_ok)["cards"]
        assert picks.run_picks(db, now=now + timedelta(days=1), judge=_judge_picking([other]), shopping=_shopping_ok) == {"cards": [], "skipped": "pending_full"}


def test_run_picks_nothing_worth_and_judge_failure_are_logged_not_raised(f_pool) -> None:
    _add([_candidate()])
    with without_org_data_isolation(), SessionLocal() as db:
        assert picks.run_picks(db, now=T0, judge=lambda db, ask, extra: {"picks": []}, shopping=_shopping_ok) == {"cards": [], "skipped": "nothing_worth"}

        def boom(db, ask, extra):
            raise RuntimeError("model down")

        assert picks.run_picks(db, now=T0, judge=boom, shopping=_shopping_ok) == {"cards": [], "skipped": "judge_failed"}
        assert db.scalar(select(SqhCard).where(SqhCard.kind == CANDIDATE_CARD_KIND)) is None


def test_should_pick_only_after_todays_morning_plan() -> None:
    today = T0.astimezone(picks.dossiers.LA).date()
    assert picks.should_pick(now=T0, last_plan=today)
    assert not picks.should_pick(now=T0, last_plan=today - timedelta(days=1))
    assert not picks.should_pick(now=T0, last_plan=None)


# ---------------------------------------------------------------- 批 / 驳 / 建进 K


def _pick_one(f_pool, **over: Any) -> tuple[str, str]:
    (cid,) = _add([_candidate(**over)])
    with without_org_data_isolation(), SessionLocal() as db:
        out = picks.run_picks(db, now=T0, judge=_judge_picking([cid]), shopping=_shopping_ok)
    return cid, out["cards"][0]


def test_approve_queues_the_same_link_as_a_dossier_and_k_build_marks_f_imported(f_pool) -> None:
    cid, ref = _pick_one(f_pool)
    with without_org_data_isolation(), SessionLocal() as db:
        outcome = cards.decide_card(db, card_id=ref, decision="approve", actor=db.get(User, f_pool["owner"]), channel="web")
        db.commit()
        assert outcome.changed and outcome.execution["ok"] and outcome.execution["queued"]
        dossier = db.scalar(select(SqhDossier).where(SqhDossier.offer_id == OFFER))
        assert dossier.status == "queued" and dossier.capture["f_candidate_id"] == cid and dossier.capture["pick_card_ref"] == ref
    assert _f(cid).status == "approved" and "批了" in _f(cid).notes
    # 第①步照旧:整理 → 建档卡 → 批 → 建进 K → F 候选记上去向
    ready = _process(T0)
    assert ready.status == "ready" and ready.card_ref
    with without_org_data_isolation(), SessionLocal() as db:
        card = cards.find_card(db, ready.card_ref)
        assert card.kind == DOSSIER_CARD_KIND
        cards.decide_card(db, card_id=card.ref, decision="approve", actor=db.get(User, f_pool["owner"]), channel="web")
        db.commit()
    built = _build_approved()
    assert built and built["ok"], built
    row = _f(cid)
    assert row.status == "imported_to_k" and str(row.k_product_id) == built["k_product_id"]


def test_reject_marks_f_rejected_with_the_reason(f_pool) -> None:
    cid, ref = _pick_one(f_pool)
    with without_org_data_isolation(), SessionLocal() as db:
        outcome = cards.decide_card(db, card_id=ref, decision="reject", actor=db.get(User, f_pool["owner"]), channel="c19", reason="套锅已经有两款了")
        db.commit()
        assert outcome.execution == {"ok": True, "note": "好,这个不做了,原因我记住了。"}
        assert db.scalar(select(SqhDossier).where(SqhDossier.offer_id == OFFER)) is None
    row = _f(cid)
    assert row.status == "rejected" and "套锅已经有两款了" in row.notes


def test_card_goes_stale_when_boss_already_handled_it_on_the_f_page(f_pool) -> None:
    cid, ref = _pick_one(f_pool)
    with without_org_data_isolation(), SessionLocal() as db:
        row = db.get(FCategoryCandidate, cid)
        row.status = "rejected"
        db.commit()
    with without_org_data_isolation(), SessionLocal() as db:
        outcome = cards.decide_card(db, card_id=ref, decision="approve", actor=db.get(User, f_pool["owner"]), channel="web")
        db.commit()
        assert outcome.card.status == "stale" and outcome.execution is None
        assert db.scalar(select(SqhDossier).where(SqhDossier.offer_id == OFFER)) is None
    assert _f(cid).status == "rejected"


def test_card_image_goes_through_f_image_cache(f_pool, auth_client: TestClient, monkeypatch) -> None:
    from backend.app.modules.f_series.enrichment import images as f_images

    cid, ref = _pick_one(f_pool)
    seen: dict[str, Any] = {}

    def fake(candidate_id, image_url, variant):
        seen.update(candidate_id=candidate_id, image_url=image_url, variant=variant)
        return b"\xff\xd8\xff\xdbfake", "image/jpeg"

    monkeypatch.setattr(f_images, "get_candidate_image", fake)
    _login(auth_client, OWNER)
    response = auth_client.get(f"/api/app/suqinghe/cards/{ref}/image")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("image/jpeg") and response.content.startswith(b"\xff\xd8")
    assert seen == {"candidate_id": cid, "image_url": "https://cbu01.alicdn.com/img/ibank/test.jpg", "variant": "thumb"}
    assert auth_client.get("/api/app/suqinghe/cards/zzzz/image").status_code == 404
