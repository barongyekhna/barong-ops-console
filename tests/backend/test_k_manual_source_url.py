"""K 手动建品的可选货源链接:schema 校验 + 建品后自动灌入 W-S 货源库。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_schema_accepts_and_normalizes_optional_source_url() -> None:
    from backend.app.modules.k_series.product_knowledge.schemas import (
        ProductKnowledgeCreate,
    )

    base = {"raw_input_text": "test product"}
    assert ProductKnowledgeCreate(**base).source_url is None
    assert ProductKnowledgeCreate(**base, source_url="").source_url is None
    assert ProductKnowledgeCreate(**base, source_url="   ").source_url is None
    ok = ProductKnowledgeCreate(
        **base, source_url=" https://detail.1688.com/offer/x.html "
    )
    assert ok.source_url == "https://detail.1688.com/offer/x.html"


def test_schema_rejects_non_http_source_url() -> None:
    from pydantic import ValidationError

    from backend.app.modules.k_series.product_knowledge.schemas import (
        ProductKnowledgeCreate,
    )

    with pytest.raises(ValidationError):
        ProductKnowledgeCreate(
            raw_input_text="test", source_url="detail.1688.com/offer/x.html"
        )
    with pytest.raises(ValidationError):
        ProductKnowledgeCreate(raw_input_text="test", source_url="javascript:alert(1)")


def test_create_route_wires_fail_safe_source_autofill() -> None:
    import inspect

    from backend.app.modules.k_series.product_knowledge import router

    source = inspect.getsource(router.product_knowledge_create)
    assert "fill_source_if_absent" in source
    # 建品成功之后才灌货源,且包在 try 里(货源失败不影响建品)
    assert source.index("create_product") < source.index("fill_source_if_absent")
    tail = source[source.index("fill_source_if_absent") - 200:]
    assert "except Exception" in tail
