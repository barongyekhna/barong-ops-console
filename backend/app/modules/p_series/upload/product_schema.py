"""Project verified K specifications into Woo attributes and Product schema.

Only the source-preserving ``structured_specs_json`` contract is accepted.
The AI-authored ``marketing_copy_json.json_ld`` is never a specification or
rating source.  WooCommerce itself owns ``aggregateRating``/``review`` and
emits those fields only from real, approved product reviews.
"""

from __future__ import annotations

from typing import Any

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
    value = _clean(node.get("value"))
    if not value:
        return None
    unit = _clean(node.get("unit"), limit=40)
    if not unit and isinstance(parent, dict):
        unit = _clean(parent.get("unit"), limit=40)
    return value, unit


def _append(
    attributes: list[ProductAttribute],
    properties: list[ProductSchemaProperty],
    *,
    name: str,
    value: str,
    unit: str | None,
    seen: set[str],
) -> None:
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
            name = _clean(item.get("label"), limit=120)
            value = _clean(item.get("value"))
            raw_value = _clean(item.get("raw_value"))
            if not name or not value or not raw_value:
                continue
            if (
                source_platform == "operator"
                and item.get("evidence") != "operator_fact"
            ):
                continue
            _append(
                attributes,
                properties,
                name=name,
                value=value,
                unit=_clean(item.get("unit"), limit=40),
                seen=seen,
            )

    return attributes, ProductSchema(additional_property=properties)
