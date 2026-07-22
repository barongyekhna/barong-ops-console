"""运营者作图方案编辑(2026-07-22):模板 SEO 兜底 + 预设标注层契约。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.modules.k_series.product_knowledge.brief_operator_edits import (
    MAX_OPERATOR_OVERLAY_FIELDS,
    _template_prompt_and_seo,
    build_operator_brief_image,
    build_preset_overlay,
)

pytestmark = pytest.mark.unit


def test_template_seo_never_leaves_fields_empty() -> None:
    product = SimpleNamespace(
        product_name_en="Cheese Stress Ball",
        primary_keyword="stress ball",
    )
    out = _template_prompt_and_seo(product, "on an office desk next to a laptop")
    for field in ("prompt", "title", "alt", "caption", "description"):
        assert out[field].strip(), field


def test_operator_brief_image_carries_seo_and_reference() -> None:
    seo = {
        "prompt": "p",
        "title": "t",
        "alt": "a",
        "caption": "c",
        "description": "d",
    }
    spec = build_operator_brief_image(
        position=9,
        placement="description",
        scene="hand squeezing",
        prompt_and_seo=seo,
        reference_asset_id="11111111-1111-1111-1111-111111111111",
    )
    assert spec["position"] == 9
    assert spec["placement"] == "description"
    assert spec["role"] == "proof_scene"
    assert spec["operator_added"] is True
    assert spec["reference_asset_id"]
    for field in ("title", "alt", "caption", "description"):
        assert spec[field]


def test_preset_overlay_passes_contract_and_limits() -> None:
    overlay = build_preset_overlay(["weight", "material"])
    assert overlay["role"] == "feature_callout"
    assert len(overlay["items"]) == 2
    for item in overlay["items"]:
        assert item["type"] == "callout"
        assert 0 <= item["text_anchor"]["x"] <= 1
        assert 0 <= item["anchor"]["y"] <= 1

    with pytest.raises(ValueError):
        build_preset_overlay([])
    with pytest.raises(ValueError):
        build_preset_overlay(["weight"] * (MAX_OPERATOR_OVERLAY_FIELDS + 1))
    with pytest.raises(ValueError):
        build_preset_overlay(["not_a_field"])
