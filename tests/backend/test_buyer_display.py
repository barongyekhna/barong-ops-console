from __future__ import annotations

import pytest

from backend.app.modules.k_series.product_knowledge.buyer_display import (
    buyer_display_structured_specs,
    buyer_safe_tree,
    cm_to_inches,
    contains_cjk,
    g_to_ounces,
    imperial_dimensions_mm,
    imperial_measurement,
    imperialize_text,
    kg_to_pounds,
    liters_to_quarts,
)


pytestmark = pytest.mark.unit


def test_public_imperial_conversions_share_one_decimal_rounding() -> None:
    assert cm_to_inches(16) == "6.3"
    assert kg_to_pounds(0.72) == "1.6"
    assert g_to_ounces(350) == "12.3"
    assert liters_to_quarts(1.4) == "1.5"
    assert imperial_dimensions_mm("160×160×110 mm") == "6.3 × 6.3 × 4.3 in"
    assert imperialize_text("Measures 160×160×110 mm and weighs 720 g.") == (
        "Measures 6.3 × 6.3 × 4.3 in and weighs 25.4 oz."
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Measures 10-20 cm.", "Measures 3.9–7.9 in."),
        ("Weight range: 0.5 to 1 kg.", "Weight range: 1.1–2.2 lb."),
        ("Weight range: 0.1–0.2 kg.", "Weight range: 3.5–7.1 oz."),
        ("Adjusts from 10 cm to 20 cm.", "Adjusts from 3.9–7.9 in."),
        ("Net weight: .5 kg.", "Net weight: 1.1 lb."),
        ("Net weight: 1,000 g.", "Net weight: 35.3 oz."),
    ],
)
def test_imperialize_text_converts_complete_ranges(
    source: str,
    expected: str,
) -> None:
    assert imperialize_text(source) == expected


def test_imperial_measurement_converts_separate_range_value_and_unit() -> None:
    assert imperial_measurement("0.5–1", "kg") == ("1.1–2.2", "lb")
    # A range crossing the one-pound threshold stays in one output unit.
    assert imperial_measurement("0.2 to 0.5", "kg") == ("0.4–1.1", "lb")


@pytest.mark.parametrize(
    "source",
    [
        "Length: 3 m",
        "Length is listed in meters.",
        "Capacity: 20 cl",
        "Capacity is marked ML.",
        "Fabric weight: 100 g/m²",
        "Area: 10 cm²",
        "Volume: 10 cm^3",
        "Fractional weight: 1/2 kg",
        "Converted 10 cm but another side is 2 meters.",
    ],
)
def test_imperialize_text_fails_closed_on_remaining_metric_units(source: str) -> None:
    assert imperialize_text(source) is None


@pytest.mark.parametrize(
    "source",
    [
        "中文",
        "ひらがな",
        "カタカナ",
        "한글",
        "\U00020000",
        "&#x4E2D;",
        "&#20013;",
        "&colon;&#x65E5;",
    ],
)
def test_contains_cjk_covers_asian_scripts_extensions_and_html_entities(
    source: str,
) -> None:
    assert contains_cjk(source) is True
    assert imperialize_text(source) is None


def test_buyer_safe_tree_drops_whole_unsafe_rows_and_logs_paths_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = {
        "page_faq": [
            {"question": "How should I store it?", "answer": "保持干燥"},
            {"question": "How much clearance?", "answer": "Keep 2 meters clear."},
            {"question": "Can it nest?", "answer": "Yes, it nests compactly."},
        ]
    }

    with caplog.at_level("WARNING"):
        projected = buyer_safe_tree(payload, field_path="marketing_copy")

    assert projected == {
        "page_faq": [
            {"question": "Can it nest?", "answer": "Yes, it nests compactly."}
        ]
    }
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "marketing_copy.page_faq[0]" in messages
    assert "marketing_copy.page_faq[1]" in messages
    assert "保持干燥" not in messages
    assert "Keep 2 meters clear" not in messages


def test_buyer_display_rows_are_english_imperial_and_fail_closed() -> None:
    specs = {
        "dimensions": {
            "length": {"value": 16},
            "width": {"value": 16},
            "height": {"value": 11},
            "unit": "cm",
        },
        "weight": {"value": 0.72, "unit": "kg"},
        "material": {"value": "铝合金"},
        "additional_specs": [
            {
                "key": "capacity",
                "label": "主锅容量",
                "label_en": "Main Pot Capacity",
                "value": "1.4升",
                "value_en": "1.4 L",
            },
            {
                "key": "untranslated",
                "label": "涂层",
                "value": "不粘涂层",
            },
        ],
    }

    display = buyer_display_structured_specs(specs)

    assert display["language"] == "en"
    assert display["unit_system"] == "imperial"
    assert display["rows"] == [
        {
            "path": "dimensions.length",
            "label": "Length",
            "display_value": "6.3",
            "display_unit": "in",
        },
        {
            "path": "dimensions.width",
            "label": "Width",
            "display_value": "6.3",
            "display_unit": "in",
        },
        {
            "path": "dimensions.height",
            "label": "Height",
            "display_value": "4.3",
            "display_unit": "in",
        },
        {
            "path": "weight",
            "label": "Weight",
            "display_value": "1.6",
            "display_unit": "lb",
        },
        {
            "path": "additional_specs.capacity",
            "label": "Main Pot Capacity",
            "display_value": "1.5 qt",
            "display_unit": None,
        },
    ]


def test_buyer_spec_rows_convert_string_ranges_and_log_skipped_metric_paths(
    caplog: pytest.LogCaptureFixture,
) -> None:
    specs = {
        "weight": {"value": "0.5–1", "unit": "kg"},
        "dimensions": {"length": {"value": 2}, "unit": "m"},
        "additional_specs": [
            {
                "key": "residual_capacity",
                "label_en": "Reservoir Capacity",
                "value_en": "20",
                "unit": "cl",
            }
        ],
    }

    with caplog.at_level("WARNING"):
        display = buyer_display_structured_specs(specs)

    assert display["rows"] == [
        {
            "path": "weight",
            "label": "Weight",
            "display_value": "1.1–2.2",
            "display_unit": "lb",
        }
    ]
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "dimensions.length" in messages
    assert "additional_specs[0]" in messages
    assert "Reservoir Capacity" not in messages
