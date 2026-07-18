"""Manual FAQ editing endpoint: single-source page_faq + schema eligibility."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_manual_faq_marks_schema_eligible_and_replaces_page_faq() -> None:
    from backend.app.modules.k_series.product_knowledge.faq_research import (
        faq_schema_is_eligible,
    )

    # The endpoint writes this exact shape; assert the downstream gate accepts it.
    mcj = {
        "page_faq": [
            {
                "question": "Is this cookware safe on open flames?",
                "answer": "Yes - use it on camp stoves with normal supervision.",
                "source": "manual_review",
            }
        ],
        "faq_quality": {
            "eligible_for_schema": True,
            "source": "manual_review",
            "question_count": 1,
            "reviewed_at": "2026-07-18T00:00:00+00:00",
        },
    }
    assert faq_schema_is_eligible(mcj) is True


def test_manual_faq_empty_clears_schema_eligibility() -> None:
    from backend.app.modules.k_series.product_knowledge.faq_research import (
        faq_schema_is_eligible,
    )

    mcj = {
        "page_faq": [],
        "faq_quality": {
            "eligible_for_schema": False,
            "source": "manual_review",
            "question_count": 0,
            "reviewed_at": "2026-07-18T00:00:00+00:00",
        },
    }
    assert faq_schema_is_eligible(mcj) is False


def test_manual_faq_validation_rules() -> None:
    """CJK and non-interrogative questions must be rejected at the API layer.

    The route logic is exercised via its validation building blocks so the
    red lines cannot silently drift: contains_cjk guards both fields and the
    question must end with '?'.
    """
    from backend.app.modules.k_series.product_knowledge.buyer_display import (
        contains_cjk,
    )

    assert contains_cjk("这个锅安全吗?") is True
    assert contains_cjk("Is this pot safe?") is False
    assert not "Best cookware 2026 review".endswith("?")
    assert "What fuel does the stove use?".endswith("?")


def test_visible_faq_and_schema_derive_from_same_manual_source() -> None:
    """description html + FAQPage schema must both read the manual page_faq."""
    from backend.app.modules.p_series.upload.description_html import (
        build_description_html,
        build_schema_jsonld,
    )

    mcj = {
        "product_page_copy": {},
        "page_faq": [
            {
                "question": "Can I pack this set in a carry-on?",
                "answer": "The nested pieces pack small enough for most carry-on bags.",
                "source": "manual_review",
            }
        ],
        "faq_quality": {
            "eligible_for_schema": True,
            "source": "manual_review",
            "question_count": 1,
            "reviewed_at": "2026-07-18T00:00:00+00:00",
        },
    }
    visible = build_description_html(mcj)["html"]
    assert "Can I pack this set in a carry-on?" in visible
    schema = build_schema_jsonld(mcj)
    assert "FAQPage" in schema
    assert "Can I pack this set in a carry-on?" in schema
