"""节日轻氛围(2026-07-23):场景/描述图注入,主图与变体主图纯净。"""

from __future__ import annotations

import pytest

from backend.app.modules.k_series.product_knowledge.image_render_jobs import (
    _festival_block,
)
from backend.app.modules.k_series.product_knowledge.schemas import (
    ProductKnowledgeCreate,
)

pytestmark = pytest.mark.unit


def test_festival_block_only_for_known_styles() -> None:
    assert "Halloween" in _festival_block("halloween")
    assert "pumpkin" in _festival_block("halloween")
    assert _festival_block(None) == ""
    assert _festival_block("none") == ""
    assert _festival_block("unknown") == ""


def test_festival_block_never_touches_product_or_text() -> None:
    block = _festival_block("christmas")
    assert "physically unchanged" in block or "remain physically unchanged" in block
    assert "never as text" in block or "never as\ntext" in block.replace("  ", " ")
    assert "background" in block.lower()


def test_schema_validates_festival_style() -> None:
    p = ProductKnowledgeCreate(
        product_name_en="X", raw_input_text="d", target_market="US",
        festival_style="Halloween",
    )
    assert p.festival_style == "halloween"
    blank = ProductKnowledgeCreate(
        product_name_en="X", raw_input_text="d", target_market="US",
        festival_style="none",
    )
    assert blank.festival_style is None
    with pytest.raises(ValueError, match="不支持"):
        ProductKnowledgeCreate(
            product_name_en="X", raw_input_text="d", target_market="US",
            festival_style="diwali_typo",
        )
