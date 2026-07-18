from __future__ import annotations

import pytest

from backend.app.modules.k_series.product_knowledge.evidence_guard import (
    TitleEvidenceConsistencyError,
    enforce_package_evidence_consistency,
    enforce_title_evidence_consistency,
    reconcile_title_numeric_claims,
)


pytestmark = pytest.mark.unit


def _people_specs(value: str = "2-3 people") -> dict:
    return {
        "schema_version": "1.0",
        "source": {"platform": "1688"},
        "additional_specs": [
            {
                "key": "supplier_attribute_ef381aa201",
                "label": "\u9002\u7528\u4eba\u6570",
                "source_label": "\u9002\u7528\u4eba\u6570",
                "value": value,
                "raw_value": value,
                "value_en": "2-3 people",
            }
        ],
    }


def _guard(title: str, specs: dict | None) -> dict:
    return enforce_title_evidence_consistency(
        {"seo": {"title": title, "h1": title}},
        product_name=title,
        product_type="cookware",
        category_name="Camping Cookware",
        site_brand="Barong Yekhna",
        approved_selling_points={"bullets": []},
        structured_specs=specs,
    )


def test_people_claim_mismatch_is_rewritten_from_verified_specs() -> None:
    guarded = _guard(
        "Portable Camping Cookware for 1-2 People",
        _people_specs(),
    )

    assert guarded["seo"] == {
        "title": "Portable Camping Cookware for 2-3 People",
        "h1": "Portable Camping Cookware for 2-3 People",
    }
    assert guarded["evidence_consistency"]["numeric_reconciled_fields"] == [
        "h1",
        "title",
    ]


def test_people_claim_without_corresponding_spec_is_deleted() -> None:
    guarded = _guard("Portable Camping Cookware for 1-2 People", {})

    assert guarded["seo"] == {
        "title": "Portable Camping Cookware",
        "h1": "Portable Camping Cookware",
    }


def test_people_claim_matching_spec_is_byte_for_byte_unchanged() -> None:
    title = "Portable Camping Cookware for 2-3 People"
    guarded = _guard(title, _people_specs())

    assert guarded["seo"] == {"title": title, "h1": title}
    assert guarded["evidence_consistency"]["status"] == "passed"
    assert guarded["evidence_consistency"]["numeric_reconciled_fields"] == []


def test_piece_and_capacity_claims_are_rewritten_or_removed_from_specs() -> None:
    specs = {
        "piece_count": {"value": 7, "raw_value": "7 pieces"},
        "capacity_pot": {"value": 1.4, "unit": "L", "raw_value": "1.4 L"},
    }

    assert reconcile_title_numeric_claims(
        "5-Piece Camping Cookware 2 qt Set",
        specs,
    ) == "7-Piece Camping Cookware 1.4 L Set"
    assert reconcile_title_numeric_claims(
        "5-Piece Camping Cookware 2 qt Set",
        {},
    ) == "Camping Cookware Set"


def test_package_gate_accepts_verified_piece_count_without_package_list() -> None:
    guarded = enforce_package_evidence_consistency(
        {"seo": {"title": "7-Piece Camping Cookware Set"}},
        structured_specs={"piece_count": {"value": 7}},
    )

    assert guarded["seo"]["title"] == "7-Piece Camping Cookware Set"
    assert guarded["package_evidence_consistency"]["verified_piece_count"] == 7

    rewritten = enforce_package_evidence_consistency(
        {"seo": {"title": "5-Piece Camping Cookware Set"}},
        structured_specs={"piece_count": {"value": 7}},
    )
    assert rewritten["seo"]["title"] == "7-Piece Camping Cookware Set"


def test_supplier_chinese_people_claim_uses_hashed_additional_spec_label() -> None:
    assert reconcile_title_numeric_claims(
        "\u6237\u5916\u9732\u8425\u9505\u51771-2\u4eba\u4fbf\u643a\u5957\u88c5",
        _people_specs("2-3\u4eba"),
    ) == "\u6237\u5916\u9732\u8425\u9505\u51772-3\u4eba\u4fbf\u643a\u5957\u88c5"

    assert reconcile_title_numeric_claims(
        "\u9002\u75281-2\u4eba \u6237\u5916\u9505\u5177",
        {},
    ) == "\u6237\u5916\u9505\u5177"


def test_chinese_liter_capacity_claim_is_reconciled() -> None:
    assert reconcile_title_numeric_claims(
        "\u6237\u5916\u9505\u51771.5\u5347\u5957\u88c5",
        {"capacity_pot": {"value": 1.4, "unit": "L"}},
    ) == "\u6237\u5916\u9505\u51771.4L\u5957\u88c5"


def test_piece_count_conflict_and_multiple_capacities_fail_closed() -> None:
    with pytest.raises(TitleEvidenceConsistencyError, match="disagree or are ambiguous"):
        reconcile_title_numeric_claims(
            "7-Piece Camping Cookware Set",
            {"piece_count": {"value": 7}},
            package_includes=["Pot", "Lid"],
        )

    with pytest.raises(TitleEvidenceConsistencyError, match="ambiguous"):
        reconcile_title_numeric_claims(
            "2 L Camping Cookware Set",
            {
                "capacity_pot": {"value": 1.4, "unit": "L"},
                "capacity_pan": {"value": 0.8, "unit": "L"},
            },
        )
