"""Buyer-facing English and US-imperial presentation helpers.

K keeps source evidence and canonical metric values unchanged.  Every public
surface (copy, Woo attributes, Product JSON-LD and image overlays) can import
this module to render the same audited US-market representation.
"""

from __future__ import annotations

import html
import logging
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


logger = logging.getLogger(__name__)

_CJK_PATTERN = re.compile(
    "["
    "\u1100-\u11ff"  # Hangul Jamo
    "\u3040-\u309f"  # Hiragana
    "\u30a0-\u30ff"  # Katakana
    "\u3130-\u318f"  # Hangul Compatibility Jamo
    "\u31f0-\u31ff"  # Katakana Phonetic Extensions
    "\u3400-\u4dbf"  # CJK Extension A
    "\u4e00-\u9fff"  # Unified Han
    "\ua960-\ua97f"  # Hangul Jamo Extended-A
    "\uac00-\ud7af"  # Hangul syllables
    "\ud7b0-\ud7ff"  # Hangul Jamo Extended-B
    "\uf900-\ufaff"  # CJK compatibility ideographs
    "\uff66-\uff9d"  # Half-width Katakana
    "\U00020000-\U0002ebef"  # CJK Extensions B-F/I
    "\U0002f800-\U0002fa1f"  # Compatibility supplement
    "\U00030000-\U000323af"  # CJK Extensions G-H
    "]"
)
_PACKAGE_SPLIT_PATTERN = re.compile(r"[\n,;，；、|+]+")
_NUMBER_PATTERN = r"(?:(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+)"
_NUMBER_START_BOUNDARY = r"(?<![A-Za-z0-9.,/+^\-])"
_SUPPORTED_METRIC_UNIT_PATTERN = (
    r"millimeters?|millimetres?|centimeters?|centimetres?|kilograms?|grams?|"
    r"milliliters?|millilitres?|liters?|litres?|mm|cm|kg|ml|g|l"
)
_SPELLED_SIZE_WEIGHT_CAPACITY_METRIC_UNIT_PATTERN = (
    r"kilometers?|kilometres?|meters?|metres?|millimeters?|millimetres?|"
    r"centimeters?|centimetres?|metric\s+tons?|tonnes?|kilograms?|"
    r"milligrams?|grams?|milliliters?|millilitres?|centiliters?|centilitres?|"
    r"deciliters?|decilitres?|liters?|litres?"
)
_ALL_SIZE_WEIGHT_CAPACITY_METRIC_UNIT_PATTERN = (
    _SPELLED_SIZE_WEIGHT_CAPACITY_METRIC_UNIT_PATTERN
    + r"|km|mm|cm|mg|kg|cl|dl|ml|m|g|l"
)
_COMBINED_DIMENSION_PATTERN = re.compile(
    rf"{_NUMBER_START_BOUNDARY}(?P<a>{_NUMBER_PATTERN})\s*[x×*]\s*"
    rf"(?P<b>{_NUMBER_PATTERN})"
    rf"(?:\s*[x×*]\s*(?P<c>{_NUMBER_PATTERN}))?\s*"
    r"(?P<unit>mm|millimeters?|millimetres?|cm|centimeters?|centimetres?)\b",
    flags=re.IGNORECASE,
)
_METRIC_RANGE_PATTERN = re.compile(
    rf"{_NUMBER_START_BOUNDARY}(?P<lower>{_NUMBER_PATTERN})\s*"
    rf"(?:(?P<lower_unit>{_SUPPORTED_METRIC_UNIT_PATTERN})\s*)?"
    r"(?P<separator>-|–|—|to)\s*"
    rf"(?P<upper>{_NUMBER_PATTERN})\s*"
    rf"(?P<unit>{_SUPPORTED_METRIC_UNIT_PATTERN})\b",
    flags=re.IGNORECASE,
)
_METRIC_MEASUREMENT_PATTERN = re.compile(
    rf"{_NUMBER_START_BOUNDARY}(?P<value>{_NUMBER_PATTERN})\s*"
    rf"(?P<unit>{_SUPPORTED_METRIC_UNIT_PATTERN})\b",
    flags=re.IGNORECASE,
)
_NUMERIC_RANGE_VALUE_PATTERN = re.compile(
    rf"(?P<lower>{_NUMBER_PATTERN})\s*(?:-|–|—|to)\s*"
    rf"(?P<upper>{_NUMBER_PATTERN})",
    flags=re.IGNORECASE,
)
_REMAINING_METRIC_PATTERN = re.compile(
    rf"(?:{_NUMBER_PATTERN}\s*|/\s*)"
    rf"(?:{_ALL_SIZE_WEIGHT_CAPACITY_METRIC_UNIT_PATTERN})(?:[²³23])?"
    r"(?=$|[^A-Za-z])",
    flags=re.IGNORECASE,
)
_REMAINING_SPELLED_METRIC_PATTERN = re.compile(
    rf"\b(?:{_SPELLED_SIZE_WEIGHT_CAPACITY_METRIC_UNIT_PATTERN})\b",
    flags=re.IGNORECASE,
)
_REMAINING_ABBREVIATED_METRIC_PATTERN = re.compile(
    r"\b(?:km|mm|cm|mg|kg|cl|dl|ml)\b|\bL\b|\bm[²³]\b",
    flags=re.IGNORECASE,
)
_METRIC_POWER_PATTERN = re.compile(
    r"(?:kilometers?|kilometres?|meters?|metres?|millimeters?|millimetres?|"
    r"centimeters?|centimetres?|km|mm|cm|m)\s*"
    r"(?:[²³]|\^[23]|square(?:d)?|cubic|cubed)",
    flags=re.IGNORECASE,
)

_CM_TO_IN = Decimal("0.3937007874")
_MM_TO_IN = Decimal("0.03937007874")
_KG_TO_LB = Decimal("2.2046226218")
_KG_TO_OZ = Decimal("35.27396195")
_G_TO_OZ = Decimal("0.03527396195")
_L_TO_QT = Decimal("1.0566882094")
_ML_TO_QT = Decimal("0.0010566882094")

_BUYER_STANDARD_FIELDS: tuple[tuple[str, str], ...] = (
    ("lumens", "Luminous Flux"),
    ("color_temperature_k", "Color Temperature"),
    ("battery_type", "Battery Type"),
    ("battery_capacity_mah", "Battery Capacity"),
    ("charge_time_h", "Charge Time"),
    ("runtime_h", "Runtime"),
    ("ip_rating", "IP Rating"),
    ("dimensions.length", "Length"),
    ("dimensions.width", "Width"),
    ("dimensions.height", "Height"),
    ("weight", "Weight"),
    ("material", "Material"),
    ("mount_type", "Mount Type"),
    ("certifications", "Certifications"),
)


def contains_cjk(value: Any) -> bool:
    """Detect Han, Japanese kana, or Hangul, including HTML entities."""

    return bool(_CJK_PATTERN.search(html.unescape(str(value or ""))))


def buyer_english_text(value: Any, *, limit: int | None = None) -> str | None:
    """Return normalized non-CJK text, otherwise fail closed with ``None``."""

    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if not text or contains_cjk(text):
        return None
    return text[:limit] if limit is not None else text


def normalize_package_includes(
    value: Any,
    *,
    reject_cjk: bool = True,
    max_items: int = 100,
) -> list[str]:
    """Normalize one-English-component-per-row package contents.

    A string is accepted for supplier/provider interoperability and split on
    conservative list separators.  Public K payloads normally submit a list.
    Duplicate rows are removed without changing their order.
    """

    if isinstance(value, str):
        candidates: list[Any] = _PACKAGE_SPLIT_PATTERN.split(value)
    elif isinstance(value, list):
        candidates = value
    else:
        return []

    output: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        if not isinstance(raw, (str, int, float, Decimal)) or isinstance(raw, bool):
            continue
        text = " ".join(str(raw).split()).strip()
        # Strip real list bullets, but never mistake a decimal measurement such
        # as ``1.4 L pot`` for an ordered-list prefix (``1. item``).
        text = re.sub(r"^(?:[-*•]\s*|\d+[.)]\s+)", "", text).strip()
        if not text:
            continue
        if contains_cjk(text):
            if reject_cjk:
                raise ValueError("package_includes must contain English-only items")
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text[:255])
        if len(output) >= max_items:
            break
    return output


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _one_decimal(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def cm_to_inches(value: Any) -> str | None:
    parsed = _decimal(value)
    return _one_decimal(parsed * _CM_TO_IN) if parsed is not None else None


def mm_to_inches(value: Any) -> str | None:
    parsed = _decimal(value)
    return _one_decimal(parsed * _MM_TO_IN) if parsed is not None else None


def kg_to_pounds(value: Any) -> str | None:
    parsed = _decimal(value)
    return _one_decimal(parsed * _KG_TO_LB) if parsed is not None else None


def kg_to_ounces(value: Any) -> str | None:
    parsed = _decimal(value)
    return _one_decimal(parsed * _KG_TO_OZ) if parsed is not None else None


def g_to_ounces(value: Any) -> str | None:
    parsed = _decimal(value)
    return _one_decimal(parsed * _G_TO_OZ) if parsed is not None else None


def liters_to_quarts(value: Any) -> str | None:
    parsed = _decimal(value)
    return _one_decimal(parsed * _L_TO_QT) if parsed is not None else None


def _canonical_unit(unit: Any) -> str:
    raw = str(unit or "").strip().casefold()
    aliases = {
        "centimeter": "cm",
        "centimeters": "cm",
        "centimetre": "cm",
        "centimetres": "cm",
        "millimeter": "mm",
        "millimeters": "mm",
        "millimetre": "mm",
        "millimetres": "mm",
        "kilogram": "kg",
        "kilograms": "kg",
        "gram": "g",
        "grams": "g",
        "liter": "l",
        "liters": "l",
        "litre": "l",
        "litres": "l",
        "milliliter": "ml",
        "milliliters": "ml",
        "millilitre": "ml",
        "millilitres": "ml",
    }
    return aliases.get(raw, raw)


def _convert_scalar(value: Any, unit: str) -> tuple[str, str] | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    canonical = _canonical_unit(unit)
    if canonical == "cm":
        return _one_decimal(parsed * _CM_TO_IN), "in"
    if canonical == "mm":
        return _one_decimal(parsed * _MM_TO_IN), "in"
    if canonical == "kg":
        pounds = parsed * _KG_TO_LB
        if pounds < 1:
            return _one_decimal(parsed * _KG_TO_OZ), "oz"
        return _one_decimal(pounds), "lb"
    if canonical == "g":
        return _one_decimal(parsed * _G_TO_OZ), "oz"
    if canonical == "l":
        return _one_decimal(parsed * _L_TO_QT), "qt"
    if canonical == "ml":
        return _one_decimal(parsed * _ML_TO_QT), "qt"
    return None


def _convert_values_same_unit(
    values: list[Any],
    unit: str,
) -> tuple[list[str], str] | None:
    """Convert a range/list without mixing lb and oz inside one result."""

    parsed = [_decimal(value) for value in values]
    if not parsed or any(value is None for value in parsed):
        return None
    numbers = [value for value in parsed if value is not None]
    canonical = _canonical_unit(unit)
    if canonical == "kg":
        pounds = [value * _KG_TO_LB for value in numbers]
        if all(value < 1 for value in pounds):
            return [_one_decimal(value * _KG_TO_OZ) for value in numbers], "oz"
        return [_one_decimal(value) for value in pounds], "lb"
    converted = [_convert_scalar(value, canonical) for value in numbers]
    if not converted or any(value is None for value in converted):
        return None
    units = {value[1] for value in converted if value is not None}
    if len(units) != 1:
        return None
    return [value[0] for value in converted if value is not None], units.pop()


def _is_size_weight_capacity_metric_unit(unit: Any) -> bool:
    raw = str(unit or "").strip()
    return bool(
        raw
        and re.fullmatch(
            _ALL_SIZE_WEIGHT_CAPACITY_METRIC_UNIT_PATTERN,
            raw,
            flags=re.IGNORECASE,
        )
    )


def imperial_measurement(value: Any, unit: Any) -> tuple[str, str] | None:
    """Convert a scalar/range/list metric measurement for a US buyer."""

    canonical = _canonical_unit(unit)
    if canonical not in {"cm", "mm", "kg", "g", "l", "ml"}:
        return None
    if isinstance(value, dict):
        converted = _convert_values_same_unit(
            [value.get("min"), value.get("max")], canonical
        )
        if converted is None:
            return None
        amounts, output_unit = converted
        rendered = (
            amounts[0]
            if amounts[0] == amounts[1]
            else f"{amounts[0]}–{amounts[1]}"
        )
        return rendered, output_unit
    if isinstance(value, list):
        converted = _convert_values_same_unit(value, canonical)
        if converted is None:
            return None
        amounts, output_unit = converted
        return ", ".join(amounts), output_unit
    if isinstance(value, str):
        range_match = _NUMERIC_RANGE_VALUE_PATTERN.fullmatch(value.strip())
        if range_match is not None:
            converted = _convert_values_same_unit(
                [range_match.group("lower"), range_match.group("upper")],
                canonical,
            )
            if converted is None:
                return None
            amounts, output_unit = converted
            return f"{amounts[0]}–{amounts[1]}", output_unit
    return _convert_scalar(value, canonical)


def imperial_dimensions_mm(value: str) -> str | None:
    """Render ``160×160×110 mm`` as ``6.3 × 6.3 × 4.3 in``."""

    match = _COMBINED_DIMENSION_PATTERN.fullmatch(str(value or "").strip())
    if match is None or _canonical_unit(match.group("unit")) != "mm":
        return None
    axes = [match.group("a"), match.group("b"), match.group("c")]
    rendered = [mm_to_inches(axis) for axis in axes if axis is not None]
    if not rendered or any(item is None for item in rendered):
        return None
    return " × ".join(item for item in rendered if item is not None) + " in"


def imperialize_text(value: Any) -> str | None:
    """Convert complete metric expressions or fail closed on any residue."""

    if not isinstance(value, str) or not value.strip() or contains_cjk(value):
        return None

    # Preserve ordinary markup while making common encoded spacing convertible.
    source = re.sub(
        r"(?:&nbsp;|&#0*160;|&#x0*a0;|\u00a0)",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    # Linear conversion factors cannot be reused for area or volume.  Drop the
    # entire public string instead of turning (for example) cm² into a false in².
    if _METRIC_POWER_PATTERN.search(html.unescape(source)):
        return None

    def replace_dimensions(match: re.Match[str]) -> str:
        unit = _canonical_unit(match.group("unit"))
        converter = mm_to_inches if unit == "mm" else cm_to_inches
        axes = [match.group("a"), match.group("b"), match.group("c")]
        rendered = [converter(axis) for axis in axes if axis is not None]
        if not rendered or any(item is None for item in rendered):
            return match.group(0)
        return " × ".join(item for item in rendered if item is not None) + " in"

    rendered = _COMBINED_DIMENSION_PATTERN.sub(replace_dimensions, source)
    range_failed = False

    def replace_range(match: re.Match[str]) -> str:
        nonlocal range_failed
        unit = match.group("unit")
        lower_unit = match.group("lower_unit")
        if lower_unit and _canonical_unit(lower_unit) != _canonical_unit(unit):
            range_failed = True
            return match.group(0)
        converted = imperial_measurement(
            {"min": match.group("lower"), "max": match.group("upper")},
            unit,
        )
        if converted is None:
            range_failed = True
            return match.group(0)
        amount, output_unit = converted
        return f"{amount} {output_unit}"

    rendered = _METRIC_RANGE_PATTERN.sub(replace_range, rendered)
    if range_failed:
        return None

    def replace_measurement(match: re.Match[str]) -> str:
        converted = imperial_measurement(match.group("value"), match.group("unit"))
        if converted is None:
            return match.group(0)
        amount, unit = converted
        return f"{amount} {unit}"

    rendered = _METRIC_MEASUREMENT_PATTERN.sub(replace_measurement, rendered).strip()
    unescaped = html.unescape(rendered)
    if (
        _REMAINING_METRIC_PATTERN.search(unescaped)
        or _REMAINING_SPELLED_METRIC_PATTERN.search(unescaped)
        or _REMAINING_ABBREVIATED_METRIC_PATTERN.search(unescaped)
    ):
        return None
    return rendered


def _unsafe_buyer_string_reason(value: str) -> str | None:
    if not value.strip():
        return None
    if contains_cjk(value):
        return "non_english_script"
    if imperialize_text(value) is None:
        return "unconverted_metric"
    return None


def _unsafe_tree_reasons(value: Any) -> set[str]:
    if isinstance(value, str):
        reason = _unsafe_buyer_string_reason(value)
        return {reason} if reason else set()
    if isinstance(value, list):
        return {
            reason
            for item in value
            for reason in _unsafe_tree_reasons(item)
        }
    if isinstance(value, dict):
        reasons = {
            "non_english_script"
            for key in value
            if contains_cjk(key)
        }
        for item in value.values():
            reasons.update(_unsafe_tree_reasons(item))
        return reasons
    return set()


def _safe_log_key(value: Any) -> str:
    key = str(value or "")
    return key if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", key) else "<field>"


def buyer_safe_tree(value: Any, *, field_path: str = "") -> Any:
    """Recursively drop CJK strings/rows and imperialize remaining prose.

    This is the final P-series fail-safe.  Evidence objects remain untouched in
    K; only the disposable buyer-facing projection is filtered.
    """

    path = field_path or "$"
    if isinstance(value, str):
        clean = imperialize_text(value)
        if clean is None and value.strip():
            logger.warning(
                "Dropped buyer-facing field path=%s reason=%s",
                path,
                _unsafe_buyer_string_reason(value) or "invalid_text",
            )
        return clean
    if isinstance(value, list):
        output: list[Any] = []
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            if isinstance(item, dict):
                reasons = _unsafe_tree_reasons(item)
                if reasons:
                    logger.warning(
                        "Dropped buyer-facing row path=%s reason=%s",
                        item_path,
                        ",".join(sorted(reasons)),
                    )
                    continue
            clean = buyer_safe_tree(item, field_path=item_path)
            if clean not in (None, "", [], {}):
                output.append(clean)
        return output
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if contains_cjk(key):
                logger.warning(
                    "Dropped buyer-facing field path=%s.%s reason=non_english_script",
                    path,
                    "<non-english-key>",
                )
                continue
            clean = buyer_safe_tree(
                item,
                field_path=f"{path}.{_safe_log_key(key)}",
            )
            if clean not in (None, "", [], {}):
                output[str(key)] = clean
        return output
    return value


def _spec_node(specs: dict[str, Any], path: str) -> tuple[Any, Any]:
    current: Any = specs
    parent: Any = None
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None, None
        parent = current
        current = current[segment]
    return current, parent


def _display_source_value(value: Any) -> str | None:
    if isinstance(value, dict):
        lower = _display_source_value(value.get("min"))
        upper = _display_source_value(value.get("max"))
        if not lower or not upper:
            return None
        return lower if lower == upper else f"{lower}–{upper}"
    if isinstance(value, list):
        parts = [part for item in value if (part := _display_source_value(item))]
        return ", ".join(parts) or None
    if isinstance(value, float):
        return f"{value:g}"
    if value is None or isinstance(value, bool):
        return None
    rendered = str(value).strip()
    return rendered or None


def buyer_spec_rows(
    structured_specs: Any,
    *,
    target_market: str = "US",
) -> list[dict[str, str | None]]:
    """Project canonical facts into English, pre-converted display rows.

    The original source-preserving contract remains untouched.  Copy models
    consume these rows when they need to quote a specification, so they never
    calculate units or translate supplier labels themselves.
    """

    if not isinstance(structured_specs, dict):
        return []
    imperial = target_market.strip().upper() in {
        "US",
        "USA",
        "UNITED STATES",
        "UNITED STATES OF AMERICA",
    }
    rows: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for path, label in _BUYER_STANDARD_FIELDS:
        node, parent = _spec_node(structured_specs, path)
        if not isinstance(node, dict):
            continue
        raw_value: Any = node.get("value")
        rendered = _display_source_value(raw_value)
        if rendered and contains_cjk(rendered):
            raw_value = node.get("value_en")
            rendered = buyer_english_text(raw_value)
        if not rendered:
            logger.warning(
                "Skipped buyer specification path=%s reason=non_english_script_or_empty",
                path,
            )
            continue
        unit = str(node.get("unit") or "").strip()
        if not unit and isinstance(parent, dict):
            unit = str(parent.get("unit") or "").strip()
        display_value = rendered
        display_unit = buyer_english_text(unit, limit=40) if unit else None
        if imperial and unit:
            converted = imperial_measurement(raw_value, unit)
            if converted is not None:
                display_value, display_unit = converted
            elif _is_size_weight_capacity_metric_unit(unit):
                logger.warning(
                    "Skipped buyer specification path=%s reason=unconverted_metric",
                    path,
                )
                continue
        elif imperial:
            converted_text = imperialize_text(rendered)
            if converted_text is None:
                logger.warning(
                    "Skipped buyer specification path=%s reason=unconverted_metric",
                    path,
                )
                continue
            display_value = converted_text
        if contains_cjk(display_value) or (display_unit and contains_cjk(display_unit)):
            logger.warning(
                "Skipped buyer specification path=%s reason=non_english_script",
                path,
            )
            continue
        rows.append(
            {
                "path": path,
                "label": label,
                "display_value": display_value,
                "display_unit": display_unit,
            }
        )
        seen.add(label.casefold())

    additional = structured_specs.get("additional_specs")
    if isinstance(additional, list):
        for index, item in enumerate(additional):
            if not isinstance(item, dict):
                continue
            label = buyer_english_text(item.get("label_en"), limit=120)
            value = buyer_english_text(item.get("value_en"), limit=500)
            if not label or not value or label.casefold() in seen:
                logger.warning(
                    "Skipped buyer specification path=additional_specs[%s] "
                    "reason=missing_english_projection_or_duplicate",
                    index,
                )
                continue
            unit = buyer_english_text(item.get("unit"), limit=40)
            display_value = value
            display_unit = unit
            if imperial and unit:
                converted = imperial_measurement(value, unit)
                if converted is not None:
                    display_value, display_unit = converted
                elif _is_size_weight_capacity_metric_unit(unit):
                    logger.warning(
                        "Skipped buyer specification path=additional_specs[%s] "
                        "reason=unconverted_metric",
                        index,
                    )
                    continue
            else:
                converted_text = imperialize_text(value) if imperial else value
                if not converted_text:
                    logger.warning(
                        "Skipped buyer specification path=additional_specs[%s] "
                        "reason=non_english_script_or_unconverted_metric",
                        index,
                    )
                    continue
                if converted_text != value:
                    display_value, display_unit = converted_text, None
            rows.append(
                {
                    "path": "additional_specs."
                    + str(item.get("key") or index),
                    "label": label,
                    "display_value": display_value,
                    "display_unit": display_unit,
                }
            )
            seen.add(label.casefold())
    return rows


def buyer_display_structured_specs(
    structured_specs: Any,
    *,
    target_market: str = "US",
) -> dict[str, Any]:
    """Stable model-input envelope for already converted public specs."""

    return {
        "language": "en",
        "unit_system": "imperial" if target_market.strip().upper() in {
            "US",
            "USA",
            "UNITED STATES",
            "UNITED STATES OF AMERICA",
        } else "metric",
        "rows": buyer_spec_rows(
            structured_specs,
            target_market=target_market,
        ),
    }
