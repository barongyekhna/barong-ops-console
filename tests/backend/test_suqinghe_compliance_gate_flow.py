"""独立站合规门(11-02)真库流程:建档被毙 → 合规卡 → 批 = 同意 / 驳 = 放行补发建档卡;没判成照常发建档卡;
同一个 1688 链接在合规卡等着时再丢进来 → 指向那张卡;找货初筛被毙 → F 候选标红、不取数据、不发选品卡;流水线先补判。integration。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.modules.agent_series.suqinghe import cards, compliance_gate, dossiers, pipeline
from backend.app.modules.agent_series.suqinghe.constants import CANDIDATE_CARD_KIND, DOSSIER_CARD_KIND
from backend.app.modules.agent_series.suqinghe.models import SqhCard, SqhDossier
from backend.app.modules.f_series.enrichment.models import FCategoryCandidate
from backend.app.services.data_isolation import without_org_data_isolation
from tests.backend.test_suqinghe_cards_api import people  # noqa: F401
from tests.backend.test_suqinghe_dossiers_api import T0, URL, _build, _build_approved, _fetch, _read, clean  # noqa: F401
from tests.backend.test_suqinghe_picks import _add, _amazon_ok, _candidate, _judge_picking, _keepa_ok, f_pool  # noqa: F401

pytestmark = pytest.mark.integration


def _verdict(status: str, *ids: str, category: str = "") -> dict[str, Any]:
    hits = [{"id": i, "text": compliance_gate.rule_text(i), "reason": f"{i} 测试理由"} for i in ids]
    return {"version": 1, "source": "1688", "judged_at": datetime.now(UTC).isoformat(), "status": status, "hits": hits, "outside": {"category": category, "reason": "清单外"} if status == "ask" else None, "calls": 1}


def _gate(verdict: dict[str, Any], seen: list[str] | None = None):
    def gate(db, facts: str) -> dict[str, Any]:
        if seen is not None:
            seen.append(facts)
        return verdict

    return gate


def _process(gate, now: datetime = T0) -> SqhDossier:
    with without_org_data_isolation(), SessionLocal() as db:
        return dossiers.process_next(db, now=now, fetch=_fetch, read=_read, build=_build, gate=gate)


def _enqueue(owner: int) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(owner), channel="c19")
        db.commit()


def _decide(ref: str, decision: str, owner: int, reason: str | None = None) -> dict[str, Any]:
    with without_org_data_isolation(), SessionLocal() as db:
        out = cards.decide_card(db, card_id=ref, decision=decision, actor=db.get(User, owner), channel="web", reason=reason)
        db.commit()
        return out.execution or {}


def _dossier(dossier_id: int) -> SqhDossier:
    with without_org_data_isolation(), SessionLocal() as db:
        d = db.get(SqhDossier, dossier_id)
        db.expunge(d)
        return d


def _card(ref: str) -> SqhCard:
    with without_org_data_isolation(), SessionLocal() as db:
        c = db.scalar(select(SqhCard).where(SqhCard.ref == ref))
        db.expunge(c)
        return c


def test_dropped_dossier_gets_a_gate_card_not_a_dossier_card_and_override_issues_it(clean) -> None:  # noqa: F811
    owner = clean["owner"]
    _enqueue(owner)
    seen: list[str] = []
    out = _process(_gate(_verdict("drop", "G05"), seen))
    assert out.status == compliance_gate.DOSSIER_DROPPED and out.card_ref
    assert seen and "中文标题" in seen[0]  # 门看的是档案读出来的资料
    card = _card(out.card_ref)
    assert card.kind == compliance_gate.GATE_CARD_KIND and card.status == "pending"
    assert "G05" in card.conclusion and "批 = 同意,不做" in card.conclusion and "驳 = 判错了、放行" in card.conclusion
    assert card.evidence["stage"] == "dossier" and card.evidence["gate"]["status"] == "drop"
    with without_org_data_isolation(), SessionLocal() as db:
        assert db.scalar(select(SqhCard).where(SqhCard.kind == DOSSIER_CARD_KIND)) is None  # 建档卡不发

    # 同一个链接再丢进来:不重抓,指向那张合规卡
    with without_org_data_isolation(), SessionLocal() as db, pytest.raises(dossiers.DossierError) as err:
        dossiers.enqueue(db, url=URL, actor_user_id=str(owner), channel="c19")
    assert out.card_ref in str(err.value) and "驳" in str(err.value)
    # 重新整理也不行:去卡上处理
    with without_org_data_isolation(), SessionLocal() as db, pytest.raises(dossiers.DossierError):
        dossiers.redo(db, dossier_id=out.id, actor=db.get(User, owner))

    # 老板驳 = 放行:档案 ready + 建档卡,放行和理由记在档案上
    execution = _decide(out.card_ref, "reject", owner, reason="这是工业用的,不是化妆品")
    assert execution["ok"] and "建档卡" in execution["note"]
    after = _dossier(out.id)
    assert after.status == "ready" and after.card_ref != out.card_ref
    gate = after.draft["compliance_gate"]
    assert gate["override"]["reason"] == "这是工业用的,不是化妆品" and compliance_gate.state(after.draft) == "override"
    dossier_card = _card(after.card_ref)
    assert dossier_card.kind == DOSSIER_CARD_KIND and "老板放行了" in dossier_card.conclusion
    # 放行后照常能批、建进 K
    assert _decide(after.card_ref, "approve", owner)["queued"] is True
    assert _build_approved()["ok"] is True


def test_boss_agrees_with_a_drop_and_an_ask_ends_dropped(clean) -> None:  # noqa: F811
    owner = clean["owner"]
    _enqueue(owner)
    out = _process(_gate(_verdict("ask", category="农药杀虫剂")))
    assert out.status == compliance_gate.DOSSIER_GATE_ASK
    # 等老板定的时候再丢同一个链接:当作还在处理
    with without_org_data_isolation(), SessionLocal() as db:
        again, created, _ = dossiers.enqueue(db, url=URL, actor_user_id=str(owner), channel="c19")
        assert not created and again.id == out.id
        assert "合规卡" in dossiers.queue_reply(0, created=False, status=again.status)
    execution = _decide(out.card_ref, "approve", owner)
    assert execution["ok"] and "不做" in execution["note"]
    after = _dossier(out.id)
    assert after.status == compliance_gate.DOSSIER_DROPPED and after.draft["compliance_gate"]["confirmed"]["card_ref"] == out.card_ref
    # 老板已经同意不做了,再丢这个链接 = 重新判一遍(不再挡着)
    with without_org_data_isolation(), SessionLocal() as db:
        _, created, _ = dossiers.enqueue(db, url=URL, actor_user_id=str(owner), channel="c19")
        db.commit()
        assert created


def test_passing_or_unjudged_dossiers_get_the_normal_dossier_card(clean) -> None:  # noqa: F811
    owner = clean["owner"]
    _enqueue(owner)
    ok = _process(_gate(_verdict("pass")))
    assert ok.status == "ready" and _card(ok.card_ref).kind == DOSSIER_CARD_KIND
    assert ok.draft["compliance_gate"]["status"] == "pass"
    with without_org_data_isolation(), SessionLocal() as db:
        db.get(SqhDossier, ok.id).status = "rejected"
        db.commit()
    _enqueue(owner)
    # 两单之间至少隔 60 秒(1688 节流),第二单放到 5 分钟后
    err = _process(_gate({"version": 1, "source": "1688", "judged_at": "x", "status": "error", "error": "Claude 额度用完,降级档判的不算数", "calls": 1}), now=T0 + timedelta(minutes=5))
    assert err.status == "ready"
    assert "合规门这次没判成" in _card(err.card_ref).conclusion  # 建进 K 后流水线第一步补判


def test_pick_shortlist_goes_through_the_gate_before_any_paid_lookup(f_pool) -> None:  # noqa: F811
    cid, other = _add([_candidate(), _candidate(source_url="https://detail.1688.com/offer/777000555.html", score=70)])
    looked_up: list[str] = []

    def shopping(db, query):
        looked_up.append(query)
        return {"query": query, "n": 12, "min": 12.99, "p25": 25.0, "median": 32.5, "p75": 40.0, "max": 80.0, "samples": [{"title": "x", "price": 32.5}]}

    order = [_verdict("drop", "G06"), _verdict("pass")]  # 她初筛留下的顺序就是 [cid, other]
    gate_calls: list[str] = []

    def counting_gate(db, facts):
        gate_calls.append(facts)
        return order[len(gate_calls) - 1]

    with without_org_data_isolation(), SessionLocal() as db:
        result = pipeline_free_run(db, judge=_judge_picking([cid, other]), shopping=shopping, gate=counting_gate)
    assert len(gate_calls) == 2 and "1688 标题" in gate_calls[0]
    assert looked_up == ["camping cookware set"]  # 被毙的那个没去查谷歌购物
    vetoed = [s for s in result["scored"] if s["vetoed"]]
    assert vetoed and vetoed[0]["f_candidate_id"] == cid and "G06" in vetoed[0]["vetoed"][0]
    with without_org_data_isolation(), SessionLocal() as db:
        row = db.get(FCategoryCandidate, UUID(cid))
        assert row.automation_blocked is True and row.status == "pending_review"  # 只标红、不替老板驳
        assert row.red_flags_json[-1]["type"] == "sqh_compliance_gate" and "G06" in row.red_flags_json[-1]["reason"]
        keys = [c.dedupe_key for c in db.scalars(select(SqhCard).where(SqhCard.kind == CANDIDATE_CARD_KIND))]
        assert keys == [f"candidate:{other}"]


def pipeline_free_run(db, *, judge, shopping, gate):
    from backend.app.modules.agent_series.suqinghe import picks

    return picks.run_picks(db, now=datetime.now(UTC), judge=judge, shopping=shopping, amazon=_amazon_ok, keepa=_keepa_ok, gate=gate)


def test_pipeline_products_built_before_the_gate_are_judged_first(clean, monkeypatch) -> None:  # noqa: F811
    owner = clean["owner"]
    _enqueue(owner)
    ready = _process(None)  # 合规门上线前的老档案:没有门的记录
    assert "compliance_gate" not in ready.draft
    _decide(ready.card_ref, "approve", owner)
    built = _build_approved()
    assert built["ok"]
    with without_org_data_isolation(), SessionLocal() as db:
        assert pipeline.pick(db) == (ready.id, "compliance_gate")
    monkeypatch.setattr(compliance_gate, "_default_call", lambda db, prompt: {**_sheet({"G02": True})})
    out = pipeline.run_step(ready.id, "compliance_gate")
    assert out["ok"] and "合规门不做" in out["note"]
    with without_org_data_isolation(), SessionLocal() as db:
        assert pipeline.pick(db) is None  # 停着等合规卡
        gate_card = db.scalar(select(SqhCard).where(SqhCard.kind == compliance_gate.GATE_CARD_KIND))
        assert gate_card.evidence["stage"] == "pipeline" and gate_card.status == "pending"
        gate_ref = gate_card.ref
    _decide(gate_ref, "reject", owner, reason="这不是医疗器械")
    with without_org_data_isolation(), SessionLocal() as db:
        assert pipeline.pick(db) == (ready.id, "material")  # 放行了,接着往下推


def _sheet(hits: dict[str, bool]) -> dict[str, Any]:
    sk = compliance_gate.skeleton()
    for r in sk["rules"]:
        r["reason"] = "理由"
        r["hit"] = bool(hits.get(r["id"]))
    sk["outside_list"] = {"reason": "清单外", "category": "", "hit": False}
    return sk
