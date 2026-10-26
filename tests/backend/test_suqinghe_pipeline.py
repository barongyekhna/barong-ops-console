"""苏青禾接管 K 流水线(10-26):真库 integration。

建档走真的(和档案测试同一套桩),K 的 AI 调用一律打桩:这里验的是她按 K 的状态一步步往下推、
失败两次停手发卡、老板批/驳之后接着干或停下、她的判断原样交给 K。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, select

from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.modules.agent_series.suqinghe import cards, k_ops, material, pipeline
from backend.app.modules.agent_series.suqinghe.models import SqhCard, SqhDossier
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeAttribute,
    KProductKnowledgeProduct,
    KProductKnowledgeWorkflowExecution,
)
from backend.app.services.data_isolation import without_org_data_isolation
from tests.backend.test_suqinghe_cards_api import people  # noqa: F401 —— 同一套人
from tests.backend.test_suqinghe_dossiers_api import T0, URL, _build_approved, _process, clean  # noqa: F401
from tests.fixtures.organization_fixtures import DEFAULT_TEST_ORG_DB_ID

pytestmark = pytest.mark.integration

ALL_READABLE = {"product", "worker", "key", "goal", "content", "approvals"}


@pytest.fixture
def built(clean):  # noqa: F811
    """一个批过、建进 K 的产品。返回 (档案号, K 产品 id, 老板 id)。"""
    from backend.app.modules.agent_series.suqinghe import dossiers

    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
    ready = _process(T0)
    with without_org_data_isolation(), SessionLocal() as db:
        cards.decide_card(db, card_id=ready.card_ref, decision="approve", actor=db.get(User, clean["owner"]), channel="web")
        db.commit()
    outcome = _build_approved()
    assert outcome and outcome["ok"], outcome
    yield ready.id, outcome["k_product_id"], clean["owner"]
    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(delete(KProductKnowledgeWorkflowExecution).where(KProductKnowledgeWorkflowExecution.product_id == outcome["k_product_id"]))
        db.execute(delete(SqhCard).where(SqhCard.kind == pipeline.BLOCKED_CARD_KIND))
        db.commit()


def _pick() -> tuple[int, str] | None:
    with without_org_data_isolation(), SessionLocal() as db:
        return pipeline.pick(db)


def _pipe(dossier_id: int) -> dict[str, Any]:
    with without_org_data_isolation(), SessionLocal() as db:
        return dict((db.get(SqhDossier, dossier_id).draft or {}).get("pipeline") or {})


def _decide(ref: str, decision: str, owner_id: int, reason: str | None = None) -> dict[str, Any]:
    with without_org_data_isolation(), SessionLocal() as db:
        out = cards.decide_card(db, card_id=ref, decision=decision, actor=db.get(User, owner_id), channel="web", reason=reason)
        db.commit()
        return out.execution or {}


def test_two_failures_stop_and_the_boss_decides(built, monkeypatch: pytest.MonkeyPatch) -> None:
    dossier_id, _, owner = built
    assert _pick() == (dossier_id, "material")

    def broken(ctx):
        raise pipeline.StepError("图床挂了")

    monkeypatch.setitem(pipeline.STEPS, "material", broken)
    first = pipeline.run_step(dossier_id, "material")
    assert first["ok"] is False and first["blocked"] is False
    assert _pick() == (dossier_id, "material")  # 一次失败:下一轮再试
    second = pipeline.run_step(dossier_id, "material")
    assert second["blocked"] is True
    assert _pick() is None  # 停手,等老板

    with without_org_data_isolation(), SessionLocal() as db:
        card = db.scalar(select(SqhCard).where(SqhCard.ref == second["card_ref"]))
        assert card.kind == pipeline.BLOCKED_CARD_KIND and card.status == "pending"
        assert "收卖点素材" in card.title and "图床挂了" in card.why
        # 早间对账只管计划出的卡,不会把「卡住」卡当旧卡作废
        cards.settle_issues(db, live=set(), readable=ALL_READABLE, today="2026-11-01")
        db.commit()
        assert db.get(SqhCard, card.id).status == "pending"

    assert "再试一次" in _decide(second["card_ref"], "approve", owner)["note"]
    assert _pick() == (dossier_id, "material")
    assert "material" not in (_pipe(dossier_id).get("failures") or {})

    pipeline.run_step(dossier_id, "material")
    again = pipeline.run_step(dossier_id, "material")
    assert "先不做" in _decide(again["card_ref"], "reject", owner, reason="这个品不要了")["note"]
    assert _pick() is None
    assert _pipe(dossier_id)["stopped"]["reason"] == "这个品不要了"


def test_material_lands_in_k_as_evidence_and_hype_waits_for_the_boss(built, monkeypatch: pytest.MonkeyPatch) -> None:
    dossier_id, product_id, _ = built
    summary = material.summarize(
        {
            "facts": [
                {"text": "LED 照明灯", "kind": "feature", "subject": "this", "confidence": "high", "image_index": 0, "segment_index": 0},
                {"text": "小巧便携", "kind": "claim", "subject": "this", "confidence": "medium", "image_index": 0, "segment_index": 1},
                {"text": "秒杀同类", "kind": "hype", "subject": "this", "confidence": "high", "image_index": 1, "segment_index": 0},
            ]
        }
    )
    monkeypatch.setattr(material, "collect", lambda db, capture, **kw: {**summary, "read_at": "t", "version": material.MATERIAL_VERSION})
    out = pipeline.run_step(dossier_id, "material")
    assert out["ok"], out
    with without_org_data_isolation(), SessionLocal() as db:
        rows = db.scalars(select(KProductKnowledgeAttribute).where(KProductKnowledgeAttribute.product_id == product_id).order_by(KProductKnowledgeAttribute.attribute_key)).all()
        assert [(r.attribute_key, r.attribute_value_text, r.source) for r in rows] == [
            ("sqh_claim_01", "小巧便携", material.MATERIAL_SOURCE),
            ("sqh_feature_01", "LED 照明灯", material.MATERIAL_SOURCE),
        ]
        draft = db.get(SqhDossier, dossier_id).draft
        assert [r["text"] for r in draft["material"]["hype"]] == ["秒杀同类"]
    assert _pick() == (dossier_id, "keywords")

    # 素材规则升级后重读:旧的那几行先删掉,不留下一半旧一半新
    newer = material.summarize({"facts": [{"text": "Type-C 充电", "kind": "feature", "subject": "this", "confidence": "high", "image_index": 0, "segment_index": 0}]})
    monkeypatch.setattr(material, "collect", lambda db, capture, **kw: {**newer, "read_at": "t2", "version": material.MATERIAL_VERSION})
    assert pipeline.run_step(dossier_id, "material")["ok"]
    with without_org_data_isolation(), SessionLocal() as db:
        rows = db.scalars(select(KProductKnowledgeAttribute).where(KProductKnowledgeAttribute.product_id == product_id)).all()
        assert [(r.attribute_key, r.attribute_value_text) for r in rows if r.source == material.MATERIAL_SOURCE] == [("sqh_feature_01", "Type-C 充电")]


def _plant_execution(product_id: str, **fields: Any) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        db.add(
            KProductKnowledgeWorkflowExecution(
                product_id=product_id,
                organization_name="test",
                workspace_key=DEFAULT_TEST_ORG_DB_ID,
                business_context="independent_store",
                scope_mode="production",
                target_market="US",
                trace_json=[],
                execution_gate_logs_json=[],
                **fields,
            )
        )
        db.commit()


def test_keywords_then_risk_review_hand_her_judgement_to_k(built, monkeypatch: pytest.MonkeyPatch) -> None:
    dossier_id, product_id, _ = built
    with without_org_data_isolation(), SessionLocal() as db:
        dossier = db.get(SqhDossier, dossier_id)
        dossier.draft = {
            **dossier.draft,
            "material": {"features": [], "claims": [], "hype": [], "version": material.MATERIAL_VERSION},
        }
        db.commit()
    answers = iter(
        [
            {"main_keyword": "squishy stress toy", "seed_keywords": ["squishy toys", "stress relief toy"], "reason": "品类词"},
            {"decisions": [{"term": "Squishmallows dumpling", "decision": "approve"}, {"term": "squishy dumpling toy", "decision": "approve", "reason": "就是它"}]},
        ]
    )
    monkeypatch.setattr(pipeline, "_judge", lambda db, ask, brief, extra, **kw: next(answers))
    started: dict[str, Any] = {}

    def fake_start(self, product_uuid, *, main_keyword, seed_keywords):
        started.update(main_keyword=main_keyword, seed_keywords=seed_keywords, actor=self.actor.username, org=self.org_id)
        _plant_execution(
            str(product_uuid),
            status="blocked",
            current_step="risk_term_review_manual",
            claude_filter_result_json={"risk_keywords": [{"term": "Squishmallows dumpling", "reason": "竞品商标"}, {"term": "squishy dumpling toy", "reason": "泛词"}]},
            error_report_json={"code": "RISK_REVIEW_REQUIRED"},
        )

    monkeypatch.setattr(k_ops.KHands, "start_keywords", fake_start)
    out = pipeline.run_step(dossier_id, "keywords")
    assert out["ok"] and "2 个等我判" in out["note"], out
    assert started == {"main_keyword": "squishy stress toy", "seed_keywords": ["squishy toys", "stress relief toy"], "actor": "sqh_test_owner", "org": DEFAULT_TEST_ORG_DB_ID}
    assert _pipe(dossier_id)["main_keyword"] == "squishy stress toy"
    assert _pick() == (dossier_id, "risk_review")

    reviewed: dict[str, Any] = {}
    monkeypatch.setattr(k_ops.KHands, "review_risk", lambda self, pid, *, execution_id, decisions: reviewed.update(decisions=decisions))
    out = pipeline.run_step(dossier_id, "risk_review")
    assert out["ok"], out
    # 模型两个都说留;K 说第一个是竞品商标 → 不管模型怎么说都不用
    assert [(d["term"], d["decision"]) for d in reviewed["decisions"]] == [("Squishmallows dumpling", "reject"), ("squishy dumpling toy", "approve")]
    assert all(d["reason"].startswith("苏青禾:") for d in reviewed["decisions"])
    assert _pipe(dossier_id)["risk"]["decisions"] == reviewed["decisions"]


def test_price_card_then_apply_variants_prices_and_shipping(built, monkeypatch: pytest.MonkeyPatch) -> None:
    """价格卡:她算、老板批;批了她才去 K 里改成多变体、填价、选运费模板。驳了按老板的话重出一张。"""
    from backend.app.modules.agent_series.suqinghe import pricing
    from backend.app.modules.p_series.upload.assemble import gate_blockers
    from backend.app.modules.w_series.shipping.models import WShippingClass

    dossier_id, product_id, owner = built
    variants = [
        {"name_zh": "黑色", "name_en": "Black", "cost_price_cny": 20.0, "weight_g": 200.0, "dims_cm": [10.0, 8.0, 6.0]},
        {"name_zh": "绿色", "name_en": "Green", "cost_price_cny": 20.0, "weight_g": None, "dims_cm": None},
    ]
    with without_org_data_isolation(), SessionLocal() as db:
        dossier = db.get(SqhDossier, dossier_id)
        dossier.draft = {**dossier.draft, "variants": variants, "pipeline": {"main_keyword": "squishy stress toy"}}
        if not db.scalar(select(WShippingClass).where(WShippingClass.slug == pricing.DEFAULT_SHIPPING_CLASS)):
            db.add(WShippingClass(slug=pricing.DEFAULT_SHIPPING_CLASS, name="中国直发-标准线", zone_rates_json=[], origin="cn_direct"))
        db.commit()
    shops: list[str] = []
    monkeypatch.setattr(pricing, "fetch_shopping", lambda db, *, query, org_id: shops.append(query) or {"query": query, "n": 5, "min": 8.99, "p25": 11.99, "median": 14.99, "p75": 17.99, "max": 24.99, "samples": []})
    asks: list[str] = []

    def judge(db, ask, brief, extra, **kw):
        asks.append(extra)
        return {"variants": [{"key": "v1", "include": True, "price": 1.0, "label_en": "Black", "axis": "color"}, {"key": "v2", "include": True, "price": 15.99, "label_en": "Green", "axis": "color"}], "questions": [], "summary": "按颜色"}

    monkeypatch.setattr(pipeline, "_judge", judge)
    out = pipeline.run_step(dossier_id, "price_card")
    assert out["ok"], out
    ref = _pipe(dossier_id)["price"]["card_ref"]
    with without_org_data_isolation(), SessionLocal() as db:
        card = db.scalar(select(SqhCard).where(SqhCard.ref == ref))
        lines = {line["label_en"]: line for line in card.evidence["variants"]}
        assert card.kind == pipeline.PRICE_CARD_KIND and card.status == "pending"
        assert lines["Black"]["price"] == lines["Black"]["floor"] > 1.0  # 模型给 $1 → 抬到保底价
        assert lines["Green"]["price"] == 15.99 and "没写这个规格的重量" in lines["Green"]["weight_note"]
        assert shops == ["squishy stress toy"]

    # 驳回:下一张价格卡带着老板的话去问模型
    assert "重算" in _decide(ref, "reject", owner, reason="绿色卖 19.99")["note"]
    assert pipeline.run_step(dossier_id, "price_card")["ok"]
    assert "绿色卖 19.99" in asks[-1]
    ref2 = _pipe(dossier_id)["price"]["card_ref"]
    assert ref2 != ref

    assert "改变体" in _decide(ref2, "approve", owner)["note"]
    out = pipeline.run_step(dossier_id, "apply_price")
    assert out["ok"], out
    with without_org_data_isolation(), SessionLocal() as db:
        product = db.get(KProductKnowledgeProduct, product_id)
        assert product.product_type == "variable_product"
        rows = k_ops.variant_rows(db, product_id)
        assert sorted((v.color, float(v.price_override)) for v in rows) == sorted([("Black", lines["Black"]["floor"]), ("Green", 15.99)])
        assert product.shipping_class == pricing.DEFAULT_SHIPPING_CLASS and product.contains_battery is False
        blockers = gate_blockers(db, product)
        assert not [b for b in blockers if "价格" in b or "运费模板" in b], blockers
