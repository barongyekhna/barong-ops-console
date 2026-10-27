"""K 文案「按意见改」入口(10-27):逐字段改措辞,改完再过一遍 K 自己的校验链。unit,不连库、不出网。

验的是规矩本身:买家可见字段不许中文、不许第三方品牌、不许价格/运费/退货期限/保修/认证/保险;卖点原文和规格表不在这里改;
标题里没证据的片段 K 会删掉并告诉调用方(adjusted);证据契约原样保留,P 的上架门禁照常认;每次改都记 revisions。
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from backend.app.modules.k_series.product_knowledge import copy_edits
from backend.app.modules.k_series.product_knowledge.copy_edits import CopyEditError, apply_copy_edits
from backend.app.modules.k_series.product_knowledge.workflow_engine import _image_brief_evidence_digest
from backend.app.modules.p_series.upload.assemble import _evidence_gate_blockers

pytestmark = pytest.mark.unit


def _verified_point(pid: str, text: str) -> dict[str, Any]:
    snapshot = {"kind": "operator_fact", "value_text": text}
    digest = hashlib.sha256(json.dumps(snapshot, default=str, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "id": pid,
        "category": "Performance",
        "text": text,
        "importance_score": 90,
        "evidence": "operator_fact",
        "evidence_excerpt": text,
        "evidence_snapshot": snapshot,
        "evidence_digest": digest,
        "verification_status": "verified",
        "review_decision": "approve",
    }


def _copy() -> dict[str, Any]:
    return {
        "channel": "dtc",
        "product_page_copy": {
            "above_the_fold": {
                "headline": "Rinse clean wherever the trail takes you",
                "subheadline": "A rechargeable camping shower with strong flow.",
                "short_description": "Take a portable camping shower to off-grid campsites. The 2.11 GPM pump helps you rinse thoroughly.",
            },
            "key_bullets": ["stale bullet text that must be re-projected"],
            "chunk_sections": [
                {"heading": "A portable outdoor shower built for off-grid routines", "body": "Enjoy a dependable rinse at camp."},
                {"heading": "Easy to carry", "body": "The 6.5 ft hose packs down small."},
            ],
            "specifications_html_table": "<table><tr><td>Flow</td><td>2.11 GPM</td></tr></table>",
            "conversion_support_block": "A strong fit for campers and van life travelers.",
        },
        "page_faq": [{"question": "How does this portable camping shower pump draw water?", "answer": "Set the pump into your water source.", "evidence_refs": ["s1"], "intent_cluster": "how_it_works"}],
        "seo": {
            "title": "Rechargeable Portable Camping Shower Kit | Barong Yekhna",
            "meta_description": "Take a rechargeable portable camping shower off-grid with strong 2.11 GPM flow.",
            "h1": "Portable Camping Shower – Rechargeable off-grid rinses",
            "url_slug": "portable-camping-shower-kit",
        },
        "evidence_contract": "pdp-evidence-v1",
        "coverage": {"rate": 0.9},
    }


class _FakeDb:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)

    def execute(self, *args: Any, **kwargs: Any) -> Any:  # 变体包装数量的查询:unit 里没库,帮手自己兜底成 []
        raise RuntimeError("no db in unit test")


def _product(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> SimpleNamespace:
    points = [_verified_point("bp1", "Delivers a strong 2.11 GPM flow rate for a thorough rinse."), _verified_point("bp2", "Built-in 7800 mAh rechargeable battery powers multiple showers per charge.")]
    product = SimpleNamespace(
        id=uuid4(),
        product_name_en="Portable Camping Shower",
        product_type="simple_product",
        category_path="Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Showers",
        merchant_product_type=None,
        category_hint=None,
        primary_keyword="portable camping shower",
        structured_specs_json=None,
        package_includes_json=None,
        faq_research_json=None,
        detected_brand_terms=["Ivation"],
        selling_points_approved_json={"review_status": "approved", "bullets": points},
        marketing_copy_json=_copy(),
        marketing_copy_zh="旧的中文对照",
    )
    for key, value in overrides.items():
        setattr(product, key, value)
    product.marketing_copy_json["evidence_digest"] = _image_brief_evidence_digest(product)
    assert _evidence_gate_blockers(product) == []  # 前提:这版文案的证据快照是新的
    monkeypatch.setattr(copy_edits, "_latest_execution", lambda db, product_id: None)
    return product


def test_edits_change_wording_keep_evidence_and_record_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    product = _product(monkeypatch)
    db = _FakeDb()
    out = apply_copy_edits(
        db,
        product,
        {
            "headline": "Rinse off anywhere, no plumbing needed",
            "chunk_sections": [{"index": 1, "body": "The 6.5 ft hose and compact pump pack down small for the trunk."}],
            "seo": {"meta_description": "Rechargeable portable camping shower with 2.11 GPM flow for off-grid rinses."},
            "page_faq": [{"index": 0, "answer": "Set the submersible pump into a bucket or stream; it draws water and pushes it through the hose."}],
        },
        actor_user_id="1",
        reason="苏青禾读稿:钩子太像产品名",
        source="suqinghe_review",
    )
    copy = product.marketing_copy_json
    assert sorted(out["changed"]) == ["above_the_fold.headline", "chunk_sections[1].body", "page_faq[0].answer", "seo.meta_description"]
    assert out["adjusted"] == []
    assert copy["product_page_copy"]["above_the_fold"]["headline"] == "Rinse off anywhere, no plumbing needed"
    assert copy["product_page_copy"]["chunk_sections"][1]["body"].startswith("The 6.5 ft hose")
    assert copy["product_page_copy"]["chunk_sections"][0]["body"] == "Enjoy a dependable rinse at camp."  # 没动的不变
    assert copy["page_faq"][0]["answer"].startswith("Set the submersible pump")
    # 卖点栏永远是批过卖点的原文(改之前文案里那条旧的被投影掉了)
    assert copy["product_page_copy"]["key_bullets"] == [b["text"] for b in product.selling_points_approved_json["bullets"]]
    # 证据契约原样保留,P 的门禁照常认
    assert copy["evidence_contract"] == "pdp-evidence-v1" and _evidence_gate_blockers(product) == []
    rev = copy["revisions"][-1]
    assert rev["actor_user_id"] == "1" and rev["source"] == "suqinghe_review" and rev["reason"].startswith("苏青禾读稿") and rev["fields"] == out["changed"]
    assert product.marketing_copy_zh is None and db.added == [product]


@pytest.mark.parametrize(
    ("edits", "field", "why"),
    [
        ({"headline": "随时随地冲个澡"}, "above_the_fold.headline", "中文"),
        ({"short_description": "Works like the Ivation shower you know."}, "above_the_fold.short_description", "Ivation"),
        ({"conversion_support_block": "Order now for $29.99 with free shipping."}, "conversion_support_block", "价格"),
        ({"chunk_sections": [{"index": 0, "body": "Comes with a 30-day money back guarantee."}]}, "chunk_sections[0].body", "退货"),
        ({"seo": {"h1": "UL Certified Portable Camping Shower"}}, "seo.h1", "认证"),
        ({"seo": {"url_slug": "Portable Shower!"}}, "seo.url_slug", "小写"),
        ({"chunk_sections": [{"index": 7, "body": "No such section."}]}, "chunk_sections[7]", "没有这一段"),
        ({"page_faq": [{"index": 3, "answer": "No such question."}]}, "page_faq[3]", "没有这一问"),
        ({"key_bullets": ["new bullet"]}, "key_bullets", "卖点"),
    ],
)
def test_red_lines_bounce_the_field_and_change_nothing(monkeypatch: pytest.MonkeyPatch, edits: dict[str, Any], field: str, why: str) -> None:
    product = _product(monkeypatch)
    before = json.dumps(product.marketing_copy_json, sort_keys=True)
    with pytest.raises(CopyEditError) as info:
        apply_copy_edits(_FakeDb(), product, edits, actor_user_id="1")
    assert info.value.code == "MARKETING_COPY_EDIT_INVALID" and info.value.status_code == 422
    assert [item["field"] for item in info.value.items] == [field]
    assert why in info.value.items[0]["error"]
    assert json.dumps(product.marketing_copy_json, sort_keys=True) == before and product.marketing_copy_zh == "旧的中文对照"


def test_bad_fields_are_listed_together_so_the_caller_can_drop_them_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    product = _product(monkeypatch)
    with pytest.raises(CopyEditError) as info:
        apply_copy_edits(_FakeDb(), product, {"headline": "Rinse anywhere", "subheadline": "带中文", "seo": {"title": "Shower | Vango"}}, actor_user_id="1")
    assert sorted(i["field"] for i in info.value.items) == ["above_the_fold.subheadline", "seo.title"]


def test_unsupported_title_claims_are_cut_by_k_and_reported_as_adjusted(monkeypatch: pytest.MonkeyPatch) -> None:
    product = _product(monkeypatch)
    out = apply_copy_edits(_FakeDb(), product, {"seo": {"h1": "Portable Camping Shower | Heats Water to 104°F"}}, actor_user_id="1")
    assert out["changed"] == ["seo.h1"]
    assert [a["field"] for a in out["adjusted"]] == ["seo.h1"]
    assert "104" not in product.marketing_copy_json["seo"]["h1"]  # 没证据的加热说法被 K 的标题校验删掉了


def test_empty_edits_and_missing_or_stale_copy_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    product = _product(monkeypatch)
    with pytest.raises(CopyEditError) as info:
        apply_copy_edits(_FakeDb(), product, {}, actor_user_id="1")
    assert info.value.code == "MARKETING_COPY_EDIT_EMPTY"
    product.marketing_copy_json["evidence_digest"] = "stale"
    with pytest.raises(CopyEditError) as info:
        apply_copy_edits(_FakeDb(), product, {"headline": "Rinse anywhere"}, actor_user_id="1")
    assert info.value.code == "MARKETING_COPY_STALE" and info.value.status_code == 409
    product.marketing_copy_json = None
    with pytest.raises(CopyEditError) as info:
        apply_copy_edits(_FakeDb(), product, {"headline": "Rinse anywhere"}, actor_user_id="1")
    assert info.value.code == "MARKETING_COPY_MISSING"


def test_route_maps_edit_errors_to_422_with_items(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from backend.app.modules.k_series.product_knowledge import router as router_module

    product = _product(monkeypatch)
    db = _FakeDb()
    db.rollback = lambda: None  # type: ignore[attr-defined]
    db.commit = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setattr(router_module, "_scope_context", lambda _request: object())
    monkeypatch.setattr(router_module, "get_product", lambda _db, **_kwargs: product)
    payload = router_module.MarketingCopyEditRequest(edits=router_module.MarketingCopyEdits(headline="带中文的钩子"), reason="test")
    with pytest.raises(HTTPException) as info:
        router_module.product_knowledge_edit_marketing_copy(product_id=product.id, payload=payload, request=SimpleNamespace(), db=db, user=SimpleNamespace(id=1))  # type: ignore[arg-type]
    assert info.value.status_code == 422
    assert info.value.detail["code"] == "MARKETING_COPY_EDIT_INVALID" and info.value.detail["items"][0]["field"] == "above_the_fold.headline"
    ok = router_module.product_knowledge_edit_marketing_copy(
        product_id=product.id,
        payload=router_module.MarketingCopyEditRequest(edits=router_module.MarketingCopyEdits(headline="Rinse off anywhere"), reason="test"),
        request=SimpleNamespace(),  # type: ignore[arg-type]
        db=db,
        user=SimpleNamespace(id=1),  # type: ignore[arg-type]
    )
    assert ok.changed == ["above_the_fold.headline"] and ok.marketing_copy["product_page_copy"]["above_the_fold"]["headline"] == "Rinse off anywhere"
