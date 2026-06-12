import inspect
import json
from pathlib import Path

import pytest

from backend.app.modules.k_series.product_knowledge import k10_mock_adapter


ALLOWED_REVIEW_STATUSES = {"draft", "needs_review"}
REQUIRED_RESULT_FIELDS = {
    "adapter_name",
    "provider_name",
    "is_mock",
    "live_provider_called",
    "canonical_language",
    "review_status",
    "deepseek_structured_output_json",
    "ai_confidence_scores_json",
    "ai_warnings_json",
    "field_diff_json",
    "unit_payloads",
    "missing_field_hints",
    "errors",
    "warnings",
}
UNIT_PAYLOAD_TYPES = (
    "dimensions_json",
    "package_dimensions_json",
    "weight_json",
    "package_weight_json",
)
FORBIDDEN_SERIALIZED_TOKENS = (
    "api_key",
    "secret",
    "token",
    "bearer",
    "authorization",
    "provider_url",
    "webhook_url",
    "http://",
    "https://",
    "deepseek.com",
    "openai.com",
    "anthropic.com",
)
FORBIDDEN_SHAPE_FIELDS = (
    "provider_secret",
    "provider_request_id",
    "api_key",
    "secret",
    "token",
    "bearer",
    "authorization",
    "provider_url",
    "webhook_url",
    "model_call_id",
    "live_provider_request_id",
    "deepseek_request_id",
)


def _json_text(value):
    return json.dumps(value, sort_keys=True, default=str).lower()


def _assert_no_provider_data(value):
    serialized = _json_text(value)
    for token in FORBIDDEN_SERIALIZED_TOKENS:
        assert token not in serialized


def _valid_result():
    return json.loads(json.dumps(k10_mock_adapter.build_empty_mock_result()))


def _assert_invalid(validation):
    assert validation["is_valid"] is False
    assert validation["errors"] or validation["forbidden_fields_present"]


def test_import_boundary_is_module_local_without_runtime_dependencies():
    module_path = Path(inspect.getsourcefile(k10_mock_adapter) or "")
    module_source = inspect.getsource(k10_mock_adapter)
    lowered_source = module_source.lower()

    assert module_path.name == "k10_mock_adapter.py"
    assert k10_mock_adapter.__name__.endswith(".k10_mock_adapter")

    forbidden_runtime_fragments = (
        "from fastapi",
        "import fastapi",
        "from sqlalchemy",
        "import sqlalchemy",
        "from requests",
        "import requests",
        "from httpx",
        "import httpx",
        "os.environ",
        "dotenv",
        "subprocess",
        "http://",
        "https://",
        "deepseek live client",
    )
    for fragment in forbidden_runtime_fragments:
        assert fragment not in lowered_source

    for provider_module in ("openai", "anthropic"):
        assert f"import {provider_module}" not in lowered_source
        assert f"from {provider_module}" not in lowered_source

    for forbidden_output_key in ("provider_url", "webhook_url"):
        matching_lines = [
            line.strip()
            for line in lowered_source.splitlines()
            if forbidden_output_key in line
        ]
        assert matching_lines == [f'"{forbidden_output_key}",']


def test_build_mock_input_preserves_local_input_without_provider_data():
    requested_sections = ["canonical_product_fields", "unit_payloads"]
    raw_payload = {
        "sku": "K10D-R",
        "dimensions": {"value": 12, "unit": "cm"},
    }

    result = k10_mock_adapter.build_mock_input(
        raw_input_text="length 12 cm",
        raw_input_language="en",
        raw_input_payload_json=raw_payload,
        operator_notes="supplier supplied explicit dimensions",
        source_system="manual_review",
        requested_output_sections=requested_sections,
    )

    assert isinstance(result, dict)
    assert result["raw_input_text"] == "length 12 cm"
    assert result["raw_input_language"] == "en"
    assert result["raw_input_payload_json"] == raw_payload
    assert result["operator_notes"] == "supplier supplied explicit dimensions"
    assert result["source_system"] == "manual_review"
    assert result["requested_output_sections"] == requested_sections
    assert result["is_mock"] is True
    assert result["provider_name"] == "deepseek_mock"
    _assert_no_provider_data(result)


def test_build_empty_mock_result_has_complete_valid_mock_shape():
    result = k10_mock_adapter.build_empty_mock_result(
        source_text="source text",
        source_language="zh",
    )

    assert REQUIRED_RESULT_FIELDS <= set(result)
    assert result["is_mock"] is True
    assert result["live_provider_called"] is False
    assert result["provider_name"] == "deepseek_mock"
    assert result["review_status"] in ALLOWED_REVIEW_STATUSES
    assert result["source"]["raw_input_text"] == "source text"
    assert result["source"]["raw_input_language"] == "zh"

    assert set(result["unit_payloads"]) == set(UNIT_PAYLOAD_TYPES)
    assert set(result["deepseek_structured_output_json"]["unit_payloads"]) == set(
        UNIT_PAYLOAD_TYPES
    )
    for payload_type in UNIT_PAYLOAD_TYPES:
        assert result["unit_payloads"][payload_type] is None

    validation = k10_mock_adapter.validate_mock_result_shape(result)
    assert validation["is_valid"] is True
    assert validation["errors"] == []
    _assert_no_provider_data(result)


def test_build_mock_structured_output_is_deterministic_draft_only():
    mock_input = k10_mock_adapter.build_mock_input(
        raw_input_text="Net weight: 1.2 kg.",
        raw_input_language="en",
        raw_input_payload_json={
            "canonical_product_fields": {"title": "Human confirmed title"}
        },
        operator_notes="do not overwrite canonical fields",
        source_system="supplier_sheet",
        requested_output_sections=["canonical_product_fields", "field_diff_json"],
    )

    first = k10_mock_adapter.build_mock_structured_output(mock_input)
    second = k10_mock_adapter.build_mock_structured_output(mock_input)

    assert first == second
    assert first["is_mock"] is True
    assert first["live_provider_called"] is False
    assert first["review_status"] in ALLOWED_REVIEW_STATUSES
    assert first["source"]["raw_input_text"] == "Net weight: 1.2 kg."
    assert first["source"]["raw_input_language"] == "en"
    assert first["source"]["source_system"] == "supplier_sheet"
    assert first["source"]["operator_notes"] == "do not overwrite canonical fields"
    assert first["source"]["raw_input_payload_json"] == mock_input[
        "raw_input_payload_json"
    ]
    assert first["deepseek_structured_output_json"]["canonical_product_fields"] == {}
    assert first["field_diff_json"] == []
    assert "free_text_parsing_not_supported" in first["warnings"]
    assert k10_mock_adapter.validate_mock_result_shape(first)["is_valid"] is True
    _assert_no_provider_data(first)


@pytest.mark.parametrize("payload_type", UNIT_PAYLOAD_TYPES)
def test_build_unit_payload_draft_supports_current_payload_families(payload_type):
    provided_values = {"value": 7.5, "unit": "cm", "display_market": "US"}

    payload = k10_mock_adapter.build_unit_payload_draft(
        payload_type=payload_type,
        source_text="explicit local value",
        source_language="en",
        provided_values=provided_values,
    )

    unit_value = payload["unit_value_payload"]
    assert payload["payload_type"] == payload_type
    assert payload["review_status"] in ALLOWED_REVIEW_STATUSES
    assert payload["reviewer_corrected"] is False
    assert unit_value["original_value"] == 7.5
    assert unit_value["original_unit"] == "cm"
    assert unit_value["source_text"] == "explicit local value"
    assert unit_value["source_language"] == "en"
    assert unit_value["conversion_source"] == "ai_structured_from_provided_input"
    assert unit_value["review_status"] in ALLOWED_REVIEW_STATUSES
    assert unit_value["reviewer_corrected"] is False
    _assert_no_provider_data(payload)


@pytest.mark.parametrize(
    ("provided_values", "expected_error"),
    (
        ({"unit": "cm"}, "missing_value"),
        ({"value": 10}, "missing_unit"),
    ),
)
def test_build_unit_payload_draft_blocks_missing_value_or_unit(
    provided_values,
    expected_error,
):
    payload = k10_mock_adapter.build_unit_payload_draft(
        payload_type="dimensions_json",
        source_text="partial explicit local value",
        source_language="en",
        provided_values=provided_values,
    )

    unit_value = payload["unit_value_payload"]
    assert expected_error in payload["errors"]
    assert "ai_guessing_forbidden" in payload["errors"]
    assert expected_error in unit_value["errors"]
    assert "ai_guessing_forbidden" in unit_value["errors"]
    assert unit_value["conversion_source"] == "ai_structured_from_provided_input"
    assert unit_value["review_status"] in ALLOWED_REVIEW_STATUSES
    assert unit_value["reviewer_corrected"] is False


@pytest.mark.parametrize("missing_text", ("missing", "unknown"))
def test_build_unit_payload_draft_does_not_turn_missing_text_into_zero(missing_text):
    payload = k10_mock_adapter.build_unit_payload_draft(
        payload_type="weight_json",
        source_text=f"weight is {missing_text}",
        source_language="en",
        provided_values={"value": missing_text, "unit": "kg"},
    )

    unit_value = payload["unit_value_payload"]
    assert unit_value["original_value"] != 0
    if missing_text == "unknown":
        assert unit_value["original_value"] is None
        assert "missing_value" in unit_value["errors"]
        assert "ai_guessing_forbidden" in unit_value["errors"]
    else:
        assert unit_value["original_value"] == "missing"
        assert "conversion_not_possible" in unit_value["errors"]
    _assert_no_provider_data(payload)


def test_build_field_diff_draft_is_review_metadata_not_canonical_update():
    current_value = {"original_value": 1.1, "original_unit": "kg"}
    suggested_value = {"original_value": 1.0, "original_unit": "kg"}

    diff = k10_mock_adapter.build_field_diff_draft(
        field_key="weight_json.net_weight",
        current_value=current_value,
        suggested_value=suggested_value,
        reason="source provided a new draft candidate",
        confidence="low",
    )

    assert diff["field_key"] == "weight_json.net_weight"
    assert diff["current_value"] == current_value
    assert diff["suggested_value"] == suggested_value
    assert diff["draft_value"] == suggested_value
    assert diff["reason"] == "source provided a new draft candidate"
    assert diff["confidence"] == "low"
    assert diff["review_status"] in ALLOWED_REVIEW_STATUSES
    assert diff["reviewer_corrected"] is False
    assert diff["proposed_action"] == "request_review"
    _assert_no_provider_data(diff)


def test_validate_mock_result_shape_accepts_valid_empty_result():
    validation = k10_mock_adapter.validate_mock_result_shape(_valid_result())

    assert validation == {
        "is_valid": True,
        "errors": [],
        "warnings": [],
        "missing_required_fields": [],
        "forbidden_fields_present": [],
    }


def test_validate_mock_result_shape_reports_missing_required_fields():
    result = _valid_result()
    result.pop("unit_payloads")

    validation = k10_mock_adapter.validate_mock_result_shape(result)

    _assert_invalid(validation)
    assert "unit_payloads" in validation["missing_required_fields"]
    assert "shape_missing_required_field" in validation["errors"]


@pytest.mark.parametrize(
    ("field_name", "bad_value", "expected_error"),
    (
        ("live_provider_called", True, "shape_live_provider_called"),
        ("is_mock", False, "shape_not_mock_result"),
        ("review_status", "reviewed", "shape_invalid_review_status"),
        ("reviewer_corrected", True, "shape_reviewer_corrected_forbidden"),
    ),
)
def test_validate_mock_result_shape_rejects_invalid_mock_lifecycle_fields(
    field_name,
    bad_value,
    expected_error,
):
    result = _valid_result()
    result[field_name] = bad_value

    validation = k10_mock_adapter.validate_mock_result_shape(result)

    _assert_invalid(validation)
    assert expected_error in validation["errors"]


@pytest.mark.parametrize("field_name", FORBIDDEN_SHAPE_FIELDS)
def test_validate_mock_result_shape_rejects_provider_or_secret_fields(field_name):
    result = _valid_result()
    result[field_name] = "blocked-provider-value"

    validation = k10_mock_adapter.validate_mock_result_shape(result)

    _assert_invalid(validation)
    assert "shape_forbidden_provider_field" in validation["errors"]
    assert field_name in [item.lower() for item in validation["forbidden_fields_present"]]


def test_validate_mock_result_shape_rejects_nested_forbidden_fields_case_insensitive():
    result = _valid_result()
    result["field_diff_json"] = [
        {
            "safe": "draft metadata",
            "Authorization": "Bearer blocked",
            "nested": [{"API_KEY": "blocked"}],
        }
    ]

    validation = k10_mock_adapter.validate_mock_result_shape(result)

    _assert_invalid(validation)
    assert "shape_forbidden_provider_field" in validation["errors"]
    forbidden_paths = [item.lower() for item in validation["forbidden_fields_present"]]
    assert "field_diff_json[0].authorization" in forbidden_paths
    assert "field_diff_json[0].nested[0].api_key" in forbidden_paths


def test_validate_mock_result_shape_rejects_nested_reviewer_corrected_true():
    result = _valid_result()
    result["field_diff_json"] = [{"reviewer_corrected": True}]

    validation = k10_mock_adapter.validate_mock_result_shape(result)

    _assert_invalid(validation)
    assert "shape_reviewer_corrected_forbidden" in validation["errors"]
    assert "field_diff_json[0].reviewer_corrected" in validation[
        "forbidden_fields_present"
    ]


def test_list_supported_output_sections_contains_required_sections():
    supported_sections = set(k10_mock_adapter.list_supported_output_sections())

    assert {
        "canonical_product_fields",
        "unit_payloads",
        "dimensions_json",
        "package_dimensions_json",
        "weight_json",
        "package_weight_json",
        "ai_warnings_json",
        "field_diff_json",
        "missing_field_hints",
    } <= supported_sections


def test_mock_builders_do_not_emit_live_provider_or_secret_data():
    mock_input = k10_mock_adapter.build_mock_input(
        raw_input_text="package weight 3 lb",
        raw_input_language="en",
        raw_input_payload_json={"package_weight": {"value": 3, "unit": "lb"}},
        operator_notes="explicit local package weight",
        source_system="manual",
        requested_output_sections=["package_weight_json"],
    )
    outputs = [
        k10_mock_adapter.build_empty_mock_result(),
        mock_input,
        k10_mock_adapter.build_mock_structured_output(mock_input),
        k10_mock_adapter.build_field_diff_draft(
            field_key="package_weight_json.package_weight",
            current_value=None,
            suggested_value={"original_value": 3, "original_unit": "lb"},
            reason="explicit package weight candidate",
            confidence="medium",
        ),
        k10_mock_adapter.build_unit_payload_draft(
            payload_type="package_weight_json",
            source_text="package weight 3 lb",
            source_language="en",
            provided_values={"value": 3, "unit": "lb"},
        ),
    ]

    for output in outputs:
        _assert_no_provider_data(output)
