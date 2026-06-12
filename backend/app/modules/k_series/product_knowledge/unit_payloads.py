"""K09E dimensions and weight payload helper.

K09E is a pure module-local helper for dimensions / weight payload construction
and validation.
It composes K09B payload contracts using K09C unit_conversion helpers.
No DB.
No FastAPI router registration.
No SQLAlchemy session.
No env read.
No live service.
No AI guessing.
No free-text dimensions parser.
Missing / unknown values must not be converted to zero.
This module does not modify service create/update behavior.
"""

from copy import deepcopy
from typing import Any

from backend.app.modules.k_series.product_knowledge import unit_conversion


ERROR_AMBIGUOUS_DIMENSION_FORMAT = "ambiguous_dimension_format"
ERROR_PRODUCT_VS_PACKAGE_CONFLICT = "product_vs_package_conflict"
ERROR_NET_VS_GROSS_WEIGHT_AMBIGUOUS = "net_vs_gross_weight_ambiguous"
ERROR_DIMENSION_VALUE_MISSING = "dimension_value_missing"
ERROR_WEIGHT_VALUE_MISSING = "weight_value_missing"
WARNING_DIMENSION_ORDER_MISSING = "dimension_order_missing"
WARNING_OPTIONAL_FIELD_MISSING = "optional_field_missing"
WARNING_REVIEW_REQUIRED = "review_required"
WARNING_FREE_TEXT_PARSING_NOT_SUPPORTED = "free_text_parsing_not_supported"

ERROR_UNSUPPORTED_UNIT = unit_conversion.ERROR_UNSUPPORTED_UNIT
ERROR_MISSING_UNIT = unit_conversion.ERROR_MISSING_UNIT
ERROR_MISSING_VALUE = unit_conversion.ERROR_MISSING_VALUE
ERROR_INVALID_NUMERIC_VALUE = unit_conversion.ERROR_INVALID_NUMERIC_VALUE
ERROR_AI_GUESSING_FORBIDDEN = unit_conversion.ERROR_AI_GUESSING_FORBIDDEN
ERROR_CONVERSION_NOT_POSSIBLE = unit_conversion.ERROR_CONVERSION_NOT_POSSIBLE

_MISSING_TEXT_VALUES = {"", "unknown", "none", "null", "n/a", "na"}
_AI_STRUCTURED_SOURCE = "ai_structured_from_provided_input"

_PRODUCT_DIMENSION_FIELDS = (
    "length",
    "width",
    "height",
    "diameter",
    "thickness",
)
_PACKAGE_DIMENSION_FIELDS = (
    "package_length",
    "package_width",
    "package_height",
    "package_diameter",
)
_PRODUCT_WEIGHT_FIELDS = ("net_weight", "gross_weight")
_PACKAGE_WEIGHT_FIELDS = ("package_weight", "shipping_weight")


def build_dimensions_payload(
    *,
    length: Any = None,
    length_unit: str | None = None,
    width: Any = None,
    width_unit: str | None = None,
    height: Any = None,
    height_unit: str | None = None,
    diameter: Any = None,
    diameter_unit: str | None = None,
    thickness: Any = None,
    thickness_unit: str | None = None,
    dimension_order: list[str] | tuple[str, ...] | None = None,
    dimension_format: str | None = None,
    source_text: str | None = None,
    source_language: str | None = None,
    parsed_from_text: bool = False,
    display_market: str | None = None,
    conversion_source: str = "operator_entered",
    review_status: str = "draft",
    reviewer_corrected: bool = False,
) -> dict[str, Any]:
    length_payload = _build_unit_value_payload(
        value_kind="length",
        original_value=length,
        original_unit=length_unit,
        source_text=source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )
    width_payload = _build_unit_value_payload(
        value_kind="length",
        original_value=width,
        original_unit=width_unit,
        source_text=source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )
    height_payload = _build_unit_value_payload(
        value_kind="length",
        original_value=height,
        original_unit=height_unit,
        source_text=source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )
    diameter_payload = _build_unit_value_payload(
        value_kind="length",
        original_value=diameter,
        original_unit=diameter_unit,
        source_text=source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )
    thickness_payload = _build_unit_value_payload(
        value_kind="length",
        original_value=thickness,
        original_unit=thickness_unit,
        source_text=source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )

    payload = {
        "unit_group": "length",
        "length": length_payload,
        "width": width_payload,
        "height": height_payload,
        "diameter": diameter_payload,
        "thickness": thickness_payload,
        "dimension_order": _copy_list_or_none(dimension_order),
        "dimension_format": dimension_format,
        "source_text": source_text,
        "source_language": source_language,
        "parsed_from_text": bool(parsed_from_text),
        "display_market": display_market,
        "review_status": review_status,
        "warnings": [],
        "errors": [],
    }
    _finalize_dimension_payload(
        payload,
        value_fields=_PRODUCT_DIMENSION_FIELDS,
        order_field="dimension_order",
        format_field="dimension_format",
        source_text_field="source_text",
        conversion_source=conversion_source,
    )
    return payload


def build_package_dimensions_payload(
    *,
    package_length: Any = None,
    package_length_unit: str | None = None,
    package_width: Any = None,
    package_width_unit: str | None = None,
    package_height: Any = None,
    package_height_unit: str | None = None,
    package_diameter: Any = None,
    package_diameter_unit: str | None = None,
    package_dimension_order: list[str] | tuple[str, ...] | None = None,
    package_dimension_format: str | None = None,
    package_source_text: str | None = None,
    source_language: str | None = None,
    parsed_from_text: bool = False,
    display_market: str | None = None,
    conversion_source: str = "operator_entered",
    review_status: str = "draft",
    reviewer_corrected: bool = False,
) -> dict[str, Any]:
    package_length_payload = _build_unit_value_payload(
        value_kind="length",
        original_value=package_length,
        original_unit=package_length_unit,
        source_text=package_source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )
    package_width_payload = _build_unit_value_payload(
        value_kind="length",
        original_value=package_width,
        original_unit=package_width_unit,
        source_text=package_source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )
    package_height_payload = _build_unit_value_payload(
        value_kind="length",
        original_value=package_height,
        original_unit=package_height_unit,
        source_text=package_source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )
    package_diameter_payload = _build_unit_value_payload(
        value_kind="length",
        original_value=package_diameter,
        original_unit=package_diameter_unit,
        source_text=package_source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )

    payload = {
        "package_unit_group": "length",
        "package_length": package_length_payload,
        "package_width": package_width_payload,
        "package_height": package_height_payload,
        "package_diameter": package_diameter_payload,
        "package_dimension_order": _copy_list_or_none(package_dimension_order),
        "package_dimension_format": package_dimension_format,
        "package_source_text": package_source_text,
        "source_language": source_language,
        "parsed_from_text": bool(parsed_from_text),
        "display_market": display_market,
        "review_status": review_status,
        "warnings": [],
        "errors": [],
    }
    _finalize_dimension_payload(
        payload,
        value_fields=_PACKAGE_DIMENSION_FIELDS,
        order_field="package_dimension_order",
        format_field="package_dimension_format",
        source_text_field="package_source_text",
        conversion_source=conversion_source,
    )
    return payload


def build_weight_payload(
    *,
    net_weight: Any = None,
    net_weight_unit: str | None = None,
    gross_weight: Any = None,
    gross_weight_unit: str | None = None,
    source_text: str | None = None,
    source_language: str | None = None,
    parsed_from_text: bool = False,
    display_market: str | None = None,
    conversion_source: str = "operator_entered",
    review_status: str = "draft",
    reviewer_corrected: bool = False,
) -> dict[str, Any]:
    net_weight_payload = _build_unit_value_payload(
        value_kind="weight",
        original_value=net_weight,
        original_unit=net_weight_unit,
        source_text=source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )
    gross_weight_payload = _build_unit_value_payload(
        value_kind="weight",
        original_value=gross_weight,
        original_unit=gross_weight_unit,
        source_text=source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )

    payload = {
        "unit_group": "weight",
        "net_weight": net_weight_payload,
        "gross_weight": gross_weight_payload,
        "source_text": source_text,
        "source_language": source_language,
        "parsed_from_text": bool(parsed_from_text),
        "display_market": display_market,
        "review_status": review_status,
        "warnings": [],
        "errors": [],
    }
    _finalize_weight_payload(
        payload,
        value_fields=_PRODUCT_WEIGHT_FIELDS,
        source_text_field="source_text",
        conversion_source=conversion_source,
        distinguish_warning=True,
    )
    return payload


def build_package_weight_payload(
    *,
    package_weight: Any = None,
    package_weight_unit: str | None = None,
    shipping_weight: Any = None,
    shipping_weight_unit: str | None = None,
    source_text: str | None = None,
    source_language: str | None = None,
    parsed_from_text: bool = False,
    display_market: str | None = None,
    conversion_source: str = "operator_entered",
    review_status: str = "draft",
    reviewer_corrected: bool = False,
) -> dict[str, Any]:
    package_weight_payload = _build_unit_value_payload(
        value_kind="weight",
        original_value=package_weight,
        original_unit=package_weight_unit,
        source_text=source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )
    shipping_weight_payload = _build_unit_value_payload(
        value_kind="weight",
        original_value=shipping_weight,
        original_unit=shipping_weight_unit,
        source_text=source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        display_market=display_market,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )

    payload = {
        "unit_group": "weight",
        "package_weight": package_weight_payload,
        "shipping_weight": shipping_weight_payload,
        "source_text": source_text,
        "source_language": source_language,
        "parsed_from_text": bool(parsed_from_text),
        "display_market": display_market,
        "review_status": review_status,
        "warnings": [],
        "errors": [],
    }
    _finalize_weight_payload(
        payload,
        value_fields=_PACKAGE_WEIGHT_FIELDS,
        source_text_field="source_text",
        conversion_source=conversion_source,
        distinguish_warning=False,
    )
    return payload


def validate_dimensions_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_payload(
        payload,
        expected_group_fields={"unit_group": "length"},
        value_fields=_PRODUCT_DIMENSION_FIELDS,
        missing_value_error=ERROR_DIMENSION_VALUE_MISSING,
        conflict_fields=_PACKAGE_DIMENSION_FIELDS,
        order_field="dimension_order",
        format_field="dimension_format",
    )


def validate_package_dimensions_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_payload(
        payload,
        expected_group_fields={"package_unit_group": "length"},
        value_fields=_PACKAGE_DIMENSION_FIELDS,
        missing_value_error=ERROR_DIMENSION_VALUE_MISSING,
        conflict_fields=_PRODUCT_DIMENSION_FIELDS,
        order_field="package_dimension_order",
        format_field="package_dimension_format",
    )


def validate_weight_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_payload(
        payload,
        expected_group_fields={"unit_group": "weight"},
        value_fields=_PRODUCT_WEIGHT_FIELDS,
        missing_value_error=ERROR_WEIGHT_VALUE_MISSING,
        conflict_fields=_PACKAGE_WEIGHT_FIELDS,
        order_field=None,
        format_field=None,
    )


def validate_package_weight_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_payload(
        payload,
        expected_group_fields={"unit_group": "weight"},
        value_fields=_PACKAGE_WEIGHT_FIELDS,
        missing_value_error=ERROR_WEIGHT_VALUE_MISSING,
        conflict_fields=_PRODUCT_WEIGHT_FIELDS,
        order_field=None,
        format_field=None,
    )


def collect_payload_errors(payload: dict[str, Any]) -> list[str]:
    return _dedupe(_collect_codes(payload, "errors"))


def collect_payload_warnings(payload: dict[str, Any]) -> list[str]:
    return _dedupe(_collect_codes(payload, "warnings"))


def _build_unit_value_payload(
    *,
    value_kind: str,
    original_value: Any,
    original_unit: str | None,
    source_text: str | None,
    source_language: str | None,
    parsed_from_text: bool,
    display_market: str | None,
    conversion_source: str,
    review_status: str,
    reviewer_corrected: bool,
) -> dict[str, Any] | None:
    if original_value is None and original_unit is None:
        return None

    payload = unit_conversion.normalize_unit_value(
        value_kind=value_kind,
        original_value=original_value,
        original_unit=original_unit,
        display_market=display_market,
        source_text=source_text,
        source_language=source_language,
        parsed_from_text=parsed_from_text,
        conversion_source=conversion_source,
        review_status=review_status,
        reviewer_corrected=reviewer_corrected,
    )
    if conversion_source == _AI_STRUCTURED_SOURCE and any(
        code in payload["errors"] for code in (ERROR_MISSING_VALUE, ERROR_MISSING_UNIT)
    ):
        payload["errors"] = _dedupe(payload["errors"] + [ERROR_AI_GUESSING_FORBIDDEN])
    return payload


def _finalize_dimension_payload(
    payload: dict[str, Any],
    *,
    value_fields: tuple[str, ...],
    order_field: str,
    format_field: str,
    source_text_field: str,
    conversion_source: str,
) -> None:
    value_payloads = [payload.get(field) for field in value_fields]
    provided_value_fields = [
        field
        for field in value_fields
        if _unit_payload_has_non_missing_original_value(payload.get(field))
    ]

    warnings = collect_payload_warnings(payload)
    errors = collect_payload_errors(payload)

    if not provided_value_fields:
        errors.append(ERROR_DIMENSION_VALUE_MISSING)
        if conversion_source == _AI_STRUCTURED_SOURCE:
            errors.append(ERROR_AI_GUESSING_FORBIDDEN)
    if len(provided_value_fields) > 1 and not payload.get(order_field):
        warnings.append(WARNING_DIMENSION_ORDER_MISSING)
    if _is_ambiguous_dimension_format(payload.get(format_field)):
        errors.append(ERROR_AMBIGUOUS_DIMENSION_FORMAT)
    if _should_warn_free_text(payload.get(source_text_field), payload.get("parsed_from_text")):
        if not any(item is not None for item in value_payloads):
            warnings.append(WARNING_FREE_TEXT_PARSING_NOT_SUPPORTED)

    payload["warnings"] = _dedupe(warnings)
    payload["errors"] = _dedupe(errors)


def _finalize_weight_payload(
    payload: dict[str, Any],
    *,
    value_fields: tuple[str, ...],
    source_text_field: str,
    conversion_source: str,
    distinguish_warning: bool,
) -> None:
    provided_value_fields = [
        field
        for field in value_fields
        if _unit_payload_has_non_missing_original_value(payload.get(field))
    ]

    warnings = collect_payload_warnings(payload)
    errors = collect_payload_errors(payload)

    if not provided_value_fields:
        errors.append(ERROR_WEIGHT_VALUE_MISSING)
        if conversion_source == _AI_STRUCTURED_SOURCE:
            errors.append(ERROR_AI_GUESSING_FORBIDDEN)
        if distinguish_warning and _looks_like_generic_weight_text(
            payload.get(source_text_field)
        ):
            warnings.append(ERROR_NET_VS_GROSS_WEIGHT_AMBIGUOUS)
    if _should_warn_free_text(payload.get(source_text_field), payload.get("parsed_from_text")):
        if not any(payload.get(field) is not None for field in value_fields):
            warnings.append(WARNING_FREE_TEXT_PARSING_NOT_SUPPORTED)

    payload["warnings"] = _dedupe(warnings)
    payload["errors"] = _dedupe(errors)


def _validate_payload(
    payload: dict[str, Any],
    *,
    expected_group_fields: dict[str, str],
    value_fields: tuple[str, ...],
    missing_value_error: str,
    conflict_fields: tuple[str, ...],
    order_field: str | None,
    format_field: str | None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "is_valid": False,
            "errors": [ERROR_CONVERSION_NOT_POSSIBLE],
            "warnings": [],
        }

    payload_snapshot = deepcopy(payload)
    warnings = collect_payload_warnings(payload_snapshot)
    errors = collect_payload_errors(payload_snapshot)

    for group_field, expected_value in expected_group_fields.items():
        if payload_snapshot.get(group_field) != expected_value:
            errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    for conflict_field in conflict_fields:
        if conflict_field in payload_snapshot:
            errors.append(ERROR_PRODUCT_VS_PACKAGE_CONFLICT)

    value_payloads = [payload_snapshot.get(field) for field in value_fields]
    provided_value_count = sum(
        1 for item in value_payloads if _unit_payload_has_non_missing_original_value(item)
    )
    if provided_value_count == 0:
        errors.append(missing_value_error)
    if order_field is not None and provided_value_count > 1 and not payload_snapshot.get(
        order_field
    ):
        warnings.append(WARNING_DIMENSION_ORDER_MISSING)
    if format_field is not None and _is_ambiguous_dimension_format(
        payload_snapshot.get(format_field)
    ):
        errors.append(ERROR_AMBIGUOUS_DIMENSION_FORMAT)

    unit_validation_errors, unit_validation_warnings = _validate_nested_unit_values(
        payload_snapshot
    )
    errors.extend(unit_validation_errors)
    warnings.extend(unit_validation_warnings)

    errors = _dedupe(errors)
    warnings = _dedupe(warnings)
    return {
        "is_valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _validate_nested_unit_values(value: Any) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(value, dict):
        if _is_unit_value_payload(value):
            validation = unit_conversion.validate_unit_value_payload(value)
            errors.extend(_code_list(validation.get("errors")))
            warnings.extend(_code_list(validation.get("warnings")))
        for nested_value in value.values():
            nested_errors, nested_warnings = _validate_nested_unit_values(nested_value)
            errors.extend(nested_errors)
            warnings.extend(nested_warnings)
    elif isinstance(value, list):
        for item in value:
            nested_errors, nested_warnings = _validate_nested_unit_values(item)
            errors.extend(nested_errors)
            warnings.extend(nested_warnings)

    return _dedupe(errors), _dedupe(warnings)


def _collect_codes(value: Any, key: str) -> list[str]:
    codes: list[str] = []

    if isinstance(value, dict):
        codes.extend(_code_list(value.get(key)))
        for nested_value in value.values():
            codes.extend(_collect_codes(nested_value, key))
    elif isinstance(value, list):
        for item in value:
            codes.extend(_collect_codes(item, key))

    return codes


def _is_unit_value_payload(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "value_kind" in value
        and ("original_value" in value or "original_unit" in value)
    )


def _unit_payload_has_non_missing_original_value(value: Any) -> bool:
    if not _is_unit_value_payload(value):
        return False
    return not _is_missing_text_value(value.get("original_value"))


def _is_missing_text_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_TEXT_VALUES
    return False


def _copy_list_or_none(value: list[str] | tuple[str, ...] | None) -> list[str] | None:
    if value is None:
        return None
    return [str(item) for item in value]


def _is_ambiguous_dimension_format(value: Any) -> bool:
    if value is None:
        return False
    return "ambiguous" in str(value).strip().lower()


def _looks_like_generic_weight_text(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    if not text:
        return False
    return "weight" in text and not any(
        token in text
        for token in ("net", "gross", "package", "shipping", "packed")
    )


def _should_warn_free_text(source_text: Any, parsed_from_text: Any) -> bool:
    if not parsed_from_text or source_text is None:
        return False
    text = str(source_text).strip()
    if not text:
        return False
    has_digit = any(character.isdigit() for character in text)
    has_alpha = any(character.isalpha() for character in text)
    has_dimension_separator = any(marker in text.lower() for marker in (" x ", "x", "*", " by "))
    return has_digit and (has_alpha or has_dimension_separator)


def _code_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
