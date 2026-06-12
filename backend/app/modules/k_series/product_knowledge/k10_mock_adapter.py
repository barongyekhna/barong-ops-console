"""K10C module-local DeepSeek mock adapter skeleton.

K10C is a module-local DeepSeek mock adapter skeleton.
No live DeepSeek.
No OpenAI / Claude / SERP / WooCommerce / n8n / Google Sheets calls.
No DB.
No env read.
No FastAPI router registration.
No service.py integration.
Mock output only.
AI output must remain draft / needs_review.
AI must not guess missing product facts, dimensions, weights, package
dimensions, net/gross distinction, or product/package distinction.
Missing / unknown must not become 0.
This module does not approve runtime integration.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any


MOCK_ADAPTER_NAME = "k10_deepseek_mock_adapter"
MOCK_PROVIDER_NAME = "deepseek_mock"
DEFAULT_CANONICAL_LANGUAGE = "en"
DEFAULT_REVIEW_STATUS = "needs_review"
DEFAULT_CONVERSION_SOURCE = "ai_structured_from_provided_input"

ERROR_MISSING_VALUE = "missing_value"
ERROR_MISSING_UNIT = "missing_unit"
ERROR_UNSUPPORTED_UNIT = "unsupported_unit"
ERROR_INVALID_NUMERIC_VALUE = "invalid_numeric_value"
ERROR_AMBIGUOUS_DIMENSION_FORMAT = "ambiguous_dimension_format"
ERROR_PRODUCT_VS_PACKAGE_CONFLICT = "product_vs_package_conflict"
ERROR_NET_VS_GROSS_WEIGHT_AMBIGUOUS = "net_vs_gross_weight_ambiguous"
ERROR_AI_GUESSING_FORBIDDEN = "ai_guessing_forbidden"
ERROR_CONVERSION_NOT_POSSIBLE = "conversion_not_possible"
ERROR_ORIGINAL_VALUE_MISSING = "original_value_missing"
WARNING_REVIEW_REQUIRED = "review_required"
WARNING_FREE_TEXT_PARSING_NOT_SUPPORTED = "free_text_parsing_not_supported"

SHAPE_MISSING_REQUIRED_FIELD = "shape_missing_required_field"
SHAPE_INVALID_REVIEW_STATUS = "shape_invalid_review_status"
SHAPE_LIVE_PROVIDER_CALLED = "shape_live_provider_called"
SHAPE_FORBIDDEN_PROVIDER_FIELD = "shape_forbidden_provider_field"

SUPPORTED_OUTPUT_SECTIONS = [
    "canonical_product_fields",
    "unit_payloads",
    "dimensions_json",
    "package_dimensions_json",
    "weight_json",
    "package_weight_json",
    "ai_warnings_json",
    "field_diff_json",
    "missing_field_hints",
]

UNIT_PAYLOAD_KEYS = (
    "dimensions_json",
    "package_dimensions_json",
    "weight_json",
    "package_weight_json",
)

ALLOWED_REVIEW_STATUSES = {"draft", "needs_review"}

FORBIDDEN_PROVIDER_OUTPUT_KEYS = {
    "api_key",
    "provider_api_key",
    "provider_model",
    "provider_request_id",
    "provider_secret",
    "secret",
    "token",
    "model_call_id",
}

MISSING_TEXT_VALUES = {"", "unknown", "none", "null", "n/a", "na"}


@dataclass
class K10MockWarning:
    """Review warning metadata emitted by the K10 mock skeleton."""

    code: str
    path: str | None = None
    message: str | None = None


@dataclass
class K10MockError:
    """Review error metadata emitted by the K10 mock skeleton."""

    code: str
    path: str | None = None
    message: str | None = None


@dataclass
class K10MockInput:
    """Local-only mock adapter input envelope."""

    raw_input_text: str | None = None
    raw_input_language: str | None = None
    raw_input_payload_json: dict | None = None
    operator_notes: str | None = None
    source_system: str | None = "manual"
    requested_output_sections: list[str] = field(default_factory=list)
    adapter_name: str = MOCK_ADAPTER_NAME
    provider_name: str = MOCK_PROVIDER_NAME
    is_mock: bool = True


@dataclass
class K10MockResult:
    """Local-only mock adapter result envelope."""

    adapter_name: str = MOCK_ADAPTER_NAME
    provider_name: str = MOCK_PROVIDER_NAME
    adapter_mode: str = "mock"
    is_mock: bool = True
    live_provider_called: bool = False
    canonical_language: str = DEFAULT_CANONICAL_LANGUAGE
    review_status: str = DEFAULT_REVIEW_STATUS
    source: dict[str, Any] = field(default_factory=dict)
    deepseek_structured_output_json: dict[str, Any] = field(default_factory=dict)
    ai_confidence_scores_json: dict[str, Any] = field(default_factory=dict)
    ai_warnings_json: list[dict[str, Any]] = field(default_factory=list)
    field_diff_json: list[dict[str, Any]] = field(default_factory=list)
    unit_payloads: dict[str, Any] = field(default_factory=dict)
    missing_field_hints: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_mock_input(
    *,
    raw_input_text: str | None = None,
    raw_input_language: str | None = None,
    raw_input_payload_json: dict | None = None,
    operator_notes: str | None = None,
    source_system: str | None = "manual",
    requested_output_sections: list[str] | None = None,
) -> dict:
    """Build a local mock input envelope without reading env or services."""

    requested_sections = (
        list_supported_output_sections()
        if requested_output_sections is None
        else _copy_string_list(requested_output_sections)
    )
    mock_input = K10MockInput(
        raw_input_text=raw_input_text,
        raw_input_language=raw_input_language,
        raw_input_payload_json=deepcopy(raw_input_payload_json),
        operator_notes=operator_notes,
        source_system=source_system,
        requested_output_sections=requested_sections,
    )
    return asdict(mock_input)


def build_empty_mock_result(
    *,
    source_text: str | None = None,
    source_language: str | None = None,
) -> dict:
    """Return a deterministic empty K10 mock result skeleton."""

    raw_source_language = _source_language_or_unknown(source_language)
    canonical_language = _canonical_language_or_default(source_language)
    review_warning = K10MockWarning(
        code=WARNING_REVIEW_REQUIRED,
        path="unit_payloads",
        message="Mock AI output requires human review before downstream use.",
    )
    result = K10MockResult(
        canonical_language=canonical_language,
        source={
            "raw_input_text": source_text,
            "raw_input_language": raw_source_language,
        },
        deepseek_structured_output_json=_empty_structured_output(),
        ai_confidence_scores_json={},
        ai_warnings_json=[asdict(review_warning)],
        field_diff_json=[],
        unit_payloads=_empty_unit_payloads(),
        missing_field_hints=[],
        errors=[],
        warnings=[WARNING_REVIEW_REQUIRED],
    )
    return asdict(result)


def build_mock_structured_output(
    mock_input: dict,
) -> dict:
    """Build deterministic draft output without AI, parsing, or live calls."""

    input_snapshot = deepcopy(mock_input) if isinstance(mock_input, dict) else {}
    source_text = input_snapshot.get("raw_input_text")
    source_language = input_snapshot.get("raw_input_language")
    result = build_empty_mock_result(
        source_text=source_text,
        source_language=source_language,
    )
    result["source"].update(
        {
            "source_system": input_snapshot.get("source_system"),
            "operator_notes": input_snapshot.get("operator_notes"),
            "raw_input_payload_json": deepcopy(
                input_snapshot.get("raw_input_payload_json")
            ),
            "requested_output_sections": _copy_string_list(
                input_snapshot.get("requested_output_sections")
            ),
        }
    )

    if _has_text(source_text):
        warning = K10MockWarning(
            code=WARNING_FREE_TEXT_PARSING_NOT_SUPPORTED,
            path="source.raw_input_text",
            message=(
                "K10C skeleton preserves source text but does not parse free text."
            ),
        )
        result["ai_warnings_json"].append(asdict(warning))
        result["warnings"] = _dedupe_codes(
            result["warnings"] + [WARNING_FREE_TEXT_PARSING_NOT_SUPPORTED]
        )

    return result


def build_unit_payload_draft(
    *,
    payload_type: str,
    source_text: str | None = None,
    source_language: str | None = None,
    provided_values: dict | None = None,
) -> dict:
    """Build a non-converting unit payload draft from explicit local values only."""

    provided_snapshot = deepcopy(provided_values) if isinstance(provided_values, dict) else {}
    original_value = _first_present(
        provided_snapshot,
        ("original_value", "value", "candidate_value"),
    )
    original_unit = _first_present(
        provided_snapshot,
        ("original_unit", "unit", "candidate_unit"),
    )
    errors: list[str] = []
    warnings = [WARNING_REVIEW_REQUIRED]

    if _is_missing_value(original_value):
        errors.extend([ERROR_MISSING_VALUE, ERROR_AI_GUESSING_FORBIDDEN])
    if _is_missing_value(original_unit):
        errors.extend([ERROR_MISSING_UNIT, ERROR_AI_GUESSING_FORBIDDEN])
    errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    payload = {
        "payload_type": payload_type,
        "review_status": DEFAULT_REVIEW_STATUS,
        "reviewer_corrected": False,
        "source_text": source_text,
        "source_language": _source_language_or_unknown(source_language),
        "provided_values": provided_snapshot,
        "unit_value_payload": {
            "value_kind": _value_kind_for_payload_type(
                str(provided_snapshot.get("value_kind") or payload_type)
            ),
            "original_value": None
            if _is_missing_value(original_value)
            else deepcopy(original_value),
            "original_unit": None
            if _is_missing_value(original_unit)
            else str(original_unit).strip(),
            "normalized_metric_value": None,
            "normalized_metric_unit": None,
            "normalized_imperial_value": None,
            "normalized_imperial_unit": None,
            "display_value": None,
            "display_unit": None,
            "display_market": str(
                provided_snapshot.get("display_market") or "unknown"
            ),
            "conversion_source": DEFAULT_CONVERSION_SOURCE,
            "conversion_precision": ERROR_CONVERSION_NOT_POSSIBLE,
            "source_text": source_text,
            "source_language": _source_language_or_unknown(source_language),
            "parsed_from_text": _has_text(source_text),
            "review_status": DEFAULT_REVIEW_STATUS,
            "reviewer_corrected": False,
            "warnings": warnings,
            "errors": _dedupe_codes(errors),
        },
        "warnings": warnings,
        "errors": _dedupe_codes(errors),
    }
    return payload


def build_field_diff_draft(
    *,
    field_key: str,
    current_value: Any,
    suggested_value: Any,
    reason: str,
    confidence: str | None = None,
) -> dict:
    """Build draft-only field diff metadata without applying the diff."""

    return {
        "field_key": field_key,
        "path": field_key,
        "current_value": deepcopy(current_value),
        "draft_value": deepcopy(suggested_value),
        "reason": reason,
        "confidence": confidence,
        "review_status": DEFAULT_REVIEW_STATUS,
        "reviewer_corrected": False,
        "warnings": [WARNING_REVIEW_REQUIRED],
        "errors": [],
        "proposed_action": "request_review",
    }


def validate_mock_result_shape(result: dict) -> dict:
    """Perform lightweight local shape checks without external services."""

    if not isinstance(result, dict):
        return {
            "is_valid": False,
            "errors": [ERROR_CONVERSION_NOT_POSSIBLE],
            "warnings": [],
            "missing_required_fields": [],
            "forbidden_fields_present": [],
        }

    required_fields = (
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
    )
    missing_required_fields = [
        field_name for field_name in required_fields if field_name not in result
    ]
    forbidden_fields_present = [
        field_name
        for field_name in FORBIDDEN_PROVIDER_OUTPUT_KEYS
        if field_name in result
    ]
    errors: list[str] = []
    warnings: list[str] = []

    if missing_required_fields:
        errors.append(SHAPE_MISSING_REQUIRED_FIELD)
    if result.get("live_provider_called") is not False:
        errors.append(SHAPE_LIVE_PROVIDER_CALLED)
    if result.get("review_status") not in ALLOWED_REVIEW_STATUSES:
        errors.append(SHAPE_INVALID_REVIEW_STATUS)
    if forbidden_fields_present:
        errors.append(SHAPE_FORBIDDEN_PROVIDER_FIELD)
    if result.get("warnings") and WARNING_REVIEW_REQUIRED not in result.get(
        "warnings",
        [],
    ):
        warnings.append(WARNING_REVIEW_REQUIRED)

    return {
        "is_valid": not errors,
        "errors": _dedupe_codes(errors),
        "warnings": _dedupe_codes(warnings),
        "missing_required_fields": missing_required_fields,
        "forbidden_fields_present": forbidden_fields_present,
    }


def list_supported_output_sections() -> list[str]:
    """Return supported draft output sections for the K10C skeleton."""

    return list(SUPPORTED_OUTPUT_SECTIONS)


def _empty_unit_payloads() -> dict[str, Any]:
    return {payload_key: None for payload_key in UNIT_PAYLOAD_KEYS}


def _empty_structured_output() -> dict[str, Any]:
    unit_payloads = _empty_unit_payloads()
    structured_output = {
        "canonical_product_fields": {},
        "unit_payloads": unit_payloads,
        "ai_warnings_json": [],
        "field_diff_json": [],
        "missing_field_hints": [],
    }
    structured_output.update(deepcopy(unit_payloads))
    return structured_output


def _source_language_or_unknown(source_language: str | None) -> str:
    if not _has_text(source_language):
        return "unknown"
    return str(source_language).strip()


def _canonical_language_or_default(source_language: str | None) -> str:
    if not _has_text(source_language):
        return DEFAULT_CANONICAL_LANGUAGE
    return str(source_language).strip()


def _copy_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _first_present(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in source:
            return source[key]
    return None


def _value_kind_for_payload_type(payload_type: str) -> str:
    lowered = payload_type.strip().lower()
    if "weight" in lowered:
        return "weight"
    if "volume" in lowered or "capacity" in lowered:
        return "volume"
    if "temperature" in lowered:
        return "temperature"
    return "length"


def _has_text(value: Any) -> bool:
    if value is None:
        return False
    return bool(str(value).strip())


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in MISSING_TEXT_VALUES
    return False


def _dedupe_codes(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
