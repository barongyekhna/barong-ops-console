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


def _guard(
    title: str,
    specs: dict | None,
    *,
    product_name: str | None = None,
) -> dict:
    return enforce_title_evidence_consistency(
        {"seo": {"title": title, "h1": title}},
        product_name=product_name or title,
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


def test_normalized_numeric_specs_supply_semantics_to_the_word_evidence_gate() -> None:
    people = _guard(
        "Camping Cookware for 2-3 People",
        {"capacity_people": {"value": {"min": 2, "max": 3}}},
        product_name="Portable Camping Cookware Set",
    )
    pieces = _guard(
        "7-Piece Camping Cookware Set",
        {"piece_count": {"value": 7}},
        product_name="Portable Camping Cookware Set",
    )

    assert people["seo"]["h1"] == "Camping Cookware for 2-3 People"
    assert pieces["seo"]["h1"] == "7-Piece Camping Cookware Set"


def test_hyphenated_person_claim_and_singular_noun_are_rewritten_grammatically() -> None:
    assert reconcile_title_numeric_claims(
        "Portable 1-Person Camping Cookware",
        {"capacity_people": {"value": {"min": 2, "max": 3}}},
    ) == "Portable 2-3-Person Camping Cookware"
    assert reconcile_title_numeric_claims(
        "Portable Cookware for 2 People",
        {"capacity_people": {"value": 1}},
    ) == "Portable Cookware for 1 Person"
    assert reconcile_title_numeric_claims(
        "Portable Cookware for 2 People",
        {"capacity_people": {"value": {"min": 2, "max": 2}}},
    ) == "Portable Cookware for 2 People"


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

    assert reconcile_title_numeric_claims(
        "500 ml Camping Bottle",
        {"capacity_bottle": {"value": 400, "unit": "mL"}},
    ) == "400 mL Camping Bottle"


def test_production_additional_specs_support_capacity_and_piece_count() -> None:
    specs = {
        "additional_specs": [
            {
                "key": "supplier_attribute_4a3cbca7b1",
                "label": "\u4e3b\u9505\u5bb9\u91cf",
                "label_en": "Main Pot Capacity",
                "value": "1.4\u5347",
                "value_en": "1.4 L",
                "raw_value": "1.4\u5347",
            }
        ]
    }
    assert reconcile_title_numeric_claims("2 L Pot", specs) == "1.4 L Pot"

    dict_specs = {
        "additional_specs": {
            "piece_count": {
                "label_en": "Number of Pieces",
                "value": 7,
                "raw_value": "7 pieces",
            }
        }
    }
    assert reconcile_title_numeric_claims(
        "5-Piece Camping Cookware",
        dict_specs,
    ) == "7-Piece Camping Cookware"


def test_missing_people_claim_cleans_adjacent_separators_and_qualifier() -> None:
    assert reconcile_title_numeric_claims(
        "Cookware \u2013 2 People \u2013 Compact Set",
        {},
    ) == "Cookware \u2013 Compact Set"
    assert reconcile_title_numeric_claims(
        "Cookware, suitable for 2 People, Compact Set",
        {},
    ) == "Cookware, Compact Set"


def test_numeric_claims_after_unspaced_punctuation_are_still_reconciled() -> None:
    assert reconcile_title_numeric_claims(
        "Cookware,2 People",
        {"capacity_people": {"value": 3}},
    ) == "Cookware,3 People"
    assert reconcile_title_numeric_claims(
        "Bottle,1.5L",
        {"capacity_bottle": {"value": 1.4, "unit": "L"}},
    ) == "Bottle,1.4L"
    assert reconcile_title_numeric_claims(
        "Cookware,7-Piece",
        {"piece_count": {"value": 5}},
    ) == "Cookware,5-Piece"
    assert reconcile_title_numeric_claims(
        "\u9505\u5177,2\u4eba",
        {"capacity_people": {"value": 3}},
    ) == "\u9505\u5177,3\u4eba"
    assert reconcile_title_numeric_claims(
        "Kit/5-Piece Set",
        {"piece_count": {"value": 7}},
    ) == "Kit/7-Piece Set"
    assert reconcile_title_numeric_claims(
        ".5 L Bottle",
        {"capacity_bottle": {"value": 0.4, "unit": "L"}},
    ) == "0.4 L Bottle"
    assert reconcile_title_numeric_claims(
        "2-L Bottle",
        {"capacity_bottle": {"value": 1.4, "unit": "L"}},
    ) == "1.4-L Bottle"


def test_non_piece_set_counts_are_not_rewritten_as_package_piece_counts() -> None:
    title = "Cookware Set of 2 Sizes"
    assert reconcile_title_numeric_claims(
        title,
        {"piece_count": {"value": 7}},
    ) == title


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


def test_conflicting_or_malformed_representations_in_one_spec_fail_closed() -> None:
    with pytest.raises(TitleEvidenceConsistencyError, match="malformed"):
        reconcile_title_numeric_claims(
            "Portable Cookware for 1-2 People",
            {
                "capacity_people": {
                    "value": "1-2 people",
                    "value_en": "2-3 people",
                    "raw_value": "2-3\u4eba",
                }
            },
        )

    with pytest.raises(TitleEvidenceConsistencyError, match="malformed"):
        reconcile_title_numeric_claims(
            "Portable Cookware for 1-2 People",
            {"capacity_people": {"value": {"min": 2, "max": "unknown"}}},
        )


def test_piece_range_cannot_be_hidden_by_the_package_copy_gate() -> None:
    with pytest.raises(TitleEvidenceConsistencyError, match="single verified integer"):
        enforce_package_evidence_consistency(
            {"seo": {"title": "7-Piece Camping Cookware Set"}},
            structured_specs={"piece_count": {"value": {"min": 5, "max": 7}}},
        )


def test_multiple_claims_or_wrong_capacity_subject_fail_closed() -> None:
    with pytest.raises(TitleEvidenceConsistencyError, match="multiple capacity"):
        reconcile_title_numeric_claims(
            "2 L Pot and 1 L Kettle",
            {"capacity_pot": {"value": 1.4, "unit": "L"}},
        )

    with pytest.raises(TitleEvidenceConsistencyError, match="does not match"):
        reconcile_title_numeric_claims(
            "2 L Pot",
            {"capacity_pan": {"value": 0.8, "unit": "L"}},
        )

    assert reconcile_title_numeric_claims(
        "2 L Pot",
        {
            "capacity_pot": {"value": 1.4, "unit": "L"},
            "capacity_pan": {"value": 0.8, "unit": "L"},
        },
    ) == "1.4 L Pot"

    with pytest.raises(TitleEvidenceConsistencyError, match="multiple piece"):
        reconcile_title_numeric_claims(
            "5-Piece Pot Set and 2-Piece Pan Set",
            {"piece_count": {"value": 7}},
        )

    assert reconcile_title_numeric_claims(
        "2 L Pot and 1 L Kettle",
        {},
    ) == "Pot and Kettle"


def test_capacity_subject_mapping_is_order_independent() -> None:
    same_capacity = {
        "capacity_pot": {"value": 1.4, "unit": "L"},
        "capacity_pan": {"value": 1.4, "unit": "L"},
    }
    assert reconcile_title_numeric_claims("1.5 L Pan", same_capacity) == "1.4 L Pan"
    assert reconcile_title_numeric_claims(
        "1.5 L Pan",
        dict(reversed(list(same_capacity.items()))),
    ) == "1.4 L Pan"

    with pytest.raises(TitleEvidenceConsistencyError, match="subject is ambiguous"):
        reconcile_title_numeric_claims(
            "2 L Pot and Pan Set",
            {"capacity_pan": {"value": 0.8, "unit": "L"}},
        )

    with pytest.raises(TitleEvidenceConsistencyError, match="malformed"):
        reconcile_title_numeric_claims(
            "1.5 L Pot",
            {
                "capacity_pot": {
                    "value": 1.4,
                    "unit": "L",
                    "raw_value": "1.4 qt",
                }
            },
        )


@pytest.mark.parametrize(
    "title",
    [
        "1/2 L Bottle",
        "Cookware for 1/2 People",
        "1/2-Piece Cookware Set",
        "1,000-Piece Cookware Set",
        "12.5-Piece Cookware Set",
        "Cookware for 1,007 People",
        "1,500 mL Bottle",
        "1,5 L Bottle",
        "Cookware for -2 People",
        "-1 L Bottle",
        "-5-Piece Cookware Set",
        "+2 People Cookware",
        "1\u00bd L Bottle",
        "Cookware between 2 and 3 People",
        "Cookware for up to 2 People",
        "Cookware for 2 or 3 People",
        "Cookware for 2+ People",
        "\u6237\u59161,5\u5347\u9505\u5177",
        "\u9002\u75281,5\u4eba\u9505\u5177",
    ],
)
def test_unsupported_number_forms_never_partially_corrupt_title(title: str) -> None:
    with pytest.raises(
        TitleEvidenceConsistencyError,
        match=(
            "fractional|piece-count|comma-formatted|negative|signed|"
            "Unicode fraction|qualified"
        ),
    ):
        reconcile_title_numeric_claims(title, {})
