"""Project verified K specifications into Woo attributes and Product schema.

Only the source-preserving ``structured_specs_json`` contract is accepted.
The AI-authored ``marketing_copy_json.json_ld`` is never a specification or
rating source.  WooCommerce itself owns ``aggregateRating``/``review`` and
emits those fields only from real, approved product reviews.
"""

from __future__ import annotations

from typing import Any

from ...k_series.product_knowledge.buyer_display import (
    buyer_english_text,
    contains_cjk,
    imperial_measurement,
    imperialize_text,
    normalize_package_includes,
)
from ..contract.upload_package import (
    ProductAttribute,
    ProductSchema,
    ProductSchemaProperty,
)

_STANDARD_FIELDS: tuple[tuple[str, str], ...] = (
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

_MAX_PROPERTIES = 100
_IMPERIAL_MARKETS = {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}


def _clean(value: Any, *, limit: int = 500) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        lower = _clean(value.get("min"), limit=limit)
        upper = _clean(value.get("max"), limit=limit)
        if not lower or not upper:
            return None
        rendered = lower if lower == upper else f"{lower}–{upper}"
    elif isinstance(value, list):
        parts = [part for item in value if (part := _clean(item, limit=limit))]
        rendered = ", ".join(parts)
    elif isinstance(value, float):
        rendered = f"{value:g}"
    else:
        rendered = str(value).strip()
    return rendered[:limit] if rendered else None


def _lookup(specs: dict[str, Any], path: str) -> tuple[Any, Any]:
    current: Any = specs
    parent: Any = None
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None, None
        parent = current
        current = current[segment]
    return current, parent


def _evidence_value(
    specs: dict[str, Any], path: str, *, source_platform: str
) -> tuple[str, str | None] | None:
    node, parent = _lookup(specs, path)
    if not isinstance(node, dict):
        return None
    # Supplier fields need the original label/value pair. Manually entered K
    # facts instead carry the explicit operator_fact stamp written by the
    # public payload normalizer. For dimensions that stamp lives on the parent.
    if source_platform == "operator":
        evidence = node.get("evidence") == "operator_fact"
        if not evidence and isinstance(parent, dict):
            evidence = parent.get("evidence") == "operator_fact"
    else:
        evidence = _clean(node.get("raw_value")) and _clean(
            node.get("source_label")
        )
        if not evidence and isinstance(parent, dict):
            evidence = _clean(parent.get("raw_value")) and _clean(
                parent.get("source_label")
            )
    if not evidence:
        return None
    raw_value = node.get("value")
    value = _clean(raw_value)
    if not value:
        return None
    if contains_cjk(value):
        value = buyer_english_text(node.get("value_en"), limit=500)
        raw_value = node.get("value_en")
    if not value:
        return None
    unit = _clean(node.get("unit"), limit=40)
    if not unit and isinstance(parent, dict):
        unit = _clean(parent.get("unit"), limit=40)
    return value, unit


def _buyer_measurement(
    value: Any,
    unit: str | None,
    *,
    target_market: str,
) -> tuple[str, str | None] | None:
    rendered = _clean(value)
    if not rendered or contains_cjk(rendered):
        return None
    rendered_safe = imperialize_text(rendered)
    if not rendered_safe:
        return None
    if target_market.strip().upper() in _IMPERIAL_MARKETS and unit:
        converted = imperial_measurement(value, unit)
        if converted is not None:
            return converted
        # Some supplier/operator projections already include the unit in the
        # value while also carrying a separate unit field.  Prefer the complete
        # converted expression and do not append/convert the duplicate unit.
        if rendered_safe != rendered:
            return rendered_safe, None
        combined = f"{rendered} {unit}"
        combined_safe = imperialize_text(combined)
        if combined_safe is None:
            return None
        if combined_safe != combined:
            return combined_safe, None
    safe = rendered_safe
    # A value such as ``1.4 L`` carries its own converted unit; do not append
    # the old metric unit again in n8n/schema.
    if safe != rendered and unit:
        return safe, None
    clean_unit = buyer_english_text(unit, limit=40) if unit else None
    return safe, clean_unit


def _append(
    attributes: list[ProductAttribute],
    properties: list[ProductSchemaProperty],
    *,
    name: str,
    value: str,
    unit: str | None,
    seen: set[str],
) -> None:
    if contains_cjk(name) or contains_cjk(value) or (unit and contains_cjk(unit)):
        return
    key = name.casefold()
    if key in seen or len(properties) >= _MAX_PROPERTIES:
        return
    seen.add(key)
    attributes.append(ProductAttribute(name=name, value=value, unit=unit))
    properties.append(
        ProductSchemaProperty(name=name, value=value, unit_text=unit)
    )


def project_verified_product_specs(
    structured_specs_json: Any,
    *,
    package_includes: Any = None,
    target_market: str = "US",
) -> tuple[list[ProductAttribute], ProductSchema]:
    """Return two views of the same verified facts, or two empty views.

    Requiring the v1 contract plus a supported evidence source prevents legacy
    or model-authored dictionaries from silently becoming product claims.
    """
    empty = ([], ProductSchema())
    if not isinstance(structured_specs_json, dict):
        return empty
    if str(structured_specs_json.get("schema_version") or "") != "1.0":
        return empty
    source = structured_specs_json.get("source")
    if not isinstance(source, dict):
        return empty
    source_platform = str(source.get("platform") or "")
    if source_platform not in {"1688", "operator"}:
        return empty
    if (
        source_platform == "operator"
        and source.get("evidence_type") != "operator_fact"
    ):
        return empty

    attributes: list[ProductAttribute] = []
    properties: list[ProductSchemaProperty] = []
    seen: set[str] = set()
    for path, name in _STANDARD_FIELDS:
        resolved = _evidence_value(
            structured_specs_json,
            path,
            source_platform=source_platform,
        )
        if resolved is None:
            continue
        value, unit = resolved
        buyer_value = _buyer_measurement(
            value,
            unit,
            target_market=target_market,
        )
        if buyer_value is None:
            continue
        value, unit = buyer_value
        _append(
            attributes,
            properties,
            name=name,
            value=value,
            unit=unit,
            seen=seen,
        )

    additional = structured_specs_json.get("additional_specs")
    if isinstance(additional, list):
        for item in additional:
            if not isinstance(item, dict):
                continue
            # Raw supplier/operator labels are audit evidence, never public
            # copy.  Only the one-time, persisted English projection may leave K.
            name = buyer_english_text(item.get("label_en"), limit=120)
            value = buyer_english_text(item.get("value_en"), limit=500)
            raw_value = _clean(item.get("raw_value"))
            if not name or not value or not raw_value:
                continue
            if (
                source_platform == "operator"
                and item.get("evidence") != "operator_fact"
            ):
                continue
            buyer_value = _buyer_measurement(
                value,
                _clean(item.get("unit"), limit=40),
                target_market=target_market,
            )
            if buyer_value is None:
                continue
            value, unit = buyer_value
            _append(
                attributes,
                properties,
                name=name,
                value=value,
                unit=unit,
                seen=seen,
            )

    package_items = [
        safe
        for item in normalize_package_includes(package_includes, reject_cjk=False)
        if (safe := imperialize_text(item))
    ]
    if package_items:
        _append(
            attributes,
            properties,
            name="What's included",
            value=", ".join(package_items),
            unit=None,
            seen=seen,
        )

    return attributes, ProductSchema(additional_property=properties)
