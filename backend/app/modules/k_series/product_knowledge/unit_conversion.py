"""K09C pure module-local unit conversion helper.

K09C is pure module-local unit conversion helper.
No DB.
No FastAPI router registration.
No env read.
No live service.
No AI guessing.
Missing / unknown values must not be converted to zero.
Original value and original unit must be preserved by payload builders.

This module only handles single Unit Value Payload values. It does not parse
free text, dimension strings, package dimension groups, or product context.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


SUPPORTED_UNITS_BY_GROUP: dict[str, tuple[str, ...]] = {
    "length": ("mm", "cm", "m", "in", "ft"),
    "weight": ("g", "kg", "oz", "lb"),
    "volume": ("ml", "l", "fl_oz"),
    "temperature": ("c", "f"),
}

UNIT_ALIASES: dict[str, str] = {
    "mm": "mm",
    "cm": "cm",
    "m": "m",
    "in": "in",
    "inch": "in",
    "inches": "in",
    "ft": "ft",
    "foot": "ft",
    "feet": "ft",
    "g": "g",
    "gram": "g",
    "grams": "g",
    "kg": "kg",
    "kgs": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "oz": "oz",
    "ounce": "oz",
    "ounces": "oz",
    "lb": "lb",
    "lbs": "lb",
    "pound": "lb",
    "pounds": "lb",
    "ml": "ml",
    "l": "l",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "fl_oz": "fl_oz",
    "floz": "fl_oz",
    "fl_ounce": "fl_oz",
    "fl_ounces": "fl_oz",
    "fluid_ounce": "fl_oz",
    "fluid_ounces": "fl_oz",
    "c": "c",
    "f": "f",
}

UNIT_TO_GROUP: dict[str, str] = {
    unit: group
    for group, units in SUPPORTED_UNITS_BY_GROUP.items()
    for unit in units
}

DEFAULT_METRIC_UNIT_BY_GROUP: dict[str, str] = {
    "length": "cm",
    "weight": "kg",
    "volume": "l",
    "temperature": "c",
}

DEFAULT_IMPERIAL_UNIT_BY_GROUP: dict[str, str] = {
    "length": "in",
    "weight": "lb",
    "volume": "fl_oz",
    "temperature": "f",
}

ERROR_UNSUPPORTED_UNIT = "unsupported_unit"
ERROR_MISSING_UNIT = "missing_unit"
ERROR_MISSING_VALUE = "missing_value"
ERROR_INVALID_NUMERIC_VALUE = "invalid_numeric_value"
ERROR_CONVERSION_NOT_POSSIBLE = "conversion_not_possible"
ERROR_AI_GUESSING_FORBIDDEN = "ai_guessing_forbidden"
ERROR_ORIGINAL_VALUE_MISSING = "original_value_missing"

WARNING_PRECISION_LOSS = "precision_loss_warning"
WARNING_MARKET_DISPLAY_UNKNOWN = "market_display_unknown"

_DEFAULT_PRECISION_BY_GROUP: dict[str, int] = {
    "length": 2,
    "weight": 2,
    "volume": 2,
    "temperature": 2,
}

_MISSING_TEXT_VALUES = {"", "unknown", "none", "null", "n/a", "na"}

_LENGTH_TO_CM: dict[str, Decimal] = {
    "mm": Decimal("0.1"),
    "cm": Decimal("1"),
    "m": Decimal("100"),
    "in": Decimal("2.54"),
    "ft": Decimal("30.48"),
}

_WEIGHT_TO_G: dict[str, Decimal] = {
    "g": Decimal("1"),
    "kg": Decimal("1000"),
    "oz": Decimal("28.349523125"),
    "lb": Decimal("453.59237"),
}

_VOLUME_TO_ML: dict[str, Decimal] = {
    "ml": Decimal("1"),
    "l": Decimal("1000"),
    "fl_oz": Decimal("29.5735295625"),
}

_CONVERSION_FACTORS_BY_GROUP: dict[str, dict[str, Decimal]] = {
    "length": _LENGTH_TO_CM,
    "weight": _WEIGHT_TO_G,
    "volume": _VOLUME_TO_ML,
}

_ALLOWED_CONVERSION_SOURCES = {
    "operator_entered",
    "supplier_imported",
    "system_converted",
    "reviewer_corrected",
    "ai_structured_from_provided_input",
    "unknown",
}

_AI_SOURCE_PREFIXES = ("ai_", "llm_", "openai", "deepseek", "claude")

_PAYLOAD_REQUIRED_FIELDS = (
    "value_kind",
    "original_value",
    "original_unit",
    "normalized_metric_value",
    "normalized_metric_unit",
    "normalized_imperial_value",
    "normalized_imperial_unit",
    "display_value",
    "display_unit",
    "display_market",
    "conversion_source",
    "conversion_precision",
    "source_text",
    "source_language",
    "parsed_from_text",
    "review_status",
    "reviewer_corrected",
    "warnings",
    "errors",
)


def canonicalize_unit(unit: str | None) -> str | None:
    """Return the canonical unit code, or None for missing/unsupported input."""

    if unit is None:
        return None
    normalized = str(unit).strip().lower()
    if normalized in _MISSING_TEXT_VALUES:
        return None
    normalized = normalized.replace(".", "").replace("-", "_").replace(" ", "_")
    return UNIT_ALIASES.get(normalized)


def get_unit_group(unit: str | None) -> str | None:
    canonical_unit = canonicalize_unit(unit)
    if canonical_unit is None:
        return None
    return UNIT_TO_GROUP.get(canonical_unit)


def is_supported_unit(unit: str | None) -> bool:
    return get_unit_group(unit) is not None


def convert_value(
    value: Any,
    from_unit: str,
    to_unit: str,
    precision: int | None = None,
) -> int | float | None:
    """Convert a numeric value between supported units.

    Unsupported units, invalid values, and cross-group conversions return None.
    The normalizing payload builder turns those cases into explicit errors.
    """

    numeric_value, numeric_error = _coerce_decimal(value)
    if numeric_error is not None:
        return None

    from_canonical = canonicalize_unit(from_unit)
    to_canonical = canonicalize_unit(to_unit)
    if from_canonical is None or to_canonical is None:
        return None

    from_group = UNIT_TO_GROUP.get(from_canonical)
    to_group = UNIT_TO_GROUP.get(to_canonical)
    if from_group is None or from_group != to_group:
        return None

    converted, conversion_error = _convert_decimal(
        numeric_value,
        from_canonical,
        to_canonical,
    )
    if conversion_error is not None or converted is None:
        return None

    rounded = _round_decimal(
        converted,
        _resolved_precision(from_group, precision),
    )
    return _decimal_to_json_number(rounded)


def normalize_unit_value(
    value_kind: str,
    original_value: Any,
    original_unit: str | None,
    display_market: str | None = None,
    display_unit: str | None = None,
    source_text: str | None = None,
    source_language: str | None = None,
    parsed_from_text: bool = False,
    conversion_source: str = "operator_entered",
    conversion_precision: str | None = None,
    review_status: str = "draft",
    reviewer_corrected: bool = False,
) -> dict[str, Any]:
    """Build a K09B-shaped Unit Value Payload for one explicit value + unit."""

    warnings: list[str] = []
    errors: list[str] = []

    unit_group = value_kind if value_kind in SUPPORTED_UNITS_BY_GROUP else None
    canonical_original_unit = canonicalize_unit(original_unit)
    payload_original_unit = _payload_original_unit(original_unit, canonical_original_unit)
    payload_display_market = _payload_display_market(display_market)
    payload_conversion_source = _payload_conversion_source(
        conversion_source,
        reviewer_corrected,
    )

    if _looks_like_forbidden_ai_source(payload_conversion_source):
        errors.append(ERROR_AI_GUESSING_FORBIDDEN)
        errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    if unit_group is None:
        errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    numeric_value: Decimal | None = None
    if _is_missing_value(original_value):
        errors.append(ERROR_MISSING_VALUE)
        errors.append(ERROR_CONVERSION_NOT_POSSIBLE)
    else:
        numeric_value, numeric_error = _coerce_decimal(original_value)
        if numeric_error is not None:
            errors.append(numeric_error)
            errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    if _is_missing_unit(original_unit):
        errors.append(ERROR_MISSING_UNIT)
        errors.append(ERROR_CONVERSION_NOT_POSSIBLE)
    elif canonical_original_unit is None:
        errors.append(ERROR_UNSUPPORTED_UNIT)
        errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    original_unit_group = UNIT_TO_GROUP.get(canonical_original_unit or "")
    if (
        unit_group is not None
        and original_unit_group is not None
        and unit_group != original_unit_group
    ):
        errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    normalized_metric_value: int | float | None = None
    normalized_metric_unit: str | None = None
    normalized_imperial_value: int | float | None = None
    normalized_imperial_unit: str | None = None
    display_value: int | float | None = None
    payload_display_unit: str | None = None

    fatal_errors = _dedupe(errors)
    if not fatal_errors and numeric_value is not None and canonical_original_unit is not None:
        assert unit_group is not None
        precision = _DEFAULT_PRECISION_BY_GROUP[unit_group]
        normalized_metric_unit = DEFAULT_METRIC_UNIT_BY_GROUP[unit_group]
        normalized_imperial_unit = DEFAULT_IMPERIAL_UNIT_BY_GROUP[unit_group]

        normalized_metric_value = convert_value(
            numeric_value,
            canonical_original_unit,
            normalized_metric_unit,
            precision,
        )
        normalized_imperial_value = convert_value(
            numeric_value,
            canonical_original_unit,
            normalized_imperial_unit,
            precision,
        )

        payload_display_unit, display_warnings = _resolve_display_unit(
            unit_group,
            display_market,
            display_unit,
        )
        warnings.extend(display_warnings)
        if payload_display_unit is None:
            errors.append(ERROR_CONVERSION_NOT_POSSIBLE)
        else:
            display_value = convert_value(
                numeric_value,
                canonical_original_unit,
                payload_display_unit,
                precision,
            )

        if (
            normalized_metric_value is None
            or normalized_imperial_value is None
            or display_value is None
        ):
            errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    errors = _dedupe(errors)
    warnings = _dedupe(warnings)
    precision_label = conversion_precision or "2_decimal_places"
    if errors and ERROR_CONVERSION_NOT_POSSIBLE in errors and conversion_precision is None:
        precision_label = ERROR_CONVERSION_NOT_POSSIBLE

    return {
        "value_kind": value_kind,
        "original_value": _json_safe_original_value(original_value),
        "original_unit": payload_original_unit,
        "normalized_metric_value": normalized_metric_value,
        "normalized_metric_unit": normalized_metric_unit,
        "normalized_imperial_value": normalized_imperial_value,
        "normalized_imperial_unit": normalized_imperial_unit,
        "display_value": display_value,
        "display_unit": payload_display_unit,
        "display_market": payload_display_market,
        "conversion_source": payload_conversion_source,
        "conversion_precision": precision_label,
        "source_text": source_text,
        "source_language": source_language,
        "parsed_from_text": bool(parsed_from_text),
        "review_status": review_status,
        "reviewer_corrected": bool(reviewer_corrected),
        "warnings": warnings,
        "errors": errors,
    }


def default_display_unit(
    unit_group: str,
    display_market: str | None,
) -> tuple[str | None, list[str]]:
    group = str(unit_group).strip().lower()
    if group not in SUPPORTED_UNITS_BY_GROUP:
        return None, []

    market = _payload_display_market(display_market).upper()
    if market == "US":
        return DEFAULT_IMPERIAL_UNIT_BY_GROUP[group], []
    if market in {"EU", "AU", "FALLBACK"}:
        return DEFAULT_METRIC_UNIT_BY_GROUP[group], []
    if market in {"UK", "CA"}:
        return DEFAULT_METRIC_UNIT_BY_GROUP[group], [WARNING_MARKET_DISPLAY_UNKNOWN]
    return DEFAULT_METRIC_UNIT_BY_GROUP[group], [WARNING_MARKET_DISPLAY_UNKNOWN]


def validate_unit_value_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a K09B-shaped Unit Value Payload without mutating it."""

    warnings: list[str] = []
    errors: list[str] = []

    if not isinstance(payload, dict):
        return {
            "is_valid": False,
            "warnings": warnings,
            "errors": [ERROR_CONVERSION_NOT_POSSIBLE],
        }

    warnings.extend(_code_list(payload.get("warnings")))
    errors.extend(_code_list(payload.get("errors")))

    missing_required_fields = [
        field for field in _PAYLOAD_REQUIRED_FIELDS if field not in payload
    ]
    if missing_required_fields:
        errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    value_kind = payload.get("value_kind")
    unit_group = value_kind if value_kind in SUPPORTED_UNITS_BY_GROUP else None
    if unit_group is None:
        errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    original_value = payload.get("original_value")
    original_unit = payload.get("original_unit")

    if _is_missing_value(original_value):
        errors.append(ERROR_MISSING_VALUE)
    else:
        _, numeric_error = _coerce_decimal(original_value)
        if numeric_error is not None:
            errors.append(numeric_error)

    canonical_original_unit = canonicalize_unit(original_unit)
    if _is_missing_unit(original_unit):
        errors.append(ERROR_MISSING_UNIT)
    elif canonical_original_unit is None:
        errors.append(ERROR_UNSUPPORTED_UNIT)

    original_unit_group = UNIT_TO_GROUP.get(canonical_original_unit or "")
    if (
        unit_group is not None
        and original_unit_group is not None
        and unit_group != original_unit_group
    ):
        errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    for unit_field in (
        "normalized_metric_unit",
        "normalized_imperial_unit",
        "display_unit",
    ):
        unit = payload.get(unit_field)
        if _is_missing_unit(unit):
            continue
        canonical_unit = canonicalize_unit(unit)
        if canonical_unit is None:
            errors.append(ERROR_UNSUPPORTED_UNIT)
            continue
        if unit_group is not None and UNIT_TO_GROUP.get(canonical_unit) != unit_group:
            errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    if _is_missing_value(original_value):
        for value_field in (
            "normalized_metric_value",
            "normalized_imperial_value",
            "display_value",
        ):
            if not _is_missing_value(payload.get(value_field)):
                errors.append(ERROR_ORIGINAL_VALUE_MISSING)
                errors.append(ERROR_CONVERSION_NOT_POSSIBLE)
                break

    if any(
        code in errors
        for code in (
            ERROR_MISSING_VALUE,
            ERROR_MISSING_UNIT,
            ERROR_UNSUPPORTED_UNIT,
            ERROR_INVALID_NUMERIC_VALUE,
        )
    ):
        errors.append(ERROR_CONVERSION_NOT_POSSIBLE)

    errors = _dedupe(errors)
    warnings = _dedupe(warnings)
    return {
        "is_valid": not errors,
        "warnings": warnings,
        "errors": errors,
    }


def _resolve_display_unit(
    unit_group: str,
    display_market: str | None,
    display_unit: str | None,
) -> tuple[str | None, list[str]]:
    if _is_missing_unit(display_unit):
        return default_display_unit(unit_group, display_market)

    canonical_display_unit = canonicalize_unit(display_unit)
    if canonical_display_unit is None:
        return None, []
    if UNIT_TO_GROUP.get(canonical_display_unit) != unit_group:
        return None, []
    return canonical_display_unit, []


def _convert_decimal(
    value: Decimal,
    from_unit: str,
    to_unit: str,
) -> tuple[Decimal | None, str | None]:
    if from_unit == to_unit:
        return value, None

    group = UNIT_TO_GROUP.get(from_unit)
    if group is None or UNIT_TO_GROUP.get(to_unit) != group:
        return None, ERROR_CONVERSION_NOT_POSSIBLE

    if group == "temperature":
        return _convert_temperature(value, from_unit, to_unit)

    factors = _CONVERSION_FACTORS_BY_GROUP.get(group)
    if factors is None or from_unit not in factors or to_unit not in factors:
        return None, ERROR_CONVERSION_NOT_POSSIBLE

    base_value = value * factors[from_unit]
    return base_value / factors[to_unit], None


def _convert_temperature(
    value: Decimal,
    from_unit: str,
    to_unit: str,
) -> tuple[Decimal | None, str | None]:
    if from_unit == "c" and to_unit == "f":
        return value * Decimal("9") / Decimal("5") + Decimal("32"), None
    if from_unit == "f" and to_unit == "c":
        return (value - Decimal("32")) * Decimal("5") / Decimal("9"), None
    return None, ERROR_CONVERSION_NOT_POSSIBLE


def _coerce_decimal(value: Any) -> tuple[Decimal | None, str | None]:
    if isinstance(value, bool):
        return None, ERROR_INVALID_NUMERIC_VALUE
    if isinstance(value, Decimal):
        decimal_value = value
    else:
        try:
            decimal_value = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, AttributeError):
            return None, ERROR_INVALID_NUMERIC_VALUE
    if not decimal_value.is_finite():
        return None, ERROR_INVALID_NUMERIC_VALUE
    return decimal_value, None


def _round_decimal(value: Decimal, precision: int) -> Decimal:
    quant = Decimal("1").scaleb(-precision)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def _resolved_precision(unit_group: str, precision: int | None) -> int:
    if precision is None:
        return _DEFAULT_PRECISION_BY_GROUP.get(unit_group, 2)
    try:
        resolved = int(precision)
    except (TypeError, ValueError):
        return _DEFAULT_PRECISION_BY_GROUP.get(unit_group, 2)
    return max(resolved, 0)


def _decimal_to_json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_TEXT_VALUES
    return False


def _is_missing_unit(unit: Any) -> bool:
    if unit is None:
        return True
    if isinstance(unit, str):
        return unit.strip().lower() in _MISSING_TEXT_VALUES
    return False


def _payload_original_unit(
    original_unit: str | None,
    canonical_unit: str | None,
) -> str | None:
    if canonical_unit is not None:
        return canonical_unit
    if original_unit is None:
        return None
    original_unit_text = str(original_unit).strip()
    return original_unit_text or None


def _payload_display_market(display_market: str | None) -> str:
    if display_market is None:
        return "unknown"
    display_market_text = str(display_market).strip()
    if display_market_text.lower() in _MISSING_TEXT_VALUES:
        return "unknown"
    return display_market_text


def _payload_conversion_source(
    conversion_source: str | None,
    reviewer_corrected: bool,
) -> str:
    if reviewer_corrected:
        return "reviewer_corrected"
    if conversion_source is None:
        return "unknown"
    conversion_source_text = str(conversion_source).strip()
    if conversion_source_text.lower() in _MISSING_TEXT_VALUES:
        return "unknown"
    if conversion_source_text in _ALLOWED_CONVERSION_SOURCES:
        return conversion_source_text
    return conversion_source_text


def _looks_like_forbidden_ai_source(conversion_source: str) -> bool:
    if conversion_source == "ai_structured_from_provided_input":
        return False
    lowered = conversion_source.lower()
    return lowered.startswith(_AI_SOURCE_PREFIXES)


def _json_safe_original_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_to_json_number(value)
    return value


def _code_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
