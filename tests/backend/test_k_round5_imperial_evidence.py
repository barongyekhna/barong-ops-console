from __future__ import annotations

import pytest

from backend.app.modules.k_series.product_knowledge.faq_research import (
    answer_spec_number_matches,
    structured_spec_number_tokens,
    validate_generated_faq,
)
from backend.app.modules.k_series.product_knowledge.router import (
    SellingPointBullet,
    _selling_point_support_error,
    _structured_spec_evidence_snapshot,
)


pytestmark = pytest.mark.unit


def _metric_specs() -> dict:
    return {
        "dimensions": {
            "length": {"value": 17},
            "width": {"value": 17},
            "height": {"value": 12},
            "unit": "cm",
        },
        "packed_dimensions": {
            "value": [17, 17, 12],
            "raw_value": "17 × 17 × 12 cm",
            "unit": "cm",
            "source_label": "Packed dimensions",
        },
        "millimetre_length": {"value": 160, "unit": "mm"},
        "weight": {"value": 0.78, "raw_value": "780 g", "unit": "kg"},
        "shipping_weight": {"value": 720, "unit": "g"},
        "capacity": {"value": 1.4, "unit": "L"},
    }


def test_verified_metric_specs_add_buyer_display_equivalent_tokens() -> None:
    tokens = structured_spec_number_tokens(_metric_specs())

    assert {"6.7", "4.7"}.issubset(tokens)  # cm -> in
    assert "6.3" in tokens  # mm -> in
    assert "1.7" in tokens  # explicit kg -> lb
    assert "25.4" in tokens  # g -> oz
    assert "1.5" in tokens  # L -> qt
    assert {"17", "12", "160", "0.78", "780", "720", "1.4"}.issubset(
        tokens
    )


def test_selling_point_accepts_equivalent_inches_but_rejects_invented_number() -> None:
    snapshot = _structured_spec_evidence_snapshot(
        _metric_specs(),
        "packed_dimensions",
    )
    assert snapshot is not None
    assert snapshot["unit"] == "cm"

    supported = _selling_point_support_error(
        SellingPointBullet(
            category="size",
            text="Packs down to 6.7 x 6.7 x 4.7 inches.",
            importance_score=1,
            evidence="spec:packed_dimensions",
        ),
        snapshot,
    )
    invented = _selling_point_support_error(
        SellingPointBullet(
            category="size",
            text="Packs down to 8.2 x 6.7 x 4.7 inches.",
            importance_score=1,
            evidence="spec:packed_dimensions",
        ),
        snapshot,
    )

    assert supported is None
    assert invented == "Claim contains numbers absent from the current evidence: 8.2"

    weight_snapshot = _structured_spec_evidence_snapshot(_metric_specs(), "weight")
    assert weight_snapshot is not None
    assert weight_snapshot["unit"] == "kg"
    assert (
        _selling_point_support_error(
            SellingPointBullet(
                category="weight",
                text="Weighs 1.7 lb for transport.",
                importance_score=1,
                evidence="spec:weight",
            ),
            weight_snapshot,
        )
        is None
    )


def test_faq_recognizes_equivalent_inches_as_spec_numbers_without_relaxing_gate() -> None:
    specs = _metric_specs()
    research = {
        "quality_ready": True,
        "sources": [
            {
                "id": "packing",
                "question": "How should I pack this cookware set?",
                "snippet": "Keep the nested set secure inside its storage bag.",
                "intent_cluster": "travel_logistics",
            }
        ],
    }
    assert answer_spec_number_matches(
        "Its packed footprint is 6.7 x 6.7 x 4.7 inches.",
        specs,
    ) == {"6.7", "4.7"}

    equivalent = validate_generated_faq(
        {
            "page_faq": [
                {
                    "question": "How should I pack this cookware set?",
                    "answer": "Secure its 6.7-inch packed footprint in the storage bag.",
                    "evidence_refs": ["packing"],
                }
            ]
        },
        research,
        structured_specs=specs,
    )
    invented = validate_generated_faq(
        {
            "page_faq": [
                {
                    "question": "How should I pack this cookware set?",
                    "answer": "Secure its 8.2-inch packed footprint in the storage bag.",
                    "evidence_refs": ["packing"],
                }
            ]
        },
        research,
        structured_specs=specs,
    )

    assert equivalent["page_faq"] == []
    assert equivalent["faq_quality"]["dropped"][0]["reason"] == (
        "answer_repeats_product_specification_number"
    )
    assert invented["page_faq"] == []
    assert invented["faq_quality"]["dropped"][0]["reason"] == (
        "answer_contains_unsupported_number"
    )
