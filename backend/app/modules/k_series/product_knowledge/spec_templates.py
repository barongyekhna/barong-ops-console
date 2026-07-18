"""Leaf-category specification templates and paste-result safeguards.

Templates are global K taxonomy configuration.  Only an ``approved`` template
participates in product completeness or the K -> P gate; AI-created drafts are
inert until an operator reviews them.  Paste parsing is also fail-closed: every
returned source label and raw value must be traceable to the pasted text.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ....services.data_isolation import without_org_data_isolation
from .buyer_display import contains_cjk
from .models import KCategorySpecTemplate, KProductKnowledgeProduct
from .structured_specs import (
    STANDARD_SPEC_KEYS,
    normalize_combined_dimensions,
    standard_spec_key_for_label,
)


CATEGORY_SPEC_TREES = frozenset({"google", "amazon"})
CATEGORY_SPEC_STATUSES = frozenset({"draft", "approved"})
CATEGORY_SPEC_TARGETS = frozenset({"additional", "standard"})
CATEGORY_SPEC_VALUE_TYPES = frozenset({"number", "text", "enum", "boolean"})

_CATEGORY_TABLES = {
    "google": "k_category_google",
    "amazon": "k_category_amazon",
}
_SNAKE_CASE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_HAS_ENGLISH_LETTER = re.compile(r"[A-Za-z]")
_WHITESPACE = re.compile(r"\s+")
_EMPTY_SPEC_VALUES = frozenset(
    {
        "",
        "-",
        "--",
        "n/a",
        "na",
        "none",
        "null",
        "unknown",
        "not provided",
        "not specified",
        "无",
        "暂无",
        "未知",
        "未提供",
        "未标注",
    }
)
_UNIT_FACTORS: dict[str, tuple[str, Decimal]] = {
    "毫米": ("length", Decimal("0.001")),
    "millimeters": ("length", Decimal("0.001")),
    "millimeter": ("length", Decimal("0.001")),
    "mm": ("length", Decimal("0.001")),
    "厘米": ("length", Decimal("0.01")),
    "centimeters": ("length", Decimal("0.01")),
    "centimeter": ("length", Decimal("0.01")),
    "cm": ("length", Decimal("0.01")),
    "英寸": ("length", Decimal("0.0254")),
    "inches": ("length", Decimal("0.0254")),
    "inch": ("length", Decimal("0.0254")),
    "in": ("length", Decimal("0.0254")),
    "米": ("length", Decimal("1")),
    "m": ("length", Decimal("1")),
    "毫升": ("volume", Decimal("0.001")),
    "milliliters": ("volume", Decimal("0.001")),
    "milliliter": ("volume", Decimal("0.001")),
    "ml": ("volume", Decimal("0.001")),
    "liters": ("volume", Decimal("1")),
    "liter": ("volume", Decimal("1")),
    "升": ("volume", Decimal("1")),
    "l": ("volume", Decimal("1")),
    "毫克": ("mass", Decimal("0.000001")),
    "mg": ("mass", Decimal("0.000001")),
    "kilograms": ("mass", Decimal("1")),
    "kilogram": ("mass", Decimal("1")),
    "千克": ("mass", Decimal("1")),
    "公斤": ("mass", Decimal("1")),
    "kg": ("mass", Decimal("1")),
    "grams": ("mass", Decimal("0.001")),
    "gram": ("mass", Decimal("0.001")),
    "克": ("mass", Decimal("0.001")),
    "g": ("mass", Decimal("0.001")),
    "minutes": ("time", Decimal("0.01666666666666666666666666667")),
    "minute": ("time", Decimal("0.01666666666666666666666666667")),
    "分钟": ("time", Decimal("0.01666666666666666666666666667")),
    "min": ("time", Decimal("0.01666666666666666666666666667")),
    "hours": ("time", Decimal("1")),
    "hour": ("time", Decimal("1")),
    "小时": ("time", Decimal("1")),
    "hr": ("time", Decimal("1")),
    "h": ("time", Decimal("1")),
    "毫安小时": ("battery", Decimal("0.001")),
    "毫安时": ("battery", Decimal("0.001")),
    "mah": ("battery", Decimal("0.001")),
    "安培小时": ("battery", Decimal("1")),
    "安时": ("battery", Decimal("1")),
    "ah": ("battery", Decimal("1")),
    "lumens": ("luminous_flux", Decimal("1")),
    "lumen": ("luminous_flux", Decimal("1")),
    "流明": ("luminous_flux", Decimal("1")),
    "lm": ("luminous_flux", Decimal("1")),
}


class SpecTemplateValidationError(ValueError):
    """A template or provider response violated the Round 9 contract."""


def normalize_category_tree(value: Any) -> str:
    tree = str(value or "").strip().lower()
    if tree not in CATEGORY_SPEC_TREES:
        raise SpecTemplateValidationError(
            "category_tree must be 'google' or 'amazon'"
        )
    return tree


def normalize_template_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status not in CATEGORY_SPEC_STATUSES:
        raise SpecTemplateValidationError("status must be 'draft' or 'approved'")
    return status


def category_leaf(
    db: Session,
    *,
    category_tree: str,
    category_id: Any,
) -> dict[str, Any] | None:
    """Return one real leaf from the selected K taxonomy tree."""

    tree = normalize_category_tree(category_tree)
    normalized_id = str(category_id or "").strip()
    if not normalized_id or len(normalized_id) > 32:
        return None
    table = _CATEGORY_TABLES[tree]
    with without_org_data_isolation():
        row = db.execute(
            text(
                f"SELECT id, name, full_path, level, is_leaf FROM {table} "
                "WHERE id = :category_id AND is_leaf = true"
            ),
            {"category_id": normalized_id},
        ).mappings().first()
    return dict(row) if row is not None else None


def effective_product_category(product: Any) -> tuple[str, str] | None:
    """Resolve the taxonomy identity that governs a product's specs."""

    channel = str(getattr(product, "channel", None) or "dtc").strip().lower()
    if channel == "amazon":
        category_id = str(
            getattr(product, "amazon_category_id", None) or ""
        ).strip()
        return ("amazon", category_id) if category_id else None
    category_id = str(
        getattr(product, "google_product_category", None) or ""
    ).strip()
    return ("google", category_id) if category_id else None


def get_spec_template(
    db: Session,
    *,
    category_tree: str,
    category_id: Any,
    approved_only: bool = False,
) -> KCategorySpecTemplate | None:
    tree = normalize_category_tree(category_tree)
    normalized_id = str(category_id or "").strip()
    if not normalized_id:
        return None
    query = select(KCategorySpecTemplate).where(
        KCategorySpecTemplate.category_tree == tree,
        KCategorySpecTemplate.category_id == normalized_id,
    )
    if approved_only:
        query = query.where(KCategorySpecTemplate.status == "approved")
    with without_org_data_isolation():
        return db.scalar(query)


def approved_template_for_product(
    db: Session,
    product: Any,
) -> KCategorySpecTemplate | None:
    category = effective_product_category(product)
    if category is None:
        return None
    tree, category_id = category
    return get_spec_template(
        db,
        category_tree=tree,
        category_id=category_id,
        approved_only=True,
    )


def _required_text(value: Any, *, field_name: str, limit: int) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        raise SpecTemplateValidationError(f"{field_name} is required")
    if len(text_value) > limit:
        raise SpecTemplateValidationError(
            f"{field_name} must be at most {limit} characters"
        )
    return text_value


def _optional_text(value: Any, *, field_name: str, limit: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    if len(text_value) > limit:
        raise SpecTemplateValidationError(
            f"{field_name} must be at most {limit} characters"
        )
    return text_value


def normalize_template_fields(
    raw_fields: Any,
    *,
    ai_draft: bool = False,
) -> list[dict[str, Any]]:
    """Validate and canonicalize operator/AI-authored template fields."""

    if not isinstance(raw_fields, list):
        raise SpecTemplateValidationError("fields must be an array")
    if not raw_fields:
        raise SpecTemplateValidationError("fields must contain at least one field")
    if len(raw_fields) > 50:
        raise SpecTemplateValidationError("fields must contain at most 50 fields")
    if ai_draft and not 8 <= len(raw_fields) <= 12:
        raise SpecTemplateValidationError(
            "AI draft must contain between 8 and 12 fields"
        )

    fields: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, raw in enumerate(raw_fields, start=1):
        if not isinstance(raw, dict):
            raise SpecTemplateValidationError(
                f"fields[{index}] must be an object"
            )
        key = _required_text(raw.get("key"), field_name="key", limit=128).lower()
        if _SNAKE_CASE_KEY.fullmatch(key) is None:
            raise SpecTemplateValidationError(
                f"Template field key must be snake_case English: {key}"
            )
        if key in seen_keys:
            raise SpecTemplateValidationError(f"Duplicate template field key: {key}")
        seen_keys.add(key)

        target = str(raw.get("target") or "").strip().lower()
        if ai_draft and target not in CATEGORY_SPEC_TARGETS:
            # AI drafts are pre-approval material: coerce made-up buckets
            # ("common"/"custom"/...) instead of failing the whole draft.
            target = "standard" if key in STANDARD_SPEC_KEYS else "additional"
        if target not in CATEGORY_SPEC_TARGETS:
            raise SpecTemplateValidationError(
                f"Template field '{key}' has an invalid target"
            )
        if key in STANDARD_SPEC_KEYS and target != "standard":
            if ai_draft:
                target = "standard"
            else:
                raise SpecTemplateValidationError(
                    f"Standard spec key '{key}' must use target=standard"
                )
        if target == "standard" and key not in STANDARD_SPEC_KEYS:
            if ai_draft:
                # Drafts may invent variants of canonical keys (weight_g...).
                # Rename via label inference when possible, else demote.
                inferred_from_labels = {
                    inferred
                    for label in (raw.get("label_zh"), raw.get("label_en"))
                    if isinstance(label, str)
                    and (inferred := standard_spec_key_for_label(label)) is not None
                }
                if len(inferred_from_labels) == 1:
                    key = next(iter(inferred_from_labels))
                else:
                    target = "additional"
            else:
                raise SpecTemplateValidationError(
                    f"target=standard requires a canonical standard key: {key}"
                )

        label_zh = _required_text(
            raw.get("label_zh"), field_name="label_zh", limit=255
        )
        label_en = _required_text(
            raw.get("label_en"), field_name="label_en", limit=255
        )
        if contains_cjk(label_en) or _HAS_ENGLISH_LETTER.search(label_en) is None:
            raise SpecTemplateValidationError(
                f"Template field '{key}' requires an English label_en"
            )
        inferred_standard_keys = {
            inferred
            for label in (label_zh, label_en)
            if (inferred := standard_spec_key_for_label(label)) is not None
        }
        if inferred_standard_keys and inferred_standard_keys != {key}:
            inferred = sorted(inferred_standard_keys)[0]
            if ai_draft:
                key = inferred
                target = "standard"
            else:
                raise SpecTemplateValidationError(
                    f"Template label for '{key}' belongs to standard key "
                    f"'{inferred}'; use that key with target=standard"
                )

        value_type = str(raw.get("value_type") or "").strip().lower()
        if value_type not in CATEGORY_SPEC_VALUE_TYPES:
            raise SpecTemplateValidationError(
                f"Template field '{key}' has an invalid value_type"
            )
        if key == "dimensions" and value_type != "text":
            raise SpecTemplateValidationError(
                "Standard dimensions must use value_type=text (L x W x H)"
            )

        enum_options: list[str] | None = None
        raw_options = raw.get("enum_options")
        if value_type == "enum":
            if not isinstance(raw_options, list) or not raw_options:
                raise SpecTemplateValidationError(
                    f"Enum field '{key}' requires enum_options"
                )
            if len(raw_options) > 50:
                raise SpecTemplateValidationError(
                    f"Enum field '{key}' has too many enum_options"
                )
            enum_options = []
            option_keys: set[str] = set()
            for raw_option in raw_options:
                option = _required_text(
                    raw_option,
                    field_name=f"enum_options for {key}",
                    limit=255,
                )
                if contains_cjk(option):
                    raise SpecTemplateValidationError(
                        f"Enum field '{key}' requires buyer-facing enum_options "
                        "without CJK text"
                    )
                option_key = option.casefold()
                if option_key in option_keys:
                    raise SpecTemplateValidationError(
                        f"Enum field '{key}' has duplicate enum_options"
                    )
                option_keys.add(option_key)
                enum_options.append(option)
        elif raw_options not in (None, []):
            raise SpecTemplateValidationError(
                f"Non-enum field '{key}' cannot define enum_options"
            )

        required = raw.get("required", False)
        if not isinstance(required, bool):
            raise SpecTemplateValidationError(
                f"Template field '{key}' required must be a boolean"
            )

        fields.append(
            {
                "key": key,
                "target": target,
                "label_zh": label_zh,
                "label_en": label_en,
                "value_type": value_type,
                "unit": _optional_text(
                    raw.get("unit"), field_name="unit", limit=50
                ),
                "required": required,
                "enum_options": enum_options,
                "hint_zh": _optional_text(
                    raw.get("hint_zh"), field_name="hint_zh", limit=500
                ),
            }
        )
    return fields


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().casefold() not in _EMPTY_SPEC_VALUES
    if isinstance(value, (bool, int, float, Decimal)):
        return True
    if isinstance(value, list):
        return any(_has_value(item) for item in value)
    if not isinstance(value, dict):
        return False
    if "value" in value and _has_value(value.get("value")):
        return True
    if "raw_value" in value and _has_value(value.get("raw_value")):
        return True
    metadata_keys = {
        "evidence",
        "key",
        "label",
        "label_en",
        "source_label",
        "unit",
        "value_en",
    }
    return any(
        _has_value(child)
        for key, child in value.items()
        if key not in metadata_keys
    )


def _typed_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value)).is_finite()
        except InvalidOperation:
            return False
    if isinstance(value, str):
        try:
            return Decimal(value.strip()).is_finite()
        except (InvalidOperation, ValueError):
            return False
    if isinstance(value, list):
        return bool(value) and all(_typed_number(item) for item in value)
    if isinstance(value, dict):
        bounds = [value.get(key) for key in ("min", "max") if key in value]
        return bool(bounds) and all(_typed_number(item) for item in bounds)
    return False


def _typed_text(value: Any) -> bool:
    if isinstance(value, str):
        return _has_value(value) and not contains_cjk(value)
    if isinstance(value, list):
        return bool(value) and all(_typed_text(item) for item in value)
    return False


def _field_has_valid_value(field: dict[str, Any], node: Any) -> bool:
    """Validate a required value against its approved template contract."""

    if not _has_value(node):
        return False
    if field["key"] == "dimensions" and isinstance(node, dict):
        axes_complete = all(
            isinstance(node.get(axis), dict)
            and _typed_number(node[axis].get("value"))
            for axis in ("length", "width", "height")
        )
        return axes_complete and (
            not field.get("unit") or bool(str(node.get("unit") or "").strip())
        )

    candidate = node
    if isinstance(node, dict):
        candidate = node.get("value")
        if field["value_type"] in {"text", "enum"} and _typed_text(
            node.get("value_en")
        ):
            candidate = node.get("value_en")

    value_type = field["value_type"]
    if value_type == "number":
        if not _typed_number(candidate):
            return False
        # A numeric template unit describes a measured quantity.  Require the
        # saved canonical node to retain a unit, while allowing normalization
        # (for example mm -> cm) to change its spelling/value.
        if not field.get("unit"):
            return True
        if isinstance(node, dict) and str(node.get("unit") or "").strip():
            return True
        raw_value = str(node.get("raw_value") or "") if isinstance(node, dict) else ""
        unit = str(field["unit"]).strip()
        return bool(
            unit
            and re.search(
                rf"(?<![A-Za-z]){re.escape(unit)}(?![A-Za-z])",
                raw_value,
                flags=re.IGNORECASE,
            )
        )
    if value_type == "boolean":
        return isinstance(candidate, bool)
    if value_type == "enum":
        if not isinstance(candidate, str):
            return False
        return any(
            candidate.strip().casefold() == str(option).strip().casefold()
            for option in field.get("enum_options") or []
        )
    return _typed_text(candidate)


def missing_required_fields(
    fields: Any,
    structured_specs: Any,
) -> list[str]:
    """Return required template keys that have no evidence-backed value."""

    normalized_fields = normalize_template_fields(fields)
    specs = structured_specs if isinstance(structured_specs, dict) else {}
    additional_by_key = {
        str(item.get("key") or "").strip(): item
        for item in specs.get("additional_specs") or []
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }
    missing: list[str] = []
    for field in normalized_fields:
        if not field["required"]:
            continue
        if field["target"] == "standard":
            present = _field_has_valid_value(field, specs.get(field["key"]))
        else:
            present = _field_has_valid_value(
                field,
                additional_by_key.get(field["key"]),
            )
        if not present:
            missing.append(field["key"])
    return missing


def missing_required_for_product(db: Session, product: Any) -> list[str]:
    template = approved_template_for_product(db, product)
    if template is None:
        return []
    return missing_required_fields(
        template.fields_json,
        getattr(product, "structured_specs_json", None),
    )


def refresh_product_spec_completeness(db: Session, product: Any) -> list[str]:
    """Persist the current diagnostic while keeping saves non-blocking."""

    missing = missing_required_for_product(db, product)
    product.specs_incomplete = bool(missing)
    product.specs_missing_required_json = missing or None
    return missing


def refresh_category_product_completeness(
    db: Session,
    *,
    category_tree: str,
    category_id: Any,
) -> int:
    """Refresh products after an approved template is edited or withdrawn."""

    tree = normalize_category_tree(category_tree)
    normalized_id = str(category_id or "").strip()
    if tree == "amazon":
        query = select(KProductKnowledgeProduct).where(
            KProductKnowledgeProduct.amazon_category_id == normalized_id,
            func.lower(KProductKnowledgeProduct.channel) == "amazon",
        )
    else:
        query = select(KProductKnowledgeProduct).where(
            KProductKnowledgeProduct.google_product_category == normalized_id,
            func.lower(KProductKnowledgeProduct.channel) != "amazon",
        )
    template = get_spec_template(
        db,
        category_tree=tree,
        category_id=normalized_id,
        approved_only=True,
    )
    products = list(db.scalars(query))
    for product in products:
        missing = (
            missing_required_fields(
                template.fields_json,
                product.structured_specs_json,
            )
            if template is not None
            else []
        )
        product.specs_incomplete = bool(missing)
        product.specs_missing_required_json = missing or None
        db.add(product)
    return len(products)


def _evidence_token(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return _WHITESPACE.sub("", normalized)


def _is_source_evidence(value: str, raw_text: str) -> bool:
    token = _evidence_token(value)
    return bool(token and token in _evidence_token(raw_text))


def _is_source_pair(source_label: str, raw_value: str, raw_text: str) -> bool:
    """Require label/value co-occurrence instead of mixing unrelated rows."""

    label_token = _evidence_token(source_label)
    value_token = _evidence_token(raw_value)
    if not label_token or not value_token:
        return False
    return any(
        label_token in (line_token := _evidence_token(line))
        and value_token in line_token
        for line in raw_text.splitlines()
        if line.strip()
    )


def _normalized_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _normalized_parsed_value(field: dict[str, Any], value: Any) -> Any | None:
    value_type = field["value_type"]
    if value_type == "number":
        return _normalized_number(value)
    if value_type == "boolean":
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().casefold()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    normalized_text = value.strip()
    if value_type == "enum":
        options = field.get("enum_options") or []
        option = next(
            (
                candidate
                for candidate in options
                if candidate.casefold() == normalized_text.casefold()
            ),
            None,
        )
        return option
    # Text values are buyer-facing after confirmation.  A provider that did
    # not translate the Chinese source has not completed the match.
    if contains_cjk(normalized_text):
        return None
    return normalized_text[:2000]


def _unit_token(value: Any) -> str | None:
    text_value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    for alias in sorted(_UNIT_FACTORS, key=len, reverse=True):
        if re.search(
            rf"(?<![a-z]){re.escape(alias)}(?![a-z])",
            text_value,
        ):
            return alias
    return None


def _source_number(value: str) -> Decimal | None:
    matches = re.findall(
        r"(?<![A-Za-z])[-+]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?",
        unicodedata.normalize("NFKC", value),
    )
    if len(matches) != 1:
        return None
    try:
        number = Decimal(matches[0].replace(",", ""))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _number_matches_evidence(
    field: dict[str, Any],
    value: int | float,
    *,
    raw_value: str,
    source_label: str,
) -> bool:
    source_number = _source_number(raw_value)
    if source_number is None:
        return False
    normalized_number = Decimal(str(value))
    target_unit = _unit_token(field.get("unit"))
    source_unit = _unit_token(f"{raw_value} {source_label}")
    expected = source_number
    if target_unit is not None:
        if source_unit is None:
            # A unit declared only by the approved template means the pasted
            # bare scalar already uses that input unit.
            source_unit = target_unit
        source_group, source_factor = _UNIT_FACTORS[source_unit]
        target_group, target_factor = _UNIT_FACTORS[target_unit]
        if source_group != target_group:
            return False
        expected = source_number * source_factor / target_factor
    elif field.get("unit"):
        # Unknown/custom units can still be proven when the exact template
        # unit occurs in the source; conversion is deliberately not guessed.
        unit = str(field["unit"]).strip()
        if not re.search(
            rf"(?<![A-Za-z]){re.escape(unit)}(?![A-Za-z])",
            f"{raw_value} {source_label}",
            flags=re.IGNORECASE,
        ):
            return False
    tolerance = max(Decimal("0.000001"), abs(expected) * Decimal("0.000001"))
    return abs(normalized_number - expected) <= tolerance


def _boolean_from_evidence(raw_value: str) -> bool | None:
    token = re.sub(
        r"[\s\W_]+",
        "",
        unicodedata.normalize("NFKC", raw_value).casefold(),
        flags=re.UNICODE,
    )
    if token in {"0", "false", "no"} or any(
        term in token for term in ("否", "不支持", "不适用", "没有", "无")
    ):
        return False
    if token in {"1", "true", "yes"} or any(
        term in token for term in ("是", "支持", "适用", "有")
    ):
        return True
    return None


def _dimension_values(value: dict[str, Any] | None) -> tuple[Decimal, ...] | None:
    if not isinstance(value, dict):
        return None
    output: list[Decimal] = []
    for axis in ("length", "width", "height"):
        leaf = value.get(axis)
        if not isinstance(leaf, dict):
            return None
        try:
            number = Decimal(str(leaf.get("value")))
        except (InvalidOperation, ValueError):
            return None
        if not number.is_finite():
            return None
        output.append(number)
    return tuple(output)


def _parsed_value_matches_evidence(
    field: dict[str, Any],
    value: Any,
    *,
    raw_value: str,
    source_label: str,
) -> bool:
    if field["key"] == "dimensions" and isinstance(value, str):
        unit = str(field.get("unit") or "").strip()
        raw_dimensions = normalize_combined_dimensions(
            source_label,
            f"{raw_value} {unit}".strip(),
        )
        normalized_dimensions = normalize_combined_dimensions(
            field["label_en"],
            f"{value} {unit}".strip(),
        )
        return _dimension_values(raw_dimensions) == _dimension_values(
            normalized_dimensions
        ) and _dimension_values(raw_dimensions) is not None
    if field["value_type"] == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and _number_matches_evidence(
            field,
            value,
            raw_value=raw_value,
            source_label=source_label,
        )
    if field["value_type"] == "boolean":
        return _boolean_from_evidence(raw_value) is value
    return True


def normalize_paste_parse_output(
    provider_output: Any,
    *,
    raw_text: str,
    fields: Any,
) -> dict[str, Any]:
    """Whitelist an AI parse result and recompute all fail-safe diagnostics."""

    normalized_fields = normalize_template_fields(fields)
    field_by_key = {field["key"]: field for field in normalized_fields}
    output = provider_output
    if isinstance(output, dict) and isinstance(output.get("result"), dict):
        output = output["result"]
    if not isinstance(output, dict) or not isinstance(output.get("matched"), dict):
        raise SpecTemplateValidationError(
            "AI paste parser response must contain a matched object"
        )

    matched: dict[str, dict[str, Any]] = {}
    for raw_key, raw_match in output["matched"].items():
        key = str(raw_key or "").strip()
        field = field_by_key.get(key)
        if field is None or not isinstance(raw_match, dict):
            continue
        source_label = str(raw_match.get("source_label") or "").strip()
        raw_value = str(raw_match.get("raw_value") or "").strip()
        if not source_label or not raw_value:
            continue
        source_standard_key = standard_spec_key_for_label(source_label)
        if source_standard_key is not None and (
            field["target"] != "standard" or field["key"] != source_standard_key
        ):
            continue
        if not _is_source_pair(source_label, raw_value, raw_text):
            continue
        value = _normalized_parsed_value(field, raw_match.get("value"))
        if value is None:
            continue
        if not _parsed_value_matches_evidence(
            field,
            value,
            raw_value=raw_value,
            source_label=source_label,
        ):
            continue
        matched[key] = {
            "value": value,
            "raw_value": raw_value[:2000],
            "source_label": source_label[:255],
        }

    missing_required = [
        field["key"]
        for field in normalized_fields
        if field["required"] and field["key"] not in matched
    ]

    unmatched: list[str] = []
    seen_unmatched: set[str] = set()

    def retain_unmatched(value: Any) -> None:
        line = str(value or "").strip()
        if not line or not _is_source_evidence(line, raw_text):
            return
        normalized = _evidence_token(line)
        if normalized in seen_unmatched:
            return
        seen_unmatched.add(normalized)
        unmatched.append(line[:2000])

    raw_unmatched = output.get("unmatched_lines")
    if isinstance(raw_unmatched, list):
        for line in raw_unmatched:
            retain_unmatched(line)

    matched_pairs = [
        (_evidence_token(item["source_label"]), _evidence_token(item["raw_value"]))
        for item in matched.values()
    ]
    for line in raw_text.splitlines():
        compact_line = _evidence_token(line)
        if not compact_line:
            continue
        covered = any(
            source_label in compact_line and raw_value in compact_line
            for source_label, raw_value in matched_pairs
        )
        if not covered:
            retain_unmatched(line)
        if len(unmatched) >= 200:
            break

    return {
        "matched": matched,
        "unmatched_lines": unmatched,
        "missing_required": missing_required,
    }


__all__ = [
    "CATEGORY_SPEC_STATUSES",
    "CATEGORY_SPEC_TARGETS",
    "CATEGORY_SPEC_TREES",
    "CATEGORY_SPEC_VALUE_TYPES",
    "SpecTemplateValidationError",
    "approved_template_for_product",
    "category_leaf",
    "effective_product_category",
    "get_spec_template",
    "missing_required_fields",
    "missing_required_for_product",
    "normalize_category_tree",
    "normalize_paste_parse_output",
    "normalize_template_fields",
    "normalize_template_status",
    "refresh_category_product_completeness",
    "refresh_product_spec_completeness",
]
