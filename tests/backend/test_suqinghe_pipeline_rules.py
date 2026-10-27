"""苏青禾接管 K 流水线(10-26):下一步干什么、她自己的判断怎么落成 K 要的东西。unit,不连库、不出网。"""

from __future__ import annotations

import json

import pytest

from backend.app.modules.agent_series.suqinghe import k_ops, pipeline
from backend.app.modules.agent_series.suqinghe.pipeline import View, next_step

pytestmark = pytest.mark.unit


def _view(**overrides) -> View:
    base = dict(
        material_done=True,
        stopped=False,
        blocked_step=None,
        execution_status=None,
        execution_step=None,
        execution_minutes=None,
        risk_approved=False,
        sp_job=None,
        sp_failures=0,
        sp_candidates=False,
        sp_approved=False,
    )
    base.update(overrides)
    return View(**base)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"material_done": False}, "material"),
        ({}, "keywords"),
        ({"execution_status": "running", "execution_minutes": 5}, None),  # K 还在跑,等
        ({"execution_status": "running", "execution_minutes": 90}, "keywords_retry"),  # 跑到一半断了
        ({"execution_status": "blocked", "execution_step": "risk_term_review_manual"}, "risk_review"),
        ({"execution_status": "blocked", "execution_step": "serp_keyword_fetch"}, "keywords_retry"),
        ({"execution_status": "failed", "execution_step": "deepseek_enrichment"}, "keywords_retry"),
        # 风险词审完,K 停在「要文案」是正常的,下一步是卖点
        ({"execution_status": "blocked", "execution_step": "marketing_copy_generation", "risk_approved": True}, "selling_points"),
        ({"risk_approved": True, "execution_status": "blocked", "sp_job": "running"}, None),
        ({"risk_approved": True, "execution_status": "blocked", "sp_job": "failed", "sp_failures": 1}, "selling_points"),
        # K 那边连着失败两次 → 停手发卡,不再重排(排队那一下总是「成功」的,不能按它数)
        ({"risk_approved": True, "execution_status": "blocked", "sp_job": "failed", "sp_failures": 2}, "block:selling_points"),
        ({"risk_approved": True, "execution_status": "blocked", "sp_job": "completed", "sp_candidates": True}, "approve_selling_points"),
        # 卖点批完 → 价格卡:没发过/被驳/作废 → 出一张;在等老板 → 等;批了 → 去 K 里改;改完 → 写文案
        ({"risk_approved": True, "execution_status": "blocked", "sp_approved": True}, "price_card"),
        ({"risk_approved": True, "execution_status": "blocked", "sp_approved": True, "price_card": "pending"}, None),
        ({"risk_approved": True, "execution_status": "blocked", "sp_approved": True, "price_card": "rejected"}, "price_card"),
        ({"risk_approved": True, "execution_status": "blocked", "sp_approved": True, "price_card": "stale"}, "price_card"),
        ({"risk_approved": True, "execution_status": "blocked", "sp_approved": True, "price_card": "approved"}, "apply_price"),
        ({"risk_approved": True, "execution_status": "blocked", "sp_approved": True, "price_card": "approved", "price_applied": True, "shipping_set": True}, "copy"),
        ({"blocked_step": "keywords"}, None),  # 「卡住」卡在等老板
        ({"stopped": True, "material_done": False}, None),  # 老板说这个品先不做
    ],
)
def test_next_step_reads_only_k_state(overrides, expected) -> None:
    assert next_step(_view(**overrides)) == expected


def test_main_keyword_must_be_a_short_plain_category_phrase() -> None:
    good = pipeline.parse_keyword_choice(
        {"main_keyword": "Cordless  Drill", "seed_keywords": ["12v drill driver", "cordless drill", "best drill 2026", "DeWalt Drill!"], "reason": "品类词"}
    )
    assert good == {"main_keyword": "cordless drill", "seed_keywords": ["12v drill driver"], "reason": "品类词"}
    for bad in ("drill", "best cordless drill", "12V Cordless Brushless Drill Driver with Keyless Chuck and LED Light", "电钻"):
        assert pipeline.parse_keyword_choice({"main_keyword": bad}) is None, bad
    fenced = {"content": "```json\n" + json.dumps({"main_keyword": "camping lantern", "seed_keywords": []}) + "\n```"}
    assert pipeline.parse_keyword_choice(fenced)["main_keyword"] == "camping lantern"


def test_risk_terms_default_to_reject_unless_explicitly_approved() -> None:
    terms = ["DeWalt compatible battery", "12v drill battery pack", "battery for milwaukee m12"]
    result = {"decisions": [{"term": "12V Drill Battery Pack", "decision": "approve", "reason": "参数对得上"}, {"term": "DeWalt compatible battery", "decision": "maybe"}]}
    decisions = pipeline.fill_risk_decisions(result, terms)
    assert [(d["term"], d["decision"]) for d in decisions] == [
        ("DeWalt compatible battery", "reject"),
        ("12v drill battery pack", "approve"),
        ("battery for milwaukee m12", "reject"),  # 没判到 → 默认不用
    ]
    assert all(d["reason"].startswith("苏青禾:") for d in decisions)
    assert [d["decision"] for d in pipeline.fill_risk_decisions({"content": "看不懂"}, terms)] == ["reject"] * 3
    # K 说是别人的商标:模型说留也不留
    branded = pipeline.fill_risk_decisions(
        {"decisions": [{"term": "12v drill battery pack", "decision": "approve"}]}, ["12v drill battery pack"], {"12v drill battery pack": "含竞品品牌词"}
    )
    assert branded[0]["decision"] == "reject" and "商标" in branded[0]["reason"]


def test_selling_points_keep_verified_and_drop_what_k_bounced() -> None:
    candidates = {
        "review_status": "candidate",
        "bullets": [
            {"id": "sp-1", "category": "performance", "text": "Brushless motor", "importance_score": 9, "evidence": "verified_feature:abc", "verification_status": "verified"},
            {"id": "sp-2", "category": "battery", "text": "Lasts all day", "importance_score": 5, "evidence": "operator_fact", "verification_status": "unverified"},
            {"id": "sp-3", "category": "spec", "text": "12V", "importance_score": 7, "evidence": "spec:additional_specs.sqh_voltage", "verification_status": "verified"},
        ],
    }
    first = pipeline.selling_point_review(candidates)
    assert [b["review_decision"] for b in first] == ["approve", "reject", "approve"]
    again = pipeline.selling_point_review(candidates, pipeline.rejected_indexes({"code": "SELLING_POINT_EVIDENCE_REQUIRED", "items": [{"index": 2, "text": "12V", "error": "数字对不上"}]}))
    assert [b["review_decision"] for b in again] == ["approve", "reject", "reject"]
    assert "verification_status" not in first[0]  # 证据状态由 K 自己重核,不替它填


def test_stand_in_request_carries_the_org_k_reads() -> None:
    from backend.app.modules.k_series.product_knowledge.services.api_support import _scope_context
    from backend.app.services.module_execution_gate import _request_state_value

    request = k_ops.stand_in_request("org_trade")
    assert _scope_context(request).workspace_key == "org_trade"
    assert _request_state_value(request, "org_id", "active_org_id", "session_org_id") == "org_trade"


PRICED = {"risk_approved": True, "execution_status": "blocked", "sp_approved": True, "price_card": "approved", "price_applied": True, "shipping_set": True}
# 文案三件事(10-27)之后:走到作图指令要文案读过、老板批过
COPY_DONE = {**PRICED, "copy_ok": True, "copy_checked": True, "copy_approved": True}
READY = {**COPY_DONE, "brief_ok": True, "render_requested": True, "staged": 9}


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({**PRICED}, "copy"),
        ({**PRICED, "copy_job": "running"}, None),
        ({**PRICED, "copy_job": "failed", "copy_failures": 1}, "copy"),
        ({**PRICED, "copy_job": "failed", "copy_failures": 2}, "block:copy"),
        ({**COPY_DONE}, "image_brief"),
        ({**COPY_DONE, "brief_job": "pending"}, None),
        ({**COPY_DONE, "brief_job": "failed", "brief_failures": 2}, "block:image_brief"),
        ({**COPY_DONE, "brief_ok": True}, "render"),
        ({**READY, "render_active": True}, None),
        ({**READY, "audit_active": True}, None),  # 出完图 K 自己跑品牌审查,等它
        ({**READY}, "review_card"),
        ({**READY, "render_failed": 2}, "render_retry"),
        ({**READY, "render_failed": 2, "render_retried": True}, "review_card"),  # 补过一次还缺的,卡上写着
        ({**READY, "staged": 0}, "block:render"),
        ({**READY, "review_card": "pending"}, None),
        ({**READY, "review_card": "stale"}, "review_card"),
        ({**READY, "review_card": "rejected"}, "rework"),
        ({**READY, "review_card": "approved"}, "save_renders"),
        ({**READY, "review_card": "approved", "saved": True}, "dispatch"),
        ({**READY, "review_card": "approved", "saved": True, "dispatched": True, "upload_status": "queued"}, None),
        ({**READY, "review_card": "approved", "saved": True, "dispatched": True, "upload_status": "failed"}, "block:dispatch"),
        ({**READY, "review_card": "approved", "saved": True, "dispatched": True, "upload_status": "success"}, "readback"),
        ({**READY, "review_card": "approved", "saved": True, "dispatched": True, "upload_status": "success", "live_checked": True}, None),
    ],
)
def test_after_the_price_copy_images_review_then_publish(overrides, expected) -> None:
    assert next_step(_view(**overrides)) == expected


# ---------------------------------------------------------------- 文案三件事(10-27):读稿 → 文案卡 → 批/驳 → (作图指令先停)

CHECKED = {**PRICED, "copy_ok": True, "copy_checked": True}


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({**PRICED, "copy_ok": True}, "copy_check"),  # K 写完先读一遍
        ({**CHECKED}, "copy_card"),
        ({**CHECKED, "copy_card": "pending"}, None),
        ({**CHECKED, "copy_card": "stale"}, "copy_card"),
        ({**CHECKED, "copy_card": "rejected"}, "copy_rework"),
        ({**CHECKED, "copy_card": "approved"}, "copy_card"),  # 批过的是旧版(文案后来又变了,读过了),重新给他看
        ({**CHECKED, "copy_card": "approved", "copy_approved": True, "brief_paused": True}, None),  # 作图指令先停:到这就停
        ({**CHECKED, "copy_card": "approved", "copy_approved": True}, "image_brief"),
        ({**CHECKED, "copy_card": "approved", "copy_approved": True, "brief_ok": True}, "render"),
        ({**PRICED, "copy_ok": True, "copy_checked": False, "copy_card": "approved", "copy_approved": True}, "copy_check"),  # 没读过的版本不能往下
    ],
)
def test_copy_is_read_then_carded_then_images_wait_for_the_switch(overrides, expected) -> None:
    assert next_step(_view(**overrides)) == expected


def test_review_card_rules_still_assume_the_copy_was_approved() -> None:
    """READY 那组用例带着「文案读过、老板批过」:去掉任一个都到不了审核卡,这里钉死这个前提。"""
    assert next_step(_view(**READY)) == "review_card"
    assert next_step(_view(**{**READY, "copy_checked": False})) == "copy_check"
    assert next_step(_view(**{**READY, "copy_approved": False})) == "copy_card"


def test_copy_text_only_keeps_what_the_buyer_sees() -> None:
    from backend.app.modules.agent_series.suqinghe import copywork

    view = copywork.copy_text(
        {
            "product_page_copy": {
                "above_the_fold": {"headline": " Rinse  clean ", "subheadline": None, "short_description": "Two sentences. Here."},
                "key_bullets": ["A", "", "B"],
                "chunk_sections": [{"heading": "H", "body": "B"}, "junk", {"heading": "", "body": ""}],
                "conversion_support_block": "C",
                "specifications_html_table": "<table>secret</table>",
            },
            "seo": {"h1": "H1", "title": "T | Barong Yekhna", "meta_description": "M", "url_slug": "s"},
            "page_faq": [{"question": "Q?", "answer": "A.", "evidence_refs": ["x"]}],
            "missing_inputs": ["no warranty data"],
            "coverage": {"rate": 0.75},
            "evidence_digest": "abc",
        }
    )
    assert view["headline"] == "Rinse clean" and view["subheadline"] == "" and view["bullets"] == ["A", "B"]
    assert view["sections"] == [{"heading": "H", "body": "B"}, {"heading": "", "body": ""}]
    assert view["faq"] == [{"question": "Q?", "answer": "A."}] and view["coverage_rate"] == 0.75
    assert "specifications_html_table" not in json.dumps(view) and "evidence_digest" not in json.dumps(view)
    assert copywork.copy_text(None)["sections"] == []


def test_parse_check_keeps_only_well_formed_in_range_english_edits() -> None:
    from backend.app.modules.agent_series.suqinghe import copywork

    check = copywork.parse_check(
        {
            "summary_zh": "卖的是便携淋浴",
            "edits": {
                "headline": "Rinse off anywhere",
                "subheadline": "",
                "short_description": "带中文的不能要",
                "chunk_sections": [{"index": 1, "body": "New body"}, {"index": 9, "body": "out of range"}, {"index": 1, "heading": "dup index ignored"}, {"index": "0", "body": "bad index"}, {"index": 0}],
                "seo": {"h1": "Portable Camping Shower – Off-Grid Rinses", "url_slug": None, "bogus": "x"},
                "page_faq": [{"index": 0, "answer": "Set the pump in water."}, {"index": 2, "answer": "no such"}],
            },
            "notes": ["钩子改成买家结果", 42, ""],
            "unsure": "not a list",
        },
        sections=2,
        faqs=1,
    )
    assert check["summary_zh"] == "卖的是便携淋浴"
    assert check["edits"] == {
        "headline": "Rinse off anywhere",
        "chunk_sections": [{"index": 1, "body": "New body"}],
        "seo": {"h1": "Portable Camping Shower – Off-Grid Rinses"},
        "page_faq": [{"index": 0, "answer": "Set the pump in water."}],
    }
    assert check["notes"] == ["钩子改成买家结果", "42"] and check["unsure"] == []
    assert copywork.parse_check("garbage", sections=0, faqs=0) == {"summary_zh": "", "edits": {}, "notes": [], "unsure": []}


def test_parse_rework_binds_bullet_changes_to_known_ids() -> None:
    from backend.app.modules.agent_series.suqinghe import copywork

    rw = copywork.parse_rework(
        {
            "edits": {"seo": {"h1": "Shorter title"}},
            "bullet_edits": [{"id": "bp2", "text": "Battery powers several showers per charge"}, {"id": "bp9", "text": "unknown id"}, {"id": "bp1", "text": "中文"}],
            "drop_points": ["bp3", "bp2", "bp3", "nope"],
            "unclear": "  第二段太长  ",
        },
        sections=3,
        faqs=0,
        point_ids={"bp1", "bp2", "bp3"},
    )
    assert rw["edits"] == {"seo": {"h1": "Shorter title"}}
    assert rw["bullet_edits"] == [{"id": "bp2", "text": "Battery powers several showers per charge"}]
    assert rw["drop_points"] == ["bp3"]  # 改过措辞的 bp2 不能同时被去掉
    assert rw["unclear"] == "第二段太长"


def test_strip_edits_removes_exactly_what_k_bounced() -> None:
    from backend.app.modules.agent_series.suqinghe import copywork

    edits = {
        "headline": "H",
        "conversion_support_block": "C",
        "chunk_sections": [{"index": 0, "heading": "h0", "body": "b0"}, {"index": 2, "body": "b2"}],
        "seo": {"title": "T", "h1": "H1"},
        "page_faq": [{"index": 0, "answer": "A0"}, {"index": 1, "answer": "A1"}],
    }
    out = copywork.strip_edits(edits, ["above_the_fold.headline", "chunk_sections[0].body", "chunk_sections[2].body", "seo.title", "page_faq[1].answer", "conversion_support_block"])
    assert out == {"chunk_sections": [{"index": 0, "heading": "h0"}], "seo": {"h1": "H1"}, "page_faq": [{"index": 0, "answer": "A0"}]}
    assert edits["chunk_sections"][0]["body"] == "b0"  # 原样不动
    assert copywork.strip_edits({"seo": {"title": "T"}}, ["seo.title"]) == {}


def test_image_brief_pause_switch_defaults_on() -> None:
    from backend.app.modules.agent_series.suqinghe import constants

    import os

    saved = os.environ.pop("SQH_IMAGE_BRIEF_PAUSED", None)
    try:
        assert constants.image_brief_paused() is True
        os.environ["SQH_IMAGE_BRIEF_PAUSED"] = "0"
        assert constants.image_brief_paused() is False
        os.environ["SQH_IMAGE_BRIEF_PAUSED"] = "1"
        assert constants.image_brief_paused() is True
    finally:
        if saved is None:
            os.environ.pop("SQH_IMAGE_BRIEF_PAUSED", None)
        else:
            os.environ["SQH_IMAGE_BRIEF_PAUSED"] = saved
