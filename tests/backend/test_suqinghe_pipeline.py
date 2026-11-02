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
from backend.app.modules.agent_series.suqinghe.models import SqhCard, SqhDossier, SqhRouteRecord
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
    with without_org_data_isolation(), SessionLocal() as db:  # 合规门(11-02)过了的品;门本身的流程见 test_suqinghe_compliance_gate_flow
        dossier = db.get(SqhDossier, ready.id)
        dossier.draft = {**(dossier.draft or {}), "compliance_gate": {"version": 1, "source": "1688", "status": "pass", "hits": [], "outside": None}}
        db.commit()
    yield ready.id, outcome["k_product_id"], clean["owner"]
    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(delete(KProductKnowledgeWorkflowExecution).where(KProductKnowledgeWorkflowExecution.product_id == outcome["k_product_id"]))
        db.execute(delete(SqhCard).where(SqhCard.kind == pipeline.BLOCKED_CARD_KIND))
        db.execute(delete(SqhRouteRecord).where(SqhRouteRecord.dossier_id == ready.id))
        db.commit()


def _pick() -> tuple[int, str] | None:
    with without_org_data_isolation(), SessionLocal() as db:
        return pipeline.pick(db)


def _pipe(dossier_id: int) -> dict[str, Any]:
    with without_org_data_isolation(), SessionLocal() as db:
        return dict((db.get(SqhDossier, dossier_id).draft or {}).get("pipeline") or {})


def _route_chosen(dossier_id: int, pack: str = "sunny-pop") -> None:
    """选包定下来了(M2a):种一份「用」的选包记录。选包本身的流程见 test_jiagui_registry_flow。"""
    with without_org_data_isolation(), SessionLocal() as db:
        db.add(SqhRouteRecord(dossier_id=dossier_id, sku="TEST", decision_kind="use", pack_id=pack, pack_version="1.0.1", record={}, registry_fp=""))
        db.commit()


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
    monkeypatch.setenv("SQH_MARKET_ENABLED", "0")  # 这条只验素材 → 关键词,竞品拆解另有用例
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
    monkeypatch.setenv("SQH_MARKET_ENABLED", "0")
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

    def fake_start(self, product_uuid, *, main_keyword, seed_keywords, competitors=None):
        started.update(main_keyword=main_keyword, seed_keywords=seed_keywords, actor=self.actor.username, org=self.org_id)
        assert competitors == []  # 这条关了竞品拆解,不该带竞品名单
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


def _stage_render(product_id: str, position: int, *, days_old: float = 2.0) -> str:
    """一张 K 的暂存出图(k_auto_render),staged_at 设成几天前。"""
    from datetime import timedelta

    from backend.app.modules.k_series.product_knowledge.image_render_jobs import RENDER_PIPELINE_TAG
    from backend.app.modules.k_series.product_knowledge.models import KProductKnowledgeMediaAsset

    with without_org_data_isolation(), SessionLocal() as db:
        asset = KProductKnowledgeMediaAsset(
            product_id=product_id,
            asset_type="image",
            asset_role="main" if position == 1 else "gallery",
            status="staged",
            review_status="pending",
            mime_type="image/webp",
            metadata_json={
                "render_pipeline": RENDER_PIPELINE_TAG,
                "position": position,
                "placement": "gallery",
                "role_label": f"图{position}",
                "staged_at": (datetime.now(UTC) - timedelta(days=days_old)).isoformat(),
            },
        )
        db.add(asset)
        db.commit()
        return str(asset.id)


def test_review_card_holds_its_images_then_rework_then_publish(built, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from backend.app.modules.content_core import wc_sync
    from backend.app.modules.k_series.product_knowledge import image_render_jobs as irj
    from backend.app.modules.k_series.product_knowledge.models import KProductKnowledgeMediaAsset

    dossier_id, product_id, owner = built
    with without_org_data_isolation(), SessionLocal() as db:
        product = db.get(KProductKnowledgeProduct, product_id)
        product.marketing_copy_json = {
            "seo": {"h1": "Squishy Dumpling Stress Toy", "title": "t"},
            "product_page_copy": {"above_the_fold": {"headline": "Squeeze the stress away"}, "key_bullets": ["Soft TPR", "Slow rise"]},
            "page_faq": [{"question": "q", "answer": "a"}],
        }
        product.selling_points_approved_json = {"review_status": "approved", "bullets": [{"id": "bp1", "text": "柔软 TPR", "category": "material", "importance_score": 8, "evidence": "verified_feature:x"}]}
        product.brand_audit_json = {"clean": True, "image_violations": [], "text_violations": [], "errors": []}
        db.commit()
    first = [_stage_render(product_id, pos) for pos in (1, 2)]
    monkeypatch.setattr(pipeline, "_judge", lambda db, ask, brief, extra, **kw: {"concerns": ["写了缓解焦虑就算健康功效,别写"]})
    out = pipeline.run_step(dossier_id, "review_card")
    assert out["ok"], out
    ref = _pipe(dossier_id)["review"]["card_ref"]
    with without_org_data_isolation(), SessionLocal() as db:
        card = db.scalar(select(SqhCard).where(SqhCard.ref == ref))
        assert card.kind == pipeline.REVIEW_CARD_KIND and [i["asset_id"] for i in card.evidence["images"]] == first
        assert card.evidence["concerns"] == ["写了缓解焦虑就算健康功效,别写"] and "合规要你看" in card.why
        assert card.evidence["copy"]["h1"] == "Squishy Dumpling Stress Toy"
        # 暂存了两天,K 的 24 小时回收照样跑——审核卡上的图不收
        assert irj.cleanup_stale_staged(db, product_id) == 0
        db.commit()
        assert {a.status for a in db.scalars(select(KProductKnowledgeMediaAsset).where(KProductKnowledgeMediaAsset.id.in_(first)))} == {"staged"}

    # 驳回:她把老板的话对到第 2 张图,单张重做
    _decide(ref, "reject", owner, reason="第二张图太暗")
    reworked: list[tuple[str, str]] = []
    monkeypatch.setattr(pipeline, "_judge", lambda db, ask, brief, extra, **kw: {"drop_points": [], "image_fixes": [{"position": 2, "instruction": "调亮"}], "unclear": ""})
    monkeypatch.setattr(k_ops.KHands, "render_rework", lambda self, pid, *, asset_id, extra_prompt: reworked.append((str(asset_id), extra_prompt)))
    out = pipeline.run_step(dossier_id, "rework")
    assert out["ok"] and "第 2 张" in out["note"], out
    assert reworked == [(first[1], "调亮(老板原话:第二张图太暗)")]
    assert _pipe(dossier_id)["review"]["card_ref"] is None and _pipe(dossier_id)["review"]["history"][0]["reason"] == "第二张图太暗"

    # 重做的图出来了(同一位置新的一张)→ 新审核卡带的是新图;老板批了 → 保存 → 推 → 回读 Woo
    newer = _stage_render(product_id, 2, days_old=0)
    assert pipeline.run_step(dossier_id, "review_card")["ok"]
    ref2 = _pipe(dossier_id)["review"]["card_ref"]
    with without_org_data_isolation(), SessionLocal() as db:
        assert [i["asset_id"] for i in db.scalar(select(SqhCard).where(SqhCard.ref == ref2)).evidence["images"]] == [first[0], newer]
    assert "推上独立站" in _decide(ref2, "approve", owner)["note"]
    calls: list[str] = []
    monkeypatch.setattr(k_ops.KHands, "save_renders", lambda self, pid: calls.append("save"))
    monkeypatch.setattr(k_ops.KHands, "dispatch", lambda self, pid: calls.append("dispatch") or SimpleNamespace(job_id="job-sqh-1"))
    assert pipeline.run_step(dossier_id, "save_renders")["ok"]
    assert pipeline.run_step(dossier_id, "dispatch")["ok"]
    assert calls == ["save", "dispatch"]
    with without_org_data_isolation(), SessionLocal() as db:
        from sqlalchemy import text

        db.execute(
            text(
                "INSERT INTO p_upload_jobs (job_id, product_id, channel, status, token, external_product_id, external_url, created_at, updated_at) "
                "VALUES ('job-sqh-1', :p, 'woocommerce', 'success', 't', '4321', 'https://shop/p/4321', now(), now())"
            ),
            {"p": product_id},
        )
        db.commit()
    monkeypatch.setattr(wc_sync, "fetch_product_states_safely", lambda db, ids: {4321: {"status": "draft"}})
    out = pipeline.run_step(dossier_id, "readback")
    assert out["ok"] and "#4321" in out["note"] and "draft" in out["note"], out
    assert _pipe(dossier_id)["publish"]["live"]["status"] == "draft"
    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(__import__("sqlalchemy").text("DELETE FROM p_upload_jobs WHERE job_id = 'job-sqh-1'"))
        db.execute(delete(KProductKnowledgeMediaAsset).where(KProductKnowledgeMediaAsset.product_id == product_id, KProductKnowledgeMediaAsset.status == "staged"))
        db.execute(delete(SqhCard).where(SqhCard.kind == pipeline.REVIEW_CARD_KIND))
        db.commit()


def test_copy_is_read_fixed_carded_and_reworked_before_images(built, monkeypatch: pytest.MonkeyPatch) -> None:
    """文案三件事(10-27):K 写完她读稿改稿(经 K 的改稿接口,K 退回的去掉再交)→ 文案卡全文给老板 → 驳回按意见改 →
    改卖点原文走卖点审批(文案作废重写,老板的话带到下一版读稿)→ 批了锁定这版;作图指令那段先停,开关放开才往下。"""
    from backend.app.modules.k_series.product_knowledge.workflow_engine import _image_brief_evidence_digest
    from tests.backend.test_k_copy_edits import _copy, _verified_point

    dossier_id, product_id, owner = built
    monkeypatch.setenv("SQH_IMAGE_BRIEF_PAUSED", "1")
    points = [
        _verified_point("bp1", "Delivers a strong 2.11 GPM flow rate for a thorough rinse."),
        _verified_point("bp2", "Built-in 7800 mAh rechargeable battery powers multiple showers per charge."),
    ]

    def plant_copy() -> None:
        with without_org_data_isolation(), SessionLocal() as db:
            product = db.get(KProductKnowledgeProduct, product_id)
            product.product_name_en = "Portable Camping Shower"
            product.faq_research_json = None
            product.selling_points_approved_json = {"review_status": "approved", "bullets": [dict(p) for p in points], "seo_keywords": ["portable camping shower"]}
            copy = _copy()
            copy["evidence_digest"] = _image_brief_evidence_digest(product)
            product.marketing_copy_json = copy
            db.commit()

    plant_copy()
    with without_org_data_isolation(), SessionLocal() as db:
        dossier = db.get(SqhDossier, dossier_id)
        dossier.draft = {**dossier.draft, "pipeline": {"main_keyword": "portable camping shower", "selling_points": {"held_certifications": ["UL 1642"]}}}
        db.commit()
    # 文案前面那几道门(素材、关键词、卖点、价格卡)在视图上打桩成「都过了」;文案这几个字段照旧从 K 和档案里读真的
    import dataclasses

    real_build_view = pipeline.build_view
    monkeypatch.setattr(
        pipeline,
        "build_view",
        lambda db, dossier, product: dataclasses.replace(
            real_build_view(db, dossier, product),
            material_done=True,
            market_done=True,
            execution_status="blocked",
            execution_step="marketing_copy_generation",
            risk_approved=True,
            sp_approved=True,
            price_card="approved",
            price_applied=True,
            shipping_set=True,
        ),
    )
    try:
        assert _pick() == (dossier_id, "copy_check")

        # 她读稿:改钩子和一条 FAQ;副标题里写了 free shipping,K 退回那一条,其余照改
        asks: list[str] = []

        def reader(db, ask, brief, extra, **kw):
            asks.append(extra)
            return {
                "summary_zh": "卖便携淋浴,主打流量和续航",
                "edits": {
                    "headline": "Rinse off anywhere, no plumbing needed",
                    "subheadline": "Strong flow with free shipping on every order",
                    "page_faq": [{"index": 0, "answer": "Set the submersible pump into a bucket or stream and it draws water on its own."}],
                },
                "notes": ["钩子改成买家结果"],
                "unsure": ["bp2 的 7800 mAh 要核对"],
            }

        monkeypatch.setattr(pipeline, "_judge", reader)
        out = pipeline.run_step(dossier_id, "copy_check")
        assert out["ok"] and "改了 2 处" in out["note"] and "1 处要老板定" in out["note"], out
        assert "UL 1642" in asks[-1] and "bp1: Delivers" in asks[-1]
        check = _pipe(dossier_id)["copy_check"]
        assert check["changed"] == ["above_the_fold.headline", "page_faq[0].answer"]
        assert any("subheadline" in n and "K 不认" in n and "运费" in n for n in check["notes"]), check["notes"]
        with without_org_data_isolation(), SessionLocal() as db:
            copy = db.get(KProductKnowledgeProduct, product_id).marketing_copy_json
            assert copy["product_page_copy"]["above_the_fold"]["headline"] == "Rinse off anywhere, no plumbing needed"
            assert copy["product_page_copy"]["above_the_fold"]["subheadline"] == "A rechargeable camping shower with strong flow."  # 被退回的那条没动
            assert copy["product_page_copy"]["key_bullets"] == [p["text"] for p in points]
            assert copy["revisions"][-1]["source"] == "suqinghe_review" and copy["revisions"][-1]["actor_user_id"] == str(owner)

        assert _pick() == (dossier_id, "copy_card")
        assert pipeline.run_step(dossier_id, "copy_card")["ok"]
        ref = _pipe(dossier_id)["copy_card"]["card_ref"]
        with without_org_data_isolation(), SessionLocal() as db:
            card = db.scalar(select(SqhCard).where(SqhCard.ref == ref))
            assert card.kind == pipeline.COPY_CARD_KIND and card.status == "pending" and card.confidence == "medium"
            ev = card.evidence
            assert ev["copy"]["headline"] == "Rinse off anywhere, no plumbing needed" and ev["copy"]["faq"][0]["answer"].startswith("Set the submersible pump")
            assert ev["copy"]["bullets"] == [p["text"] for p in points] and ev["points"][1]["id"] == "bp2"
            assert ev["check"]["unsure"] == ["bp2 的 7800 mAh 要核对"] and ev["brief_paused"] is True
            assert "UL 1642" in card.why and "要你定" in card.why and "作图指令按你的安排先不动" in card.conclusion
        assert _pick() is None  # 等老板

        # 驳回,只说标题:她翻成 seo.h1 的改动,这版她刚改的不用再读,直接重出文案卡
        assert "改文案" in _decide(ref, "reject", owner, reason="标题改成 Portable Camping Shower – Rechargeable Battery")["note"]
        assert _pick() == (dossier_id, "copy_rework")
        monkeypatch.setattr(
            pipeline,
            "_judge",
            lambda db, ask, brief, extra, **kw: {"edits": {"seo": {"h1": "Portable Camping Shower – Rechargeable Battery"}}, "bullet_edits": [], "drop_points": [], "unclear": ""},
        )
        out = pipeline.run_step(dossier_id, "copy_rework")
        assert out["ok"] and "seo.h1" in out["note"], out
        pipe = _pipe(dossier_id)
        assert pipe["copy_card"]["card_ref"] is None and pipe["copy_card"]["history"][0]["reason"].startswith("标题改成")
        assert _pick() == (dossier_id, "copy_card")
        assert pipeline.run_step(dossier_id, "copy_card")["ok"]
        ref2 = _pipe(dossier_id)["copy_card"]["card_ref"]
        assert ref2 != ref
        with without_org_data_isolation(), SessionLocal() as db:
            h1 = db.scalar(select(SqhCard).where(SqhCard.ref == ref2)).evidence["copy"]["seo"]["h1"]
            assert h1.lower().startswith("portable camping shower") and "rechargeable battery" in h1.lower(), h1

        # 再驳,这次说的是卖点:去掉 bp2 → 走卖点审批,文案证据过期要重写;老板的话留给下一版读稿
        _decide(ref2, "reject", owner, reason="第二条卖点不要,电池续航没实测")
        monkeypatch.setattr(pipeline, "_judge", lambda db, ask, brief, extra, **kw: {"edits": {}, "bullet_edits": [], "drop_points": ["bp2"], "unclear": ""})
        out = pipeline.run_step(dossier_id, "copy_rework")
        assert out["ok"] and "去掉卖点 bp2" in out["note"] and "重写" in out["note"], out
        with without_org_data_isolation(), SessionLocal() as db:
            product = db.get(KProductKnowledgeProduct, product_id)
            assert [b["text"] for b in product.selling_points_approved_json["bullets"]] == [points[0]["text"]]
        assert _pick() == (dossier_id, "copy")  # 文案跟不上卖点了,K 重写
        assert _pipe(dossier_id)["copy_boss_note"].startswith("第二条卖点不要")

        # K 重写好了(这里直接种一版):她再读一遍,读稿时看得到老板上一版的意见
        points.pop()
        plant_copy()
        assert _pick() == (dossier_id, "copy_check")
        asks.clear()
        monkeypatch.setattr(pipeline, "_judge", lambda db, ask, brief, extra, **kw: asks.append(extra) or {"summary_zh": "重写后的版本没问题", "edits": {}, "notes": [], "unsure": []})
        out = pipeline.run_step(dossier_id, "copy_check")
        assert out["ok"] and "没什么要改的" in out["note"], out
        assert "第二条卖点不要" in asks[-1] and _pipe(dossier_id).get("copy_boss_note") is None
        assert pipeline.run_step(dossier_id, "copy_card")["ok"]
        ref3 = _pipe(dossier_id)["copy_card"]["card_ref"]

        # 批了:锁定这版;作图指令先停,放开开关才往下
        assert "先不动" in _decide(ref3, "approve", owner)["note"]
        assert _pipe(dossier_id)["copy_approved"]["card_ref"] == ref3
        assert _pick() is None
        monkeypatch.setenv("SQH_IMAGE_BRIEF_PAUSED", "0")
        assert _pick() is None  # M2a(11-02):风格包还没定下来,作图那一段等着
        _route_chosen(dossier_id)
        assert _pick() == (dossier_id, "image_brief")
    finally:
        with without_org_data_isolation(), SessionLocal() as db:
            db.execute(delete(SqhCard).where(SqhCard.kind == pipeline.COPY_CARD_KIND))
            db.commit()


def test_market_research_feeds_keywords_and_a_rejected_card_reruns_them(built, monkeypatch: pytest.MonkeyPatch) -> None:
    """竞品拆解(10-27):素材之后她读同类页 → 拆解卡(不用批)→ 种子词和竞品名带进 K 的关键词;老板驳了 → 撤掉重跑;拆不了两次 → 跳过不挡。"""
    from backend.app.modules.agent_series.suqinghe import market
    from backend.app.modules.agent_series.suqinghe.models import SqhMemory

    dossier_id, product_id, owner = built
    with without_org_data_isolation(), SessionLocal() as db:
        dossier = db.get(SqhDossier, dossier_id)
        dossier.draft = {**dossier.draft, "material": {"features": [], "claims": [], "hype": [], "version": material.MATERIAL_VERSION}}
        dossier.capture = {**(dossier.capture or {}), "pick_card_ref": None}
        db.commit()
    assert _pick() == (dossier_id, "market")

    done = {
        "status": "done",
        "query": "squishy stress toy",
        "pages": [{"url": f"https://shop{i}.com/p", "domain": f"shop{i}.com", "title": f"Toy {i}", "ok": True, "price": 12.0 + i, "bullets": 4, "faq": 2, "image_count": 6, "highlight": "Soft and slow rising", "claims": []} for i in range(4)],
        "serp_keywords": ["squishy toys for adults"],
        "priorities": [{"what": "捏起来软不软、回弹慢不慢", "why": "四家都把手感放第一条"}, {"what": "材质安不安全", "why": "三家写了无毒"}],
        "ours": {"has": ["慢回弹"], "missing": ["材质检测报告"]},
        "bullet_order_hint": ["slow rising soft", "safe material"],
        "keywords": {"category": ["squishy stress toy", "stress relief squishy"], "attribute": ["slow rising"], "scene": ["desk fidget"], "question": ["are squishies safe for kids?"]},
        "competitors": {"brands": ["Squishmallows"], "domains": ["shop0.com"]},
        "gaps": ["材质检测报告有没有"],
        "note": "同类都在卖手感,我们要把慢回弹讲到最前面",
        "at": "2026-10-27T00:00:00+00:00",
    }
    monkeypatch.setattr(market, "research", lambda db, **kw: done)
    out = pipeline.run_step(dossier_id, "market")
    assert out["ok"] and "拆解卡 #" in out["note"] and "4 个关键词种子" in out["note"], out
    pipe = _pipe(dossier_id)
    ref = pipe["market"]["card_ref"]
    with without_org_data_isolation(), SessionLocal() as db:
        card = db.scalar(select(SqhCard).where(SqhCard.ref == ref))
        assert card.kind == pipeline.MARKET_CARD_KIND and card.status == "pending" and "不用批" in card.conclusion
        assert card.evidence["priorities"][0]["what"].startswith("捏起来") and card.evidence["keywords"]["category"] == ["squishy stress toy", "stress relief squishy"]
        assert [p["domain"] for p in card.evidence["pages"]] == [f"shop{i}.com" for i in range(4)]
        assert db.scalar(select(SqhMemory).where(SqhMemory.kind == "observation", SqhMemory.subject.like("%竞品拆解%"))) is not None
    assert _pick() == (dossier_id, "keywords")

    # 关键词:她定的种子 + 拆解来的种子,竞品名单一起交给 K
    started: dict[str, Any] = {}
    monkeypatch.setattr(pipeline, "_judge", lambda db, ask, brief, extra, **kw: {"main_keyword": "squishy stress toy", "seed_keywords": ["squishy toys"], "reason": "品类词"})

    def fake_start(self, product_uuid, *, main_keyword, seed_keywords, competitors=None):
        started.update(main_keyword=main_keyword, seed_keywords=seed_keywords, competitors=competitors)
        _plant_execution(str(product_uuid), status="blocked", current_step="risk_term_review_manual", claude_filter_result_json={"risk_keywords": []}, error_report_json={"code": "RISK_REVIEW_REQUIRED"})

    monkeypatch.setattr(k_ops.KHands, "start_keywords", fake_start)
    out = pipeline.run_step(dossier_id, "keywords")
    assert out["ok"] and "4 个拆解来的种子词、2 个竞品名" in out["note"], out
    assert started["seed_keywords"] == ["squishy toys", "squishy stress toy", "stress relief squishy", "slow rising", "desk fidget"]
    assert started["competitors"] == ["Squishmallows", "shop0.com"]

    # 老板驳了拆解卡:情报撤掉,关键词从 SERP 那一步重跑、不带种子和竞品
    assert "重跑" in _decide(ref, "reject", owner, reason="这几家不是我们的对手")["note"]
    pipe = _pipe(dossier_id)
    assert pipe["market"]["status"] == "rejected" and pipe["keywords_rerun"] is True
    assert _pick() == (dossier_id, "keywords_retry")
    retried: dict[str, Any] = {}
    monkeypatch.setattr(k_ops.KHands, "retry_keywords", lambda self, pid, *, step, main_keyword, seed_keywords, competitors=None: retried.update(step=step, seed_keywords=seed_keywords, competitors=competitors))
    out = pipeline.run_step(dossier_id, "keywords_retry")
    assert out["ok"], out
    assert retried == {"step": "serp_keyword_fetch", "seed_keywords": ["squishy toys"], "competitors": []}
    assert not _pipe(dossier_id).get("keywords_rerun")
    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(delete(SqhCard).where(SqhCard.kind == pipeline.MARKET_CARD_KIND))
        db.commit()


def test_market_research_that_fails_twice_is_skipped_without_blocking(built, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.modules.agent_series.suqinghe import market

    dossier_id, product_id, _ = built
    with without_org_data_isolation(), SessionLocal() as db:
        dossier = db.get(SqhDossier, dossier_id)
        dossier.draft = {**dossier.draft, "material": {"features": [], "claims": [], "hype": [], "version": material.MATERIAL_VERSION}}
        db.commit()
    monkeypatch.setattr(market, "research", lambda db, **kw: {"status": "skipped", "reason": "只读到 1 页(至少 3 页才拆)", "query": kw.get("query")})
    first = pipeline.run_step(dossier_id, "market")
    assert first["ok"] is False and first["blocked"] is False and "第 1 次" in first["note"]
    assert _pick() == (dossier_id, "market")  # 再试一次
    second = pipeline.run_step(dossier_id, "market")
    assert second["ok"] and "不带市场情报往下走" in second["note"], second
    assert _pipe(dossier_id)["market"]["status"] == "skipped" and _pipe(dossier_id)["market"]["attempts"] == 2
    assert _pick() == (dossier_id, "keywords")  # 没有「卡住」卡,照常往下
    with without_org_data_isolation(), SessionLocal() as db:
        assert db.scalar(select(SqhCard).where(SqhCard.kind == pipeline.BLOCKED_CARD_KIND)) is None


def test_price_card_asks_the_seller_first_when_the_page_has_no_weights(built, monkeypatch: pytest.MonkeyPatch) -> None:
    """B 期(10-29):详情页没有重量 → 不出价格卡,先在旺旺问卖家(台账 +1);卖家回了 → 规格标「卖家口头」、旧卡作废、价格卡重出并写明;
    老板驳回时点名重量 → 再问一次。整条链上浏览器是假的,模型是假的,台账是真的。"""
    from backend.app.modules.agent_series.suqinghe import browser, pricing, seller_chat
    from backend.app.modules.w_series.shipping.models import WShippingClass
    from r_system_v2.ra.quota_ledger import PROVIDER_SQH_1688_IM, remaining_today

    monkeypatch.setenv("SQH_SELLER_CHAT", "1")
    dossier_id, product_id, owner = built
    variants = [
        {"name_zh": "黑色", "name_en": "Black", "cost_price_cny": 20.0, "weight_g": None, "dims_cm": None},
        {"name_zh": "绿色", "name_en": "Green", "cost_price_cny": 20.0, "weight_g": None, "dims_cm": None},
    ]
    with without_org_data_isolation(), SessionLocal() as db:
        dossier = db.get(SqhDossier, dossier_id)
        dossier.draft = {**dossier.draft, "variants": variants, "supplier": {"name": "义乌市多加玩具有限公司", "login_id": "义乌市多加玩具有限公司"}, "pipeline": {"main_keyword": "squishy stress toy"}}
        if not db.scalar(select(WShippingClass).where(WShippingClass.slug == pricing.DEFAULT_SHIPPING_CLASS)):
            db.add(WShippingClass(slug=pricing.DEFAULT_SHIPPING_CLASS, name="中国直发-标准线", zone_rates_json=[], origin="cn_direct"))
        db.commit()
        before = remaining_today(db, PROVIDER_SQH_1688_IM)

    class FakeBrowser:
        asked: list[dict[str, Any]] = []
        thread: list[dict[str, Any]] = []

        def ask_seller(self, **kw):
            self.asked.append(kw)
            self.thread = [{"self": True, "nick": "无敌小巴龙", "time": "2026-10-29 21:00:00", "text": kw["text"]}]
            return {"ok": True, "im_url": browser.im_url(kw["login_id"], kw["offer_id"]), "login_id": kw["login_id"], "dump": "/tmp/x", "messages": list(self.thread)}

        def read_seller_chat(self, **kw):
            return list(self.thread)

    fake = FakeBrowser()
    monkeypatch.setattr(browser, "enabled", lambda: True)
    monkeypatch.setattr(browser, "holding", lambda: False)
    monkeypatch.setattr(browser, "get", lambda: fake)
    monkeypatch.setattr(pricing, "fetch_shopping", lambda db, *, query, org_id: {"query": query, "n": 0, "samples": []})
    monkeypatch.setattr(pipeline, "_judge", lambda db, ask, brief, extra, **kw: {"variants": [{"key": "v1", "include": True, "price": 12.99, "label_en": "Black", "axis": "color"}, {"key": "v2", "include": True, "price": 12.99, "label_en": "Green", "axis": "color"}], "questions": [], "summary": "按颜色"})

    # 1. 该出价格卡了,但页面没有重量:先问卖家,不发卡,台账 +1,流水线停在「等卖家」
    out = pipeline.run_step(dossier_id, "price_card")
    assert out["ok"] and "先在旺旺问卖家" in out["note"], out
    assert len(fake.asked) == 1 and fake.asked[0]["login_id"] == "义乌市多加玩具有限公司" and fake.asked[0]["text"].startswith("您好,我是跨境卖家")
    with without_org_data_isolation(), SessionLocal() as db:
        assert remaining_today(db, PROVIDER_SQH_1688_IM) == before - 1
        dossier = db.get(SqhDossier, dossier_id)
        chat = dossier.draft["seller_chat"]
        assert chat["status"] == "asked" and chat["question"] == fake.asked[0]["text"] and "price" not in (dossier.draft.get("pipeline") or {})
        product = db.get(KProductKnowledgeProduct, product_id)
        assert pipeline.build_view(db, dossier, product).seller_pending  # 等卖家:next_step 对它的处理见 rules 测试(这个夹具还没走到卖点那一步)
    # 2. 到点去看:卖家回了 → 规格写回(卖家口头)、下一步重出价格卡
    fake.thread.append({"self": False, "nick": "义乌市多加玩具有限公司", "time": "2026-10-29 21:30:00", "text": "黑的 350 克,绿的 420 克,都是 12x8x6,一箱 50 个"})
    later = datetime.now(UTC) + __import__("datetime").timedelta(minutes=20)
    judge = lambda db, prompt: {"answers": [{"key": "v1", "weight_g": 350, "dims_cm": [12, 8, 6], "units_per_carton": 50}, {"key": "v2", "weight_g": 420, "dims_cm": [12, 8, 6], "units_per_carton": 50}]}  # noqa: E731
    with without_org_data_isolation(), SessionLocal() as db:
        assert seller_chat.poll_all(db, now=later, judge=judge) == "answered"
        dossier = db.get(SqhDossier, dossier_id)
        assert dossier.draft["seller_chat"]["status"] == "answered"
        assert [v["weight_g"] for v in dossier.draft["variants"]] == [350.0, 420.0] and all(v["source"] == "seller_said" for v in dossier.draft["variants"])
        product = db.get(KProductKnowledgeProduct, product_id)
        assert not pipeline.build_view(db, dossier, product).seller_pending  # 回了:不再等,下一轮按状态该出价格卡就出
    out = pipeline.run_step(dossier_id, "price_card")
    assert out["ok"] and "价格卡" in out["note"], out
    ref = _pipe(dossier_id)["price"]["card_ref"]
    with without_org_data_isolation(), SessionLocal() as db:
        card = db.scalar(select(SqhCard).where(SqhCard.ref == ref))
        assert card.status == "pending" and "卖家" in card.why and "口头" in card.why and "不当认证" in card.why
        assert all(line["weight_note"] == pricing.SELLER_SAID_NOTE for line in card.evidence["variants"])
        assert card.evidence["seller_chat"]["status"] == "answered"
        assert remaining_today(db, PROVIDER_SQH_1688_IM) == before - 1  # 回了就不再问
    # 3. 老板驳回点名重量 → 下一张卡之前再问一次(台账 +1)。驳回是后端进程处理的,它那边没有开关(10-29 实况):记号照记
    monkeypatch.setenv("SQH_SELLER_CHAT", "0")
    assert "问卖家" in _decide(ref, "reject", owner, reason="绿色的重量不对,再问一下")["note"]
    monkeypatch.setenv("SQH_SELLER_CHAT", "1")
    assert _pipe(dossier_id) is not None
    with without_org_data_isolation(), SessionLocal() as db:
        assert db.get(SqhDossier, dossier_id).draft["seller_chat"]["requested"] is True
    out = pipeline.run_step(dossier_id, "price_card")
    assert out["ok"] and "先在旺旺问卖家" in out["note"], out
    assert len(fake.asked) == 2
    with without_org_data_isolation(), SessionLocal() as db:
        assert remaining_today(db, PROVIDER_SQH_1688_IM) == before - 2
        dossier = db.get(SqhDossier, dossier_id)
        assert dossier.draft["seller_chat"]["status"] == "asked" and dossier.draft["seller_chat"]["boss_reason"] == "绿色的重量不对,再问一下"
