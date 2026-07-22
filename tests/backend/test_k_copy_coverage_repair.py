"""文案两道新保险(2026-07-23):确定性盒内文案 + 覆盖率口径。"""

from __future__ import annotations

import pytest

from backend.app.modules.k_series.product_knowledge.workflow_engine import (
    _keyword_coverage_receipt,
    _pack_aware_box_section,
)

pytestmark = pytest.mark.unit


def test_pack_aware_box_overrides_ai_text_for_quantity_variants() -> None:
    result = {
        "product_page_copy": {
            "chunk_sections": [
                {"heading": "Feel the squeeze", "body": "..."},
                {"heading": "What's in the box", "body": "Your box includes one stress ball."},
            ]
        }
    }
    out = _pack_aware_box_section(
        result, pack_quantities=[1, 2], package_includes=["stress ball"]
    )
    box = out["product_page_copy"]["chunk_sections"][1]["body"]
    assert "1 Pack option includes 1 stress ball" in box
    assert "2 Packs option includes 2 stress balls" in box
    assert "one stress ball." not in box


def test_pack_aware_box_untouched_for_single_quantity() -> None:
    result = {
        "product_page_copy": {
            "chunk_sections": [
                {"heading": "What's in the box", "body": "Your box includes one stress ball."}
            ]
        }
    }
    out = _pack_aware_box_section(
        result, pack_quantities=[1], package_includes=["stress ball"]
    )
    assert out["product_page_copy"]["chunk_sections"][0]["body"] == (
        "Your box includes one stress ball."
    )


def test_pack_aware_box_appends_section_when_missing() -> None:
    out = _pack_aware_box_section(
        {"product_page_copy": {"chunk_sections": []}},
        pack_quantities=[1, 2],
        package_includes=[],
    )
    chunks = out["product_page_copy"]["chunk_sections"]
    assert chunks and chunks[-1]["heading"] == "What's in the box"


def test_coverage_receipt_flags_missing_top_keywords() -> None:
    receipt = _keyword_coverage_receipt(
        {"product_page_copy": {"chunk_sections": [{"heading": "A squeeze ball", "body": "x"}]}},
        ["squeeze ball", "stress ball for adults"],
    )
    assert receipt["warning"] is True
    assert "stress ball for adults" in receipt["missing_keywords"]
