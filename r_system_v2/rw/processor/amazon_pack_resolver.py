"""Resolve Amazon pack quantity from Keepa product payloads."""

from __future__ import annotations

import json
import re
from typing import Any


PACK_UNIT_LABELS = {
    "pack": "件",
    "packs": "件",
    "pk": "件",
    "pcs": "件",
    "piece": "件",
    "pieces": "件",
    "count": "件",
    "counts": "件",
    "ct": "件",
    "item": "件",
    "items": "件",
    "pair": "双",
    "pairs": "双",
    "set": "套",
    "sets": "套",
    "件": "件",
    "只": "只",
    "个": "个",
    "片": "片",
    "套": "套",
    "卷": "卷",
    "双": "双",
    "对": "对",
}

HIGH_CONFIDENCE_NUMERIC_FIELDS = (
    "numberOfItems",
    "number_of_items",
    "itemPackageQuantity",
    "item_package_quantity",
    "unitCount",
    "unit_count",
    "itemCount",
    "item_count",
    "totalUnitCount",
    "total_unit_count",
)

LOW_CONFIDENCE_NUMERIC_FIELDS = (
    "packageQuantity",
    "package_quantity",
)

TEXT_FIELDS = (
    "size",
    "style",
    "color",
    "pattern",
    "edition",
    "format",
    "binding",
    "model",
    "partNumber",
    "itemTypeKeyword",
    "parentTitle",
)

ATTRIBUTE_CONTAINERS = (
    "attributes",
    "productAttributes",
    "productDetails",
    "details",
    "technicalDetails",
    "features",
    "description",
    "specialFeatures",
)


def resolve_amazon_pack(product: dict[str, Any], *, asin: str | None = None) -> dict[str, Any]:
    """Return normalized Amazon pack metadata from a Keepa product object."""

    cleaned_asin = str(asin or product.get("asin") or "").strip().upper()
    title = str(product.get("title") or "")
    evidence: list[dict[str, Any]] = []
    variation_attributes = _variation_attributes_for_asin(product, asin=cleaned_asin)

    for key in HIGH_CONFIDENCE_NUMERIC_FIELDS:
        count = _positive_int(product.get(key))
        if count and count > 1:
            return _resolved(
                count=count,
                unit=_infer_unit(_joined_text(title, variation_attributes)),
                source=f"keepa.{key}",
                confidence="high",
                evidence=[
                    _evidence("keepa_product_field", key, product.get(key)),
                    *_variation_evidence(variation_attributes),
                ],
                product=product,
                variation_attributes=variation_attributes,
            )

    for attribute in variation_attributes:
        info = extract_pack_info(
            _joined_text(attribute.get("dimension"), attribute.get("name"), attribute.get("value"))
        )
        if info["count"] and info["count"] > 1:
            return _resolved(
                count=info["count"],
                unit=info["unit"] or _infer_unit(_joined_text(title, variation_attributes)),
                source="keepa.variations.attributes",
                confidence="high",
                evidence=[_evidence("keepa_variation_attribute", "", attribute)],
                product=product,
                variation_attributes=variation_attributes,
            )

    for key in TEXT_FIELDS:
        info = extract_pack_info(product.get(key))
        if info["count"] and info["count"] > 1:
            return _resolved(
                count=info["count"],
                unit=info["unit"] or _infer_unit(_joined_text(title, product.get(key))),
                source=f"keepa.{key}",
                confidence="medium",
                evidence=[_evidence("keepa_product_field", key, product.get(key))],
                product=product,
                variation_attributes=variation_attributes,
            )

    for key in ATTRIBUTE_CONTAINERS:
        for field, value in _flatten_attribute_values(product.get(key), prefix=key):
            info = extract_pack_info(_joined_text(field, value))
            if info["count"] and info["count"] > 1:
                return _resolved(
                    count=info["count"],
                    unit=info["unit"] or _infer_unit(_joined_text(title, field, value)),
                    source=f"keepa.{field}",
                    confidence="medium",
                    evidence=[_evidence("keepa_attribute", field, value)],
                    product=product,
                    variation_attributes=variation_attributes,
                )

    title_info = extract_pack_info(title)
    if title_info["count"] and title_info["count"] > 1:
        return _resolved(
            count=title_info["count"],
            unit=title_info["unit"] or _infer_unit(title),
            source="keepa.title",
            confidence="medium",
            evidence=[_evidence("keepa_product_field", "title", title)],
            product=product,
            variation_attributes=variation_attributes,
        )

    for key in LOW_CONFIDENCE_NUMERIC_FIELDS:
        count = _positive_int(product.get(key))
        if count and count > 1:
            return _resolved(
                count=count,
                unit=_infer_unit(title),
                source=f"keepa.{key}",
                confidence="low",
                evidence=[_evidence("keepa_product_field", key, product.get(key))],
                product=product,
                variation_attributes=variation_attributes,
            )

    searchable_text = _joined_text(
        title,
        variation_attributes,
        *(product.get(key) for key in TEXT_FIELDS),
    )
    requires_alignment = _requires_pack_alignment(searchable_text)
    return {
        "count": None,
        "unit": None,
        "label": "多件装待确认" if requires_alignment else None,
        "source": "keepa.pack_not_found",
        "confidence": "needs_review" if requires_alignment else "none",
        "requires_alignment": requires_alignment,
        "evidence": _variation_evidence(variation_attributes)[:8],
        "variation_attributes": variation_attributes,
        "parent_asin": _string_or_none(product.get("parentAsin")),
        "variation_csv": _string_or_none(product.get("variationCSV")),
    }


def extract_pack_info(value: Any) -> dict[str, Any]:
    source = str(value or "")
    if not source.strip():
        return {"count": None, "unit": None, "label": None}
    patterns = (
        r"(?:number\s+of\s+items|item\s+package\s+quantity|unit\s+count)\s*[:：]?\s*([0-9]{1,3}|[一二两俩三四五六七八九十百]+)\s*(pair|pairs|piece|pieces|pcs|set|sets|pack|packs|pk|count|counts|ct|item|items)?\b",
        r"(?:pack\s*of|set\s*of)\s*([0-9]{1,3}|[一二两俩三四五六七八九十百]+)\s*(pair|pairs|piece|pieces|pcs|set|sets|pack|packs|pk|count|counts|ct|item|items)?\b",
        r"([0-9]{1,3}|[一二两俩三四五六七八九十百]+)\s*[- ]?(pack|packs|pk|pcs|pieces|piece|count|counts|ct|item|items|pair|pairs|set|sets)\b",
        r"([0-9]{1,3}|[一二两俩三四五六七八九十百]+)\s*(件|只|个|片|套|卷|双|对)\s*装",
        r"([0-9]{1,3}|[一二两俩三四五六七八九十百]+)\s*(件|只|个|片|套|卷|双|对)(?!代发|起批|起订|包邮|起售|起购)",
    )
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if not match:
            continue
        count = _parse_count_token(match.group(1))
        if not count or count <= 0:
            continue
        raw_unit = match.group(2) if len(match.groups()) >= 2 else None
        unit = _pack_unit_label(raw_unit) or _infer_unit(source)
        return {"count": count, "unit": unit, "label": f"{count}{unit}装"}
    return {"count": None, "unit": None, "label": None}


def _resolved(
    *,
    count: int,
    unit: str,
    source: str,
    confidence: str,
    evidence: list[dict[str, Any]],
    product: dict[str, Any],
    variation_attributes: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "count": count,
        "unit": unit,
        "label": f"{count}{unit}装" if count > 1 else None,
        "source": source,
        "confidence": confidence,
        "requires_alignment": count > 1,
        "evidence": _dedupe_evidence(evidence)[:12],
        "variation_attributes": variation_attributes,
        "parent_asin": _string_or_none(product.get("parentAsin")),
        "variation_csv": _string_or_none(product.get("variationCSV")),
    }


def _variation_attributes_for_asin(product: dict[str, Any], *, asin: str) -> list[dict[str, str]]:
    variations = product.get("variations")
    if not isinstance(variations, list):
        return []
    matched: list[dict[str, str]] = []
    fallback: list[dict[str, str]] = []
    for variation in variations:
        if not isinstance(variation, dict):
            continue
        variation_asin = str(variation.get("asin") or "").strip().upper()
        attributes = _variation_attribute_list(variation.get("attributes"))
        if variation_asin == asin:
            matched.extend(attributes)
        elif not variation_asin:
            fallback.extend(attributes)
    return matched or fallback


def _variation_attribute_list(value: Any) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                name = str(item.get("dimension") or item.get("name") or "").strip()
                attr_value = str(item.get("value") or "").strip()
                if name or attr_value:
                    output.append({"dimension": name, "value": attr_value})
            elif item is not None:
                output.append({"dimension": "", "value": str(item).strip()})
    elif isinstance(value, dict):
        for key, item in value.items():
            output.append({"dimension": str(key), "value": str(item)})
    return output


def _flatten_attribute_values(value: Any, *, prefix: str) -> list[tuple[str, Any]]:
    output: list[tuple[str, Any]] = []

    def visit(item: Any, path: str) -> None:
        if item is None:
            return
        if isinstance(item, dict):
            for key, nested in item.items():
                visit(nested, f"{path}.{key}" if path else str(key))
            return
        if isinstance(item, list):
            for index, nested in enumerate(item[:24]):
                visit(nested, f"{path}[{index}]")
            return
        if isinstance(item, (str, int, float)) and not isinstance(item, bool):
            output.append((path, item))

    visit(value, prefix)
    return output[:80]


def _variation_evidence(attributes: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [_evidence("keepa_variation_attribute", "", item) for item in attributes]


def _evidence(source: str, field: str, value: Any) -> dict[str, Any]:
    return {
        "source": source,
        "field": field,
        "value": _truncate_value(value),
    }


def _dedupe_evidence(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _truncate_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    return text[:240]


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = int(value)
        return parsed if parsed > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            parsed = int(text)
            return parsed if parsed > 0 else None
    return None


def _parse_count_token(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    parsed = _positive_int(text)
    if parsed is not None:
        return parsed
    normalized = text.replace("俩", "两")
    digits = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if normalized == "十":
        return 10
    if "百" in normalized:
        left, _, right = normalized.partition("百")
        hundreds = digits.get(left, 1 if not left else 0)
        remainder = _parse_count_token(right) if right else 0
        total = hundreds * 100 + (remainder or 0)
        return total if total > 0 else None
    if "十" in normalized:
        left, _, right = normalized.partition("十")
        tens = digits.get(left, 1 if not left else 0)
        ones = digits.get(right, 0) if right else 0
        total = tens * 10 + ones
        return total if total > 0 else None
    if len(normalized) == 1:
        return digits.get(normalized)
    total_text = "".join(str(digits.get(char, "")) for char in normalized)
    if total_text.isdigit():
        return _positive_int(total_text)
    return None


def _pack_unit_label(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    return PACK_UNIT_LABELS.get(normalized, "件")


def _infer_unit(text: Any) -> str:
    lowered = str(text or "").lower()
    if any(term in lowered for term in ("sock", "stocking", "glove", "pair", "pairs", "袜", "手套", "双")):
        return "双"
    if any(term in lowered for term in ("set", "sets", "套")):
        return "套"
    if any(term in lowered for term in ("panel", "panels", "片")):
        return "片"
    if any(term in lowered for term in ("roll", "rolls", "卷")):
        return "卷"
    return "件"


def _requires_pack_alignment(text: Any) -> bool:
    lowered = str(text or "").lower()
    return bool(
        re.search(
            r"(?:multipack|multi\s*pack|[0-9]{1,3}\s*pk\b|pack\s*of|set\s*of|多件装|多只装|多个装|多片装|多双装|多对装|套装|组合装|礼盒装)",
            lowered,
            flags=re.IGNORECASE,
        )
    )


def _joined_text(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            parts.append(json.dumps(value, ensure_ascii=False, default=str))
        else:
            parts.append(str(value))
    return " ".join(parts)


def _string_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
