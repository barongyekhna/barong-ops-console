"""上品前三件套:关键词谷歌富化 + 手动参考图 + 契约完整性。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_metrics_reason_text_is_human_readable() -> None:
    from backend.app.modules.k_series.product_knowledge.google_keyword_metrics import (
        metrics_reason_text,
    )

    line = metrics_reason_text(
        {
            "avg_monthly_searches": 22200,
            "competition": "HIGH",
            "cpc_low_usd": 1.35,
            "cpc_high_usd": 6.55,
        }
    )
    assert "22,200" in line and "HIGH" in line and "$1.35-6.55" in line
    assert metrics_reason_text({}).startswith("[Google] 月搜 -")


def test_keyword_enrichment_is_wired_fail_safe() -> None:
    import inspect

    from backend.app.modules.k_series.product_knowledge import workflow_engine

    source = inspect.getsource(workflow_engine.KProductKnowledgeWorkflowEngine._optimize_keywords)
    assert "fetch_keyword_metrics" in source
    assert "failed_open" in source  # 富化失败绝不阻塞关键词管线
    assert source.index("fetch_keyword_metrics") < source.index("_upsert_keywords")


def test_offer_id_extraction() -> None:
    from backend.app.modules.k_series.product_knowledge.manual_reference import (
        extract_offer_id,
    )

    assert (
        extract_offer_id("https://detail.1688.com/offer/770945232328.html?spm=x")
        == "770945232328"
    )
    assert extract_offer_id("https://example.com/foo") is None
    assert extract_offer_id(None) is None


def test_manual_reference_wired_after_create() -> None:
    import inspect

    from backend.app.modules.k_series.product_knowledge import router

    source = inspect.getsource(router.product_knowledge_create)
    assert "attach_manual_reference_image" in source
    tail = source[source.index("attach_manual_reference_image") - 300 :]
    assert "except Exception" in tail  # 参考图失败绝不阻塞建品


def test_create_schema_accepts_reference_image_url() -> None:
    from pydantic import ValidationError

    from backend.app.modules.k_series.product_knowledge.schemas import (
        ProductKnowledgeCreate,
    )

    ok = ProductKnowledgeCreate(
        raw_input_text="x",
        reference_image_url=" https://cbu01.alicdn.com/img/abc.jpg ",
    )
    assert ok.reference_image_url == "https://cbu01.alicdn.com/img/abc.jpg"
    with pytest.raises(ValidationError):
        ProductKnowledgeCreate(raw_input_text="x", reference_image_url="ftp://x/y.jpg")
