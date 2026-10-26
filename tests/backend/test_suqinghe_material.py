"""苏青禾卖点素材(10-26):详情图上的卖点说法 → K 属性(feature/claim)+ 给老板看的宣传语(hype)。unit,不连库、不出网。"""

from __future__ import annotations

import io
from typing import Any

import pytest

from backend.app.modules.agent_series.suqinghe import material
from backend.app.modules.k_series.product_knowledge.schemas import ProductKnowledgeAttributeItem
from backend.app.modules.k_series.product_knowledge.services.selling_points_service import _feature_source_is_trusted

pytestmark = pytest.mark.unit


def test_material_source_counts_as_evidence_for_k_selling_points() -> None:
    """K 写卖点只用可信来源的属性。「detail」里藏着「ai」,起名 1688_detail_image 会被当成 AI 编的、整批不用。"""
    assert _feature_source_is_trusted(material.MATERIAL_SOURCE) is True
    assert _feature_source_is_trusted("1688_detail_image") is False


def _claim(text: str, kind: str = "feature", subject: str = "this", confidence: str = "high", seg: int = 0) -> dict[str, Any]:
    cleaned = material.clean_claim({"text": text, "kind": kind, "subject": subject, "confidence": confidence}, image_index=0, segment_index=seg)
    assert cleaned is not None
    return cleaned


def test_clean_claim_drops_bare_specs_and_treats_unknown_kind_as_hype() -> None:
    for spec in ("12V", "2000mAh", "84×48×40mm", "1.5 kg"):
        assert material.clean_claim({"text": spec, "kind": "feature", "subject": "this"}, image_index=0, segment_index=0) is None
    assert material.clean_claim({"text": "  ", "kind": "feature"}, image_index=0, segment_index=0) is None
    odd = material.clean_claim({"text": "国际大牌品质", "kind": "slogan", "subject": "this", "confidence": "high"}, image_index=1, segment_index=2)
    assert odd is not None and odd["kind"] == "hype"
    assert material.clean_claim({"text": "21+1档扭力调节", "kind": "feature", "subject": "this"}, image_index=0, segment_index=0) is not None


def test_summarize_keeps_this_product_dedupes_and_is_conservative() -> None:
    read = {
        "facts": [
            _claim("无刷电机"),
            _claim("无刷 电机", seg=3),  # 同一句话,另一段图又出现
            _claim("持久续航", kind="claim"),
            _claim("持久续航", kind="hype", seg=5),  # 两段读法不同 → 按更保守的算
            _claim("超强动力 秒杀同类", kind="hype"),
            _claim("适配牧田电池", subject="other"),
            _claim("金属齿轮箱", confidence="low"),
        ],
        "segments_read": 9,
        "cost_usd": 0.004,
    }
    out = material.summarize(read)
    assert [r["text"] for r in out["features"]] == ["无刷电机"]
    assert out["claims"] == []
    assert [r["text"] for r in out["hype"]] == ["持久续航", "超强动力 秒杀同类"]
    assert out["dropped"] == {"other_product": 1, "low_confidence": 1}
    assert out["segments_read"] == 9 and out["cost_usd"] == 0.004


def test_attribute_items_write_features_and_claims_but_never_hype() -> None:
    summary = material.summarize({"facts": [_claim("LED 照明灯"), _claim("正反转"), _claim("小巧便携", kind="claim"), _claim("工业级", kind="hype")]})
    items = material.attribute_items(summary)
    assert [(i["attribute_key"], i["attribute_value_text"]) for i in items] == [
        ("sqh_feature_01", "LED 照明灯"),
        ("sqh_feature_02", "正反转"),
        ("sqh_claim_01", "小巧便携"),
    ]
    for item in items:
        parsed = ProductKnowledgeAttributeItem(**item)  # 过得了 K 的校验
        assert parsed.source == material.MATERIAL_SOURCE and parsed.requires_review is False


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (400, 600), "white").save(buffer, "PNG")
    return buffer.getvalue()


def test_collect_reads_every_segment_with_the_claims_prompt() -> None:
    prompts: list[str] = []

    class FakeRouter:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            prompts.append(kwargs["payload"]["messages"][0]["content"][0]["text"])
            return {"facts": [{"text": "LED 照明灯", "kind": "feature", "subject": "this", "confidence": "high"}]}

    capture = {"title_zh": "12V 手电钻", "skus": [{"name": "裸机"}], "attributes": [], "detail_images": ["https://cbu01.alicdn.com/img/a.jpg"]}
    out = material.collect(None, capture, download=lambda url: _png(), router_factory=lambda db: FakeRouter(), reader_role="fast", triage=False)
    assert prompts and all("卖点说法" in p and "12V 手电钻" in p for p in prompts)
    assert [r["text"] for r in out["features"]] == ["LED 照明灯"]
    assert out["read_at"]
