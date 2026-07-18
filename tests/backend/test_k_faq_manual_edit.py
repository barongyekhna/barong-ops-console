"""Manual FAQ editing endpoint: single-source page_faq + schema eligibility."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

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
    from backend.app.modules.k_series.product_knowledge.faq_research import (
        is_faq_question_candidate,
        is_faq_text_brand_safe,
    )

    assert contains_cjk("这个锅安全吗?") is True
    assert contains_cjk("Is this pot safe?") is False
    assert not "Best cookware 2026 review".endswith("?")
    assert "What fuel does the stove use?".endswith("?")
    assert is_faq_question_candidate("Can PTFE cookware be cleaned easily?") is True
    assert is_faq_question_candidate("Is TrailForge cookware reliable?") is False
    assert is_faq_text_brand_safe("Dry ABS and PVC parts before storage.") is True
    assert is_faq_text_brand_safe("Store cookware in a dry place.") is True
    assert is_faq_text_brand_safe("Store it like TrailForge cookware.") is False
    assert is_faq_text_brand_safe("Store it like Vango cookware.") is False


class _FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commit_count = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commit_count += 1


def _manual_route_setup(monkeypatch: pytest.MonkeyPatch) -> tuple[object, _FakeDb]:
    from backend.app.modules.k_series.product_knowledge import router as router_module

    product = SimpleNamespace(marketing_copy_json={})
    monkeypatch.setattr(router_module, "_scope_context", lambda _request: object())
    monkeypatch.setattr(
        router_module,
        "get_product",
        lambda _db, **_kwargs: product,
    )
    return product, _FakeDb()


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("Has TrailForge cookware been tested?", "Use normal care."),
        ("Has this cookware been tested?", "Store it like Vango cookware."),
        ("Can Tritan plastic be used for food?", "Use normal care."),
        ("Has this cookware been tested?", "Cordura fabric handles abrasion."),
        (" ", "Use normal care."),
        ("Has this cookware been tested?", " "),
    ],
)
def test_manual_faq_route_rejects_brands_and_trimmed_empty_fields(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    answer: str,
) -> None:
    from backend.app.modules.k_series.product_knowledge import router as router_module

    product, db = _manual_route_setup(monkeypatch)
    payload = router_module.ProductFaqUpdateRequest(
        items=[{"question": question, "answer": answer}]
    )

    with pytest.raises(HTTPException) as exc_info:
        router_module.product_knowledge_update_faq(
            uuid4(),
            payload,
            request=SimpleNamespace(),  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
            user=SimpleNamespace(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "FAQ_MANUAL_VALIDATION_FAILED"
    assert product.marketing_copy_json == {}
    assert db.added == []
    assert db.commit_count == 0


def test_manual_faq_route_preserves_valid_has_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.modules.k_series.product_knowledge import router as router_module

    product, db = _manual_route_setup(monkeypatch)
    payload = router_module.ProductFaqUpdateRequest(
        items=[
            {
                "question": "Has this cookware been tested before a trip?",
                "answer": "Inspect and test each piece before leaving home.",
            }
        ]
    )

    response = router_module.product_knowledge_update_faq(
        uuid4(),
        payload,
        request=SimpleNamespace(),  # type: ignore[arg-type]
        db=db,  # type: ignore[arg-type]
        user=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert response.faq_schema_eligible is True
    assert response.page_faq[0]["question"] == (
        "Has this cookware been tested before a trip?"
    )
    assert product.marketing_copy_json["faq_quality"]["eligible_for_schema"] is True
    assert db.commit_count == 1


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
