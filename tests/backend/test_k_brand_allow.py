"""放行词表(11-03 老板定):panda 造型的 panda 不是别人的牌子;全站所有品牌检查都先查这张表。

老板原话:「不能因为有一家公司叫panda，就不让我用这个词形容我的产品了……他的panda商标只限餐饮类和我一点关系都没有」。
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

ALLOWED = frozenset({"panda"})


@pytest.fixture()
def allow_panda(monkeypatch: pytest.MonkeyPatch):
    from backend.app.modules.k_series.product_knowledge import brand_allow

    monkeypatch.setattr(brand_allow, "allowed_words", lambda db=None, *, fresh=False: ALLOWED)
    return brand_allow


def test_covered_means_whole_word_and_no_real_competitor_brand() -> None:
    from backend.app.modules.k_series.product_knowledge import brand_allow as ba

    for term in ["panda", "Panda", "panda pump", "Panda Outdoor Shower", "  PANDA  portable shower head ", "panda-shaped shower"]:
        assert ba.is_covered(term, ALLOWED), term
    # 整词才算:pandas / pandaland 不是 panda
    for term in ["pandas library", "pandaland", "", None, "camping shower"]:
        assert not ba.is_covered(term, ALLOWED), term
    # 旁边带着同品类真竞品牌子,照样拦
    for term in ["panda shower for dewalt", "Coleman panda lantern", "panda stanley cup"]:
        assert not ba.is_covered(term, ALLOWED), term
    assert ba.strip_covered(["Panda", "Coleman", "panda pump"], ALLOWED) == ["Coleman"]
    assert ba.normalize("  “Panda   Pump”. ") == "panda pump"


def test_reason_says_brand_ignores_negations() -> None:
    from backend.app.modules.k_series.product_knowledge.brand_allow import reason_says_brand

    for reason in ["含竞品品牌词", "疑似他人商标 Panda", "trademark of Panda Restaurant Group", "brand term"]:
        assert reason_says_brand(reason), reason
    # 原来按字一刀切:「非品牌词」也被当成「是品牌」挡掉
    for reason in ["非品牌词,但属于功效宣称", "不是商标,是无依据的防水说法", "not a brand, unsupported claim", "generic term", "", None, "无依据的加热功效声称"]:
        assert not reason_says_brand(reason), reason


def test_validate_term_rejects_empty_long_chinese_and_real_competitors() -> None:
    from backend.app.modules.k_series.product_knowledge import brand_allow as ba

    assert ba.validate_term(" Panda ") == "panda"
    for bad in ["", "   ", "熊猫", "x" * 121, "DeWalt", "coleman lantern"]:
        with pytest.raises(ba.BrandAllowError):
            ba.validate_term(bad)


def test_suqinghe_risk_review_respects_allow_list_but_not_competitor_brands() -> None:
    from backend.app.modules.agent_series.suqinghe import pipeline

    terms = ["panda outdoor shower", "panda shower for dewalt", "stress relief toy", "non-brand thing"]
    reasons = {
        "panda outdoor shower": "含品牌词 Panda(Panda Express)",
        "panda shower for dewalt": "含竞品品牌词",
        "stress relief toy": "功效宣称",
        "non-brand thing": "非品牌词,资料里有依据",
    }
    result = {"decisions": [{"term": t, "decision": "approve", "reason": "资料有依据"} for t in terms]}
    got = {d["term"]: d["decision"] for d in pipeline.fill_risk_decisions(result, terms, reasons, allowed=ALLOWED)}
    assert got == {
        "panda outdoor shower": "approve",  # 老板放行过的词,K 说是牌子也留(模型说留)
        "panda shower for dewalt": "reject",  # 带真竞品牌子,一律不用
        "stress relief toy": "approve",  # 不是牌子的事,按模型
        "non-brand thing": "approve",  # 原来「非品牌词」里有「品牌」二字就被挡
    }
    # 没放行过:K 说是牌子,模型说留也不留(原规矩不变)
    strict = {d["term"]: d["decision"] for d in pipeline.fill_risk_decisions(result, terms, reasons, allowed=frozenset())}
    assert strict["panda outdoor shower"] == "reject"
    assert strict["non-brand thing"] == "approve"
    # 模型说不用,放行词也不会替它改成留
    rejected = pipeline.fill_risk_decisions({"decisions": [{"term": "panda outdoor shower", "decision": "reject"}]}, ["panda outdoor shower"], reasons, allowed=ALLOWED)
    assert rejected[0]["decision"] == "reject"
    # 提示词里告诉模型老板放行过哪些词;没有放行词时和原来一字不差
    assert "老板放行过的词(用在我们商品上不是别人的牌子):panda" in pipeline.risk_prompt_extra(terms, reasons, ALLOWED)
    assert pipeline.risk_prompt_extra(["a"], {"a": "x"}, frozenset()) == "风险词:\n- a(K 的风险原因:x)"
    assert "panda shower 不算蹭餐馆 Panda Express" in pipeline._RISK_ASK


def test_k_keyword_review_keeps_allow_listed_brand_flags_in_keywords(allow_panda) -> None:
    from backend.app.modules.k_series.product_knowledge import workflow_engine as we

    out = we._normalize_claude_result(
        {
            "final_keywords": ["panda outdoor shower", "portable camping shower", "coleman shower"],
            "risk_keywords": [
                {"term": "panda outdoor shower", "reason": "含品牌词 Panda"},
                {"term": "coleman shower", "reason": "含竞品品牌词 Coleman"},
                {"term": "panda shower for kids", "reason": "儿童用品,要 CPSC"},
            ],
        }
    )
    assert "panda outdoor shower" in out["final_keywords"]
    assert [r["term"] for r in out["risk_keywords"]] == ["coleman shower", "panda shower for kids"]
    assert "coleman shower" not in out["final_keywords"]


def test_k_keyword_prompt_explains_trademark_scope() -> None:
    from backend.app.modules.k_series.product_knowledge.prompt_skills import claude_keyword_review_instruction

    text = claude_keyword_review_instruction()
    assert "a mark only covers its registered goods" in text and "panda" in text


def test_brand_audit_drops_allow_listed_terms_and_tells_the_auditor(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.modules.k_series.product_knowledge import brand_guard as bg

    seen: dict[str, str] = {}

    def fake_chat(key, role, kind, messages):  # noqa: ANN001
        seen["system"] = messages[0]["content"]
        return '{"violations": [{"surface": "copy.h1", "term": "Panda pump"}, {"surface": "copy.h1", "term": "Coleman"}, {"surface": "seo.title", "term": "USB-C"}]}'

    monkeypatch.setattr(bg, "_chat_completion", fake_chat)
    out = bg.ai_text_violations(None, [("copy.h1", "Panda pump by Coleman, USB-C")], own_words=None, allowed=ALLOWED)
    assert [v["term"] for v in out] == ["Coleman"]
    assert "OWNER-APPROVED NON-BRAND WORDS" in seen["system"] and "panda" in seen["system"]
    assert "a trademark only covers its registered goods" in bg._TEXT_AUDIT_INSTRUCTION
    # 没有放行词:提示词不多那一段,Panda 照报(原行为)
    out = bg.ai_text_violations(None, [("copy.h1", "Panda pump")], allowed=frozenset())
    assert [v["term"] for v in out] == ["Panda pump", "Coleman"]
    assert "OWNER-APPROVED" not in seen["system"]


def test_source_brand_list_skips_allow_listed(allow_panda) -> None:
    from types import SimpleNamespace

    from backend.app.modules.k_series.product_knowledge import brand_guard as bg

    product = SimpleNamespace(detected_brand_terms=["Panda", "Barong", "Ivation", "x"])
    assert bg.normalized_brand_terms(product) == ["Ivation"]


def test_faq_heuristics_treat_allowed_word_as_generic(allow_panda) -> None:
    from backend.app.modules.k_series.product_knowledge import faq_research as fr

    assert fr.is_faq_question_candidate("Is the Panda Outdoor Shower easy to refill?")
    assert fr.is_faq_text_brand_safe("The PANDA pump draws water from a bucket.")
    assert fr.is_faq_text_brand_safe("Our Panda Kit ships with a hose.")
    # 真竞品照拦
    assert not fr.is_faq_question_candidate("Is Coleman better than this shower?")
    assert not fr.is_faq_text_brand_safe("Works like a Coleman shower.")


def test_faq_heuristics_without_allow_list_still_flag_panda(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.modules.k_series.product_knowledge import brand_allow
    from backend.app.modules.k_series.product_knowledge import faq_research as fr

    monkeypatch.setattr(brand_allow, "allowed_words", lambda db=None, *, fresh=False: frozenset())
    assert not fr.is_faq_text_brand_safe("Our Panda Kit ships with a hose.")


def test_market_keywords_keep_allowed_word_even_if_a_competitor_brand_matches(allow_panda) -> None:
    from backend.app.modules.agent_series.suqinghe import market

    out = market.parse_summary(
        {"keywords": {"category": ["panda shower", "coleman camp shower", "portable camping shower"]}, "competitors": {"brands": ["Panda", "Coleman"]}},
        domains=[],
    )
    assert out["keywords"]["category"] == ["panda shower", "portable camping shower"]


def test_k_risk_review_puts_approved_terms_back_into_keywords() -> None:
    from types import SimpleNamespace

    from backend.app.modules.k_series.product_knowledge.workflow_engine import KProductKnowledgeWorkflowEngine

    execution = SimpleNamespace(claude_filter_result_json={"final_keywords": ["portable camping shower"], "risk_keywords": [{"term": "panda outdoor shower"}]})
    KProductKnowledgeWorkflowEngine._restore_approved_terms_to_keyword_flow(
        None, execution=execution, approved_terms=["panda outdoor shower", "Portable Camping Shower", "  "]
    )
    assert execution.claude_filter_result_json["final_keywords"] == ["portable camping shower", "panda outdoor shower"]
    # 原来:批了「留」也加不回去——这里批了就回到关键词里,别的字段不动
    assert execution.claude_filter_result_json["risk_keywords"] == [{"term": "panda outdoor shower"}]


def test_ignoring_one_brand_finding_actually_runs() -> None:
    """08-31 起这条路径调了一个不存在的 _now(),逐条「忽略(放行)」一点就 500;原来的测试只读源码文本,从没真跑过。"""
    from types import SimpleNamespace

    from backend.app.modules.k_series.product_knowledge import brand_guard as bg
    from backend.app.modules.k_series.product_knowledge.models import KProductKnowledgeProduct

    product = KProductKnowledgeProduct(brand_audit_json={"text_violations": [{"surface": "copy.h1", "term": "Panda"}], "image_violations": []})
    added: list[object] = []
    fp = bg.brand_finding_fingerprint("text", {"surface": "copy.h1", "term": "Panda"})
    audit = bg.set_brand_finding_ignored(
        SimpleNamespace(add=added.append), product=product, fingerprint=fp, ignored=True, user=SimpleNamespace(username="owner", id=1), reason="熊猫造型"
    )
    assert audit["clean"] is True and audit["unresolved_count"] == 0
    assert audit["ignored_findings_trail"][fp]["reason"] == "熊猫造型" and audit["ignored_findings_trail"][fp]["at"]
    assert added == [product]
