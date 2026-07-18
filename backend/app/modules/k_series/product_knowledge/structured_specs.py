"""Verified, source-preserving product specification normalization.

``structured_specs_json`` is a cross-module contract.  F-series builds it from
real 1688 attribute/detail evidence, K-series supplies it to copy/image jobs,
and P-series may later map it to store attributes and Product JSON-LD.

The normalizer is deliberately deterministic: a missing or unparseable value
is omitted, never guessed.  Every normalized field retains the supplier's
original label and value so downstream consumers can audit what was claimed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from .buyer_display import (
    buyer_english_text,
    contains_cjk,
    normalize_package_includes,
)


STRUCTURED_SPECS_SCHEMA_VERSION = "1.0"

STANDARD_SPEC_KEYS = frozenset(
    {
        "lumens",
        "color_temperature_k",
        "battery_type",
        "battery_capacity_mah",
        "charge_time_h",
        "runtime_h",
        "ip_rating",
        "dimensions",
        "weight",
        "material",
        "mount_type",
        "certifications",
    }
)

_ATTRIBUTE_CONTAINER_KEYS = frozenset(
    {
        "structured_attributes",
        "attributes",
        "attribute_list",
        "attributelist",
        "product_attributes",
        "productattributes",
        "product_attribute_list",
        "productattributelist",
        "product_attribute",
        "productattribute",
        "product_feature_list",
        "productfeaturelist",
        "feature_list",
        "featurelist",
        "properties",
        "property_list",
        "propertylist",
        "props",
        "product_props",
        "productprops",
    }
)

_LABEL_KEYS = (
    "attribute_name",
    "attributename",
    "attr_name",
    "attrname",
    "property_name",
    "propertyname",
    "prop_name",
    "propname",
    "feature_name",
    "featurename",
    "label",
    "name",
    "key",
)
_VALUE_KEYS = (
    "attribute_value",
    "attributevalue",
    "attr_value",
    "attrvalue",
    "property_value",
    "propertyvalue",
    "prop_value",
    "propvalue",
    "feature_value",
    "featurevalue",
    "value_name",
    "valuename",
    "value_names",
    "valuenames",
    "values",
    "value",
)

_LABEL_EN_KEYS = (
    "label_en",
    "name_en",
    "attribute_name_en",
    "property_name_en",
    "source_label_en",
)
_VALUE_EN_KEYS = (
    "value_en",
    "attribute_value_en",
    "property_value_en",
    "raw_value_en",
)

_PACKAGE_LABEL_TERMS = (
    "包装清单",
    "装箱清单",
    "配件清单",
    "套装清单",
    "包装内容",
    "清单",
    "packageincludes",
    "packagelist",
    "packinglist",
    "whatsincluded",
    "includeditems",
    "boxcontents",
)

_EMPTY_VALUE_MARKERS = frozenset(
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

_IDENTITY_LABEL_TERMS = (
    "品牌",
    "brand",
    "manufacturer",
    "生产厂家",
    "制造商",
    "厂名",
    "供应商",
    "seller",
)

_CERTIFICATION_PATTERN = re.compile(
    r"(?<![A-Z0-9])(?:CE|FCC|ROHS|UL|ETL|PSE|CCC|CSA|TUV|GS|SAA|UKCA|"
    r"REACH|EMC|LVD|CB|BSCI|ISO\s*\d{4,5})(?![A-Z0-9])",
    flags=re.IGNORECASE,
)


def normalize_1688_structured_specs(
    payload: Any,
    *,
    source_url: str | None = None,
    weight_note: str | None = None,
) -> dict[str, Any] | None:
    """Return the v1 verified-spec contract extracted from a 1688 payload.

    The function accepts the compact payload attached to ``SupplierApiOffer``
    as well as common 1688 product-attribute shapes.  It never invokes AI and
    never fills a field merely because a category would usually have it.
    """

    source_payload = payload if isinstance(payload, dict) else {}
    output: dict[str, Any] = {
        "schema_version": STRUCTURED_SPECS_SCHEMA_VERSION,
        "source": _source_record(source_payload, source_url=source_url),
    }
    additional: list[dict[str, Any]] = []
    additional_seen: set[tuple[str, str]] = set()
    additional_keys: dict[str, str] = {}
    inline_translations = _collect_inline_translations(source_payload)

    def retain_additional(item: dict[str, Any]) -> None:
        dedupe_key = (item["label"].casefold(), item["raw_value"].casefold())
        if dedupe_key in additional_seen:
            return
        normalized_key = str(item["key"]).casefold()
        existing_label = additional_keys.get(normalized_key)
        if existing_label is not None:
            raise ValueError(
                "Supplier additional specification key collision for "
                f"'{item['key']}': '{existing_label}' and '{item['label']}'"
            )
        additional_seen.add(dedupe_key)
        additional_keys[normalized_key] = item["label"]
        additional.append(item)

    source_pairs = _dedupe_pairs(
        [
            *_collect_attribute_pairs(source_payload),
            *_collect_package_pairs(source_payload),
        ]
    )
    for label, raw_value in source_pairs:
        value_text = _value_text(raw_value)
        if not _usable_value(value_text):
            continue
        if any(term in _label_token(label) for term in _IDENTITY_LABEL_TERMS):
            # Identity fields are not product specifications and must never
            # smuggle a supplier/third-party brand into K generation prompts.
            continue
        translation = inline_translations.get(
            (label.casefold(), value_text.casefold()),
            {},
        )
        if _is_package_includes_label(label):
            source_record: dict[str, Any] = {
                "raw_value": value_text[:4000],
                "source_label": label[:255],
            }
            translated_value = buyer_english_text(translation.get("value_en"))
            if translated_value:
                source_record["value_en"] = translated_value[:4000]
            output["package_includes_source"] = source_record
            public_source: Any = translated_value
            if public_source is None and not contains_cjk(value_text):
                public_source = value_text
            package_includes = normalize_package_includes(
                public_source,
                reject_cjk=False,
            )
            if package_includes:
                output["package_includes"] = package_includes
            continue
        spec_key = _standard_key(label)
        if spec_key is None:
            item = _additional_spec(
                label,
                value_text,
                label_en=translation.get("label_en"),
                value_en=translation.get("value_en"),
            )
            retain_additional(item)
            continue
        parsed = _standard_spec(spec_key, label=label, raw_value=value_text)
        if parsed is None:
            # The supplier supplied something, but it was not strong enough to
            # support the standard claim (for example "waterproof" without an
            # IP code).  Preserve the evidence only as an unmapped attribute.
            item = _additional_spec(
                label,
                value_text,
                label_en=translation.get("label_en"),
                value_en=translation.get("value_en"),
            )
            retain_additional(item)
            continue
        translated_value = buyer_english_text(translation.get("value_en"))
        if translated_value:
            parsed["value_en"] = translated_value[:1000]
        _merge_standard_spec(output, spec_key, parsed)

    _merge_detail_measurements(output, source_payload)
    if weight_note and "weight" not in output:
        weight = _weight_spec("供应商报重", weight_note)
        if weight is not None:
            output["weight"] = weight

    if additional:
        output["additional_specs"] = additional[:100]

    if (
        not any(key in output for key in STANDARD_SPEC_KEYS)
        and not additional
        and "package_includes_source" not in output
    ):
        return None
    return output


def has_standard_specs(value: Any) -> bool:
    """Whether a stored contract contains at least one normalized standard key."""

    return isinstance(value, dict) and any(key in value for key in STANDARD_SPEC_KEYS)


def package_includes_from_structured_specs(value: Any) -> list[str]:
    """Read only a completed English package list from the specs contract."""

    if not isinstance(value, dict):
        return []
    return normalize_package_includes(
        value.get("package_includes"),
        reject_cjk=False,
    )


def _translation_request_id(path: str, source: Any) -> str:
    raw = json.dumps(
        {"path": path, "source": source},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return "buyer-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _customer_translation_requests(
    structured_specs: Any,
) -> list[dict[str, Any]]:
    if not isinstance(structured_specs, dict):
        return []
    requests: list[dict[str, Any]] = []
    for key in sorted(STANDARD_SPEC_KEYS):
        node = structured_specs.get(key)
        if not isinstance(node, dict):
            continue
        source_value = node.get("value")
        if not contains_cjk(source_value) or buyer_english_text(node.get("value_en")):
            continue
        path = key
        requests.append(
            {
                "request_id": _translation_request_id(path, source_value),
                "path": path,
                "kind": "standard_value",
                "source_label": node.get("source_label") or key,
                "source_value": source_value,
                "required_output": ["value_en"],
            }
        )

    additional = structured_specs.get("additional_specs")
    if isinstance(additional, list):
        for index, item in enumerate(additional):
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or f"row_{index + 1}").strip()
            needs: list[str] = []
            if not buyer_english_text(item.get("label_en")):
                needs.append("label_en")
            if not buyer_english_text(item.get("value_en")):
                needs.append("value_en")
            if not needs:
                continue
            source = {
                "label": item.get("label") or item.get("source_label"),
                "value": item.get("raw_value") or item.get("value"),
            }
            path = f"additional_specs.{key}"
            requests.append(
                {
                    "request_id": _translation_request_id(path, source),
                    "path": path,
                    "kind": "additional_spec",
                    "source_label": source["label"],
                    "source_value": source["value"],
                    "required_output": needs,
                }
            )

    package_source = structured_specs.get("package_includes_source")
    if (
        isinstance(package_source, dict)
        and not package_includes_from_structured_specs(structured_specs)
    ):
        source_value = package_source.get("raw_value")
        if source_value not in (None, "", [], {}):
            path = "package_includes"
            requests.append(
                {
                    "request_id": _translation_request_id(path, source_value),
                    "path": path,
                    "kind": "package_includes",
                    "source_label": package_source.get("source_label"),
                    "source_value": source_value,
                    "required_output": ["package_includes"],
                    "instruction": "Return one English component per list item.",
                }
            )
    return requests


def _translation_request_digest(requests: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(
            requests,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def pending_customer_translation_requests(
    structured_specs: Any,
) -> list[dict[str, Any]]:
    """List stable, evidence-bound fields that still need English translation.

    A failed attempt for the same exact source digest is not returned again;
    changing the supplier/operator fact creates a new request digest and makes
    it eligible for one fresh attempt.
    """

    requests = _customer_translation_requests(structured_specs)
    if not requests or not isinstance(structured_specs, dict):
        return requests
    attempt = structured_specs.get("buyer_translation")
    if isinstance(attempt, dict) and attempt.get("attempted") is True:
        attempted_ids = {
            str(item)
            for key in ("completed_request_ids", "failed_request_ids")
            for item in (attempt.get(key) or [])
        }
        requests = [
            request
            for request in requests
            if request["request_id"] not in attempted_ids
        ]
    return requests


def apply_customer_translations(
    structured_specs: Any,
    provider_output: Any,
) -> tuple[dict[str, Any] | None, list[str] | None]:
    """Safely persist one provider translation pass.

    Only request IDs generated from the current facts are accepted.  Any CJK
    or missing required result fails that row closed.  Valid rows are retained,
    while the root attempt marker prevents an unchanged failed payload from
    causing repeated provider calls.
    """

    if not isinstance(structured_specs, dict):
        return None, None
    output = copy.deepcopy(structured_specs)
    requests = _customer_translation_requests(output)
    digest = _translation_request_digest(requests)
    raw_translations = (
        provider_output.get("customer_translations")
        if isinstance(provider_output, dict)
        else None
    )
    if not isinstance(raw_translations, list) and isinstance(provider_output, dict):
        raw_translations = provider_output.get("translations")
    rows = raw_translations if isinstance(raw_translations, list) else []
    by_id = {
        str(item.get("request_id") or "").strip(): item
        for item in rows
        if isinstance(item, dict) and str(item.get("request_id") or "").strip()
    }
    completed: list[str] = []
    failed: list[str] = []
    package_includes = package_includes_from_structured_specs(output)

    for request in requests:
        request_id = request["request_id"]
        row = by_id.get(request_id, {})
        kind = request["kind"]
        if kind == "package_includes":
            candidate = row.get("package_includes") if isinstance(row, dict) else None
            if candidate is None and isinstance(provider_output, dict):
                candidate = provider_output.get("package_includes")
            try:
                translated_package = normalize_package_includes(candidate)
            except ValueError:
                translated_package = []
            if not translated_package:
                failed.append(request_id)
                continue
            output["package_includes"] = translated_package
            package_includes = translated_package
            completed.append(request_id)
            continue

        label_en = buyer_english_text(row.get("label_en"), limit=255)
        value_en = buyer_english_text(row.get("value_en"), limit=1000)
        required = set(request.get("required_output") or [])
        if ("label_en" in required and not label_en) or (
            "value_en" in required and not value_en
        ):
            failed.append(request_id)
            continue
        if kind == "standard_value":
            node = output.get(request["path"])
            if not isinstance(node, dict) or not value_en:
                failed.append(request_id)
                continue
            node["value_en"] = value_en
        else:
            stable_key = request["path"].split(".", 1)[1]
            matched = False
            for item in output.get("additional_specs") or []:
                if not isinstance(item, dict) or str(item.get("key") or "") != stable_key:
                    continue
                if label_en:
                    item["label_en"] = label_en
                if value_en:
                    item["value_en"] = value_en
                matched = True
                break
            if not matched:
                failed.append(request_id)
                continue
        completed.append(request_id)

    status = "succeeded" if not failed else "failed"
    if not requests:
        status = "not_required"
    output["buyer_translation"] = {
        "attempted": bool(requests),
        "status": status,
        "request_digest": digest,
        "completed_request_ids": completed,
        "failed_request_ids": failed,
    }
    return output, (package_includes or None)


def normalize_operator_structured_specs(payload: Any) -> dict[str, Any] | None:
    """Validate the public K manual-spec contract without inventing values.

    Manual K entry is deliberately a separate evidence source from the 1688
    normalizer.  Operators may submit standard fields in the existing v1 shape
    or extensible ``additional_specs`` rows.  Blank rows are omitted and every
    retained row is stamped as an ``operator_fact`` so selling-point evidence
    can refer to it explicitly.
    """

    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("structured_specs_json must be an object")

    source = payload.get("source")
    if not isinstance(source, dict) or str(source.get("platform") or "") != "operator":
        raise ValueError(
            "Manual structured_specs_json must use source.platform=operator"
        )

    output: dict[str, Any] = {
        "schema_version": STRUCTURED_SPECS_SCHEMA_VERSION,
        "source": {
            "platform": "operator",
            "evidence_type": "operator_fact",
        },
    }
    if source.get("note"):
        output["source"]["note"] = _clean_text(source.get("note"))[:1000]

    for key in STANDARD_SPEC_KEYS:
        raw = payload.get(key)
        if raw in (None, "", [], {}):
            continue
        if not isinstance(raw, dict):
            raise ValueError(f"Manual standard spec '{key}' must be an object")
        if key == "dimensions":
            dimensions = dict(raw)
            has_dimension_leaf = any(
                isinstance(raw.get(axis), dict)
                for axis in ("length", "width", "height")
            )
            # Round 9 templates describe one stable root key.  Accept the
            # operator-confirmed ``L x W x H`` evidence at that boundary, but
            # immediately project it back into the established v1 axis shape
            # so downstream consumers never receive a new dimensions schema.
            if not has_dimension_leaf:
                root_raw_value = _clean_text(raw.get("raw_value"))
                root_normalized_value = _clean_text(raw.get("value"))
                root_source_label = _clean_text(raw.get("source_label"))
                root_unit = _clean_text(raw.get("unit"))
                parse_value = root_normalized_value or root_raw_value
                if parse_value and root_unit:
                    parse_value = f"{parse_value} {root_unit}"
                if parse_value:
                    parsed_dimensions = normalize_combined_dimensions(
                        " ".join(
                            part
                            for part in (root_source_label, root_unit)
                            if part
                        ),
                        parse_value,
                    )
                    if parsed_dimensions is None:
                        raise ValueError(
                            "Manual dimensions must be L x W x H with an explicit unit"
                        )
                    evidence_value = root_raw_value or parse_value
                    for axis in ("length", "width", "height"):
                        leaf = parsed_dimensions.get(axis)
                        if isinstance(leaf, dict):
                            leaf["raw_value"] = evidence_value[:1000]
                            if root_source_label:
                                leaf["source_label"] = root_source_label[:255]
                    parsed_dimensions["raw_value"] = evidence_value[:1000]
                    if root_source_label:
                        parsed_dimensions["source_label"] = root_source_label[:255]
                    dimensions = parsed_dimensions
            retained_dimension = False
            for axis in ("length", "width", "height"):
                leaf = dimensions.get(axis)
                if not isinstance(leaf, dict):
                    continue
                leaf_value = leaf.get("value")
                leaf_raw_value = _clean_text(leaf.get("raw_value"))
                if leaf_value in (None, "", [], {}) and not leaf_raw_value:
                    dimensions.pop(axis, None)
                    continue
                normalized_leaf = dict(leaf)
                if leaf_raw_value:
                    normalized_leaf["raw_value"] = leaf_raw_value[:1000]
                normalized_leaf["evidence"] = "operator_fact"
                dimensions[axis] = normalized_leaf
                retained_dimension = True
            if not retained_dimension:
                continue
            dimensions["evidence"] = "operator_fact"
            output[key] = dimensions
            continue
        # Keep the established source-preserving shape.  A manual standard
        # value without a value/raw_value is not evidence and is discarded.
        value = raw.get("value")
        raw_value = _clean_text(raw.get("raw_value"))
        if value in (None, "", [], {}) and not raw_value:
            continue
        item = dict(raw)
        if raw_value:
            item["raw_value"] = raw_value[:1000]
        item["evidence"] = "operator_fact"
        output[key] = item

    additional: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    seen_keys: set[str] = set()
    raw_additional = payload.get("additional_specs")
    if raw_additional is not None and not isinstance(raw_additional, list):
        raise ValueError("additional_specs must be a list")
    for index, raw in enumerate(raw_additional or [], start=1):
        if not isinstance(raw, dict):
            raise ValueError("Every manual specification must be an object")
        source_label = _clean_text(raw.get("source_label"))
        label = _clean_text(raw.get("label") or source_label)
        raw_value = _clean_text(raw.get("raw_value"))
        submitted_value = raw.get("value")
        value_text = _clean_text(submitted_value)
        evidence_value = raw_value or value_text
        if not label and not evidence_value:
            continue
        if not label or not evidence_value:
            raise ValueError("Manual specification label and value are both required")
        if any(
            term in _label_token(candidate)
            for candidate in (label, source_label)
            for term in _IDENTITY_LABEL_TERMS
            if candidate
        ):
            raise ValueError("Brand/manufacturer identity is not a product specification")
        dedupe_key = (label.casefold(), evidence_value.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        stable_key = _clean_text(raw.get("key")) or (
            "operator_attribute_"
            + hashlib.sha1(f"{label}:{index}".encode("utf-8")).hexdigest()[:10]
        )
        stable_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", stable_key).strip("_.-")
        if not stable_key:
            raise ValueError("Manual specification key must contain letters or numbers")
        stable_key = stable_key[:128]
        normalized_key = stable_key.casefold()
        if normalized_key in seen_keys:
            raise ValueError(f"Manual specification key must be unique: {stable_key}")
        seen_keys.add(normalized_key)
        if isinstance(submitted_value, str):
            canonical_value: Any = (
                submitted_value.strip()[:1000] or evidence_value[:1000]
            )
        elif isinstance(submitted_value, (bool, int, float)):
            # Paste parsing returns typed normalized values.  Keep them typed;
            # the separate raw_value remains the verbatim operator evidence.
            canonical_value = submitted_value
        else:
            canonical_value = evidence_value[:1000]
        item: dict[str, Any] = {
            "key": stable_key,
            "label": label[:255],
            # Paste parsing retains the supplier's original Chinese label even
            # when the reviewed template supplies a different operator label.
            "source_label": (source_label or label)[:255],
            "value": canonical_value,
            "raw_value": evidence_value[:1000],
            "evidence": "operator_fact",
        }
        label_en = buyer_english_text(raw.get("label_en"), limit=255)
        if label_en is None:
            label_en = buyer_english_text(label, limit=255)
        value_en = buyer_english_text(raw.get("value_en"), limit=1000)
        if value_en is None and raw.get("raw_value") is not None:
            # parse-paste sends its translated/normalized projection as
            # ``value`` and the verbatim evidence as ``raw_value``.
            value_en = buyer_english_text(raw.get("value"), limit=1000)
        if value_en is None:
            value_en = buyer_english_text(canonical_value, limit=1000)
        if value_en is None and isinstance(canonical_value, bool):
            value_en = "Yes" if canonical_value else "No"
        elif value_en is None and isinstance(canonical_value, (int, float)):
            value_en = str(canonical_value)[:1000]
        if label_en:
            item["label_en"] = label_en
        if value_en:
            item["value_en"] = value_en
        unit = _clean_text(raw.get("unit"))
        if unit and not contains_cjk(unit):
            item["unit"] = unit[:50]
        additional.append(item)
    if additional:
        output["additional_specs"] = additional[:100]

    if not any(key in output for key in STANDARD_SPEC_KEYS) and not additional:
        return None
    return output


def _source_record(payload: dict[str, Any], *, source_url: str | None) -> dict[str, Any]:
    record: dict[str, Any] = {"platform": "1688"}
    offer_id = _clean_text(payload.get("offer_id") or payload.get("offerId"))
    if offer_id:
        record["offer_id"] = offer_id[:128]
    url = _clean_text(source_url or payload.get("detail_url") or payload.get("detailUrl"))
    if url:
        record["url"] = url[:2048]
    return record


def _collect_inline_translations(
    payload: dict[str, Any],
) -> dict[tuple[str, str], dict[str, str]]:
    """Collect already-authored English fields without treating them as proof.

    F/provider payloads differ in casing and nesting, so this scans the same
    bounded object graph as attribute extraction.  Only non-CJK English text
    is retained; source labels/values remain the evidence of record.
    """

    output: dict[tuple[str, str], dict[str, str]] = {}

    def visit(value: Any, *, depth: int) -> None:
        if depth > 6:
            return
        if isinstance(value, list):
            for item in value:
                visit(item, depth=depth + 1)
            return
        if not isinstance(value, dict):
            return
        normalized = {_normalized_key(key): nested for key, nested in value.items()}
        label = next(
            (
                _clean_text(normalized.get(key))
                for key in _LABEL_KEYS
                if normalized.get(key) is not None
            ),
            None,
        )
        raw_value = next(
            (normalized.get(key) for key in _VALUE_KEYS if normalized.get(key) is not None),
            None,
        )
        value_text = _value_text(raw_value)
        if label and value_text:
            translation: dict[str, str] = {}
            label_en = next(
                (
                    buyer_english_text(normalized.get(key), limit=255)
                    for key in _LABEL_EN_KEYS
                    if normalized.get(key) is not None
                ),
                None,
            )
            value_en = next(
                (
                    buyer_english_text(normalized.get(key), limit=1000)
                    for key in _VALUE_EN_KEYS
                    if normalized.get(key) is not None
                ),
                None,
            )
            if label_en:
                translation["label_en"] = label_en
            if value_en:
                translation["value_en"] = value_en
            if translation:
                output[(label.casefold(), value_text.casefold())] = translation
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                visit(nested, depth=depth + 1)

    visit(payload, depth=0)
    return output


def _is_package_includes_label(label: str) -> bool:
    token = _label_token(label)
    return any(term in token for term in _PACKAGE_LABEL_TERMS)


def _collect_attribute_pairs(payload: dict[str, Any]) -> list[tuple[str, Any]]:
    containers: list[Any] = []

    def visit(value: Any, *, depth: int) -> None:
        if depth > 5:
            return
        if isinstance(value, dict):
            for raw_key, nested in value.items():
                key = _normalized_key(raw_key)
                if key in _ATTRIBUTE_CONTAINER_KEYS:
                    containers.append(nested)
                elif isinstance(nested, (dict, list)):
                    visit(nested, depth=depth + 1)
        elif isinstance(value, list):
            for nested in value:
                if isinstance(nested, (dict, list)):
                    visit(nested, depth=depth + 1)

    visit(payload, depth=0)
    pairs: list[tuple[str, Any]] = []
    for container in containers:
        pairs.extend(_pairs_from_container(container))
    return _dedupe_pairs(pairs)


def _collect_package_pairs(payload: dict[str, Any]) -> list[tuple[str, Any]]:
    """Find real package-list fields in attributes or detail crawler payloads."""

    pairs: list[tuple[str, Any]] = []

    def visit(value: Any, *, depth: int) -> None:
        if depth > 7:
            return
        if isinstance(value, list):
            for nested in value:
                if isinstance(nested, (dict, list)):
                    visit(nested, depth=depth + 1)
            return
        if not isinstance(value, dict):
            return
        for raw_key, nested in value.items():
            if _is_package_includes_label(str(raw_key)) and not isinstance(nested, dict):
                rendered = _value_text(nested)
                if rendered:
                    pairs.append((str(raw_key), rendered))
            if isinstance(nested, (dict, list)):
                visit(nested, depth=depth + 1)

    visit(payload, depth=0)
    return _dedupe_pairs(pairs)


def _pairs_from_container(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, list):
        pairs: list[tuple[str, Any]] = []
        for item in value:
            pairs.extend(_pairs_from_container(item))
        return pairs
    if not isinstance(value, dict):
        return []

    normalized = {_normalized_key(key): nested for key, nested in value.items()}
    label = next(
        (
            _clean_text(normalized.get(key))
            for key in _LABEL_KEYS
            if normalized.get(key) is not None
        ),
        None,
    )
    raw_value = next(
        (normalized.get(key) for key in _VALUE_KEYS if normalized.get(key) is not None),
        None,
    )
    if label and raw_value is not None:
        return [(label[:255], raw_value)]

    # Some APIs return a direct {"材质": "ABS", "防护等级": "IP65"}
    # mapping.  This branch is only reached inside a known attribute container.
    pairs = []
    metadata_keys = set(_LABEL_KEYS) | set(_VALUE_KEYS) | {
        "id",
        "attribute_id",
        "attributeid",
        "property_id",
        "propertyid",
    }
    for raw_key, nested in value.items():
        if _normalized_key(raw_key) in metadata_keys:
            continue
        if isinstance(nested, (str, int, float, Decimal, bool)):
            pairs.append((str(raw_key), nested))
        elif isinstance(nested, list):
            text = _value_text(nested)
            if text:
                pairs.append((str(raw_key), text))
    return pairs


def _dedupe_pairs(pairs: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    output: list[tuple[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for label, value in pairs:
        cleaned_label = _clean_text(label)
        cleaned_value = _value_text(value)
        if not cleaned_label or not cleaned_value:
            continue
        key = (cleaned_label.casefold(), cleaned_value.casefold())
        if key in seen:
            continue
        seen.add(key)
        output.append((cleaned_label[:255], cleaned_value[:1000]))
    return output


def _standard_key(label: str) -> str | None:
    key = _label_token(label)
    if any(term in key for term in ("光通量", "流明", "luminousflux", "lumens", "lumen")):
        return "lumens"
    if any(term in key for term in ("色温", "colortemperature", "colourtemperature")):
        return "color_temperature_k"
    if any(term in key for term in ("电池容量", "电芯容量", "batterycapacity")):
        return "battery_capacity_mah"
    if any(term in key for term in ("电池类型", "电芯类型", "电池种类", "batterytype", "batterychemistry")):
        return "battery_type"
    if any(term in key for term in ("充电时间", "充满时间", "chargetime", "chargingtime")):
        return "charge_time_h"
    if any(
        term in key
        for term in (
            "续航时间",
            "续航时长",
            "工作时间",
            "照明时间",
            "放电时间",
            "runtime",
            "workingtime",
            "operatingtime",
            "lightingtime",
        )
    ):
        return "runtime_h"
    if any(term in key for term in ("防护等级", "防水等级", "ip等级", "iprating", "ingressprotection")):
        return "ip_rating"
    if key in {"长", "长度", "length", "productlength", "产品长度"}:
        return "dimensions.length"
    if key in {"宽", "宽度", "width", "productwidth", "产品宽度"}:
        return "dimensions.width"
    if key in {"高", "高度", "height", "productheight", "产品高度"}:
        return "dimensions.height"
    if any(
        term in key
        for term in (
            "产品尺寸",
            "外形尺寸",
            "商品尺寸",
            "规格尺寸",
            "dimensions",
            "productsize",
            "itemsize",
        )
    ) or key == "尺寸":
        return "dimensions"
    if any(
        term in key
        for term in ("产品重量", "商品重量", "净重", "单重", "weight", "itemweight")
    ) or key == "重量":
        return "weight"
    if any(term in key for term in ("主体材质", "外壳材质", "产品材质", "material")) or key == "材质":
        return "material"
    if any(
        term in key
        for term in (
            "安装方式",
            "安装类型",
            "固定方式",
            "底座类型",
            "mounttype",
            "mountingtype",
            "installationmethod",
        )
    ):
        return "mount_type"
    if any(term in key for term in ("认证", "资质", "certification", "certifications", "compliance")):
        return "certifications"
    return None


def standard_spec_key_for_label(label: str) -> str | None:
    """Classify a human label into the public canonical root key, if any."""

    key = _standard_key(label)
    if key and key.startswith("dimensions."):
        return "dimensions"
    return key


def _standard_spec(spec_key: str, *, label: str, raw_value: str) -> dict[str, Any] | None:
    if spec_key == "lumens":
        return _measurement_spec(label, raw_value, canonical_unit="lm", aliases=("lm", "流明"))
    if spec_key == "color_temperature_k":
        return _measurement_spec(label, raw_value, canonical_unit="K", aliases=("k", "开尔文"))
    if spec_key == "battery_capacity_mah":
        return _measurement_spec(
            label,
            raw_value,
            canonical_unit="mAh",
            aliases=("mah", "毫安时", "毫安小时"),
        )
    if spec_key in {"charge_time_h", "runtime_h"}:
        return _time_spec(label, raw_value)
    if spec_key == "ip_rating":
        match = re.search(
            r"\bIP\s*([0-6X][0-9X][A-Z]?)\b",
            raw_value,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return _evidence(
            value=f"IP{match.group(1).upper()}",
            raw_value=raw_value,
            source_label=label,
        )
    if spec_key == "dimensions":
        return _combined_dimensions_spec(label, raw_value)
    if spec_key.startswith("dimensions."):
        axis = spec_key.split(".", 1)[1]
        leaf = _dimension_leaf(label, raw_value)
        return {axis: leaf, "raw_value": raw_value, "source_label": label} if leaf else None
    if spec_key == "weight":
        return _weight_spec(label, raw_value)
    if spec_key in {"battery_type", "material", "mount_type"}:
        return _evidence(value=raw_value, raw_value=raw_value, source_label=label)
    if spec_key == "certifications":
        values = []
        seen: set[str] = set()
        for match in _CERTIFICATION_PATTERN.finditer(raw_value.upper()):
            certification = re.sub(r"\s+", " ", match.group(0).upper()).strip()
            if certification == "ROHS":
                certification = "RoHS"
            if certification not in seen:
                seen.add(certification)
                values.append(certification)
        if not values:
            return None
        return _evidence(value=values, raw_value=raw_value, source_label=label)
    return None


def _measurement_spec(
    label: str,
    raw_value: str,
    *,
    canonical_unit: str,
    aliases: tuple[str, ...],
) -> dict[str, Any] | None:
    unit_pattern = "|".join(re.escape(alias) for alias in aliases)
    measurement_pattern = re.compile(
        r"([0-9]+(?:\.[0-9]+)?)"
        r"(?:\s*(?:-|~|～|至|到)\s*([0-9]+(?:\.[0-9]+)?))?"
        rf"\s*(?:{unit_pattern})",
        flags=re.IGNORECASE,
    )
    normalized_raw = raw_value.replace(",", "")
    matches = list(measurement_pattern.finditer(normalized_raw))
    values: list[Decimal] = []
    for match in matches:
        for raw_number in match.groups():
            parsed = _decimal(raw_number)
            if parsed is not None:
                values.append(parsed)
    label_unit_fallback = False
    if not values and re.search(unit_pattern, label, flags=re.IGNORECASE):
        # When the unit exists only in the label, accept an entirely bare
        # scalar or an explicit two-endpoint range.  Do not reinterpret option
        # lists such as ``3色 3000/4500/6000`` as a numeric range.
        values = _label_unit_measurement_values(raw_value)
        label_unit_fallback = bool(values)
    if not values:
        return None
    if not label_unit_fallback:
        # Every number in the raw value must belong to an explicitly unit-bound
        # measurement.  This rejects partial matches such as
        # ``3色 3000/4500/6000K`` instead of publishing only 6000 K.
        if len(_all_numbers(normalized_raw)) != len(values) or len(values) > 10:
            return None
        has_explicit_range = any(match.group(2) is not None for match in matches)
        if has_explicit_range and len(matches) != 1:
            return None
        if len(values) > 1 and not has_explicit_range:
            value: Any = [_json_number(item) for item in values]
        else:
            value = _range_or_value(values)
    else:
        value = _range_or_value(values)
    return _evidence(
        value=value,
        unit=canonical_unit,
        raw_value=raw_value,
        source_label=label,
    )


def _time_spec(label: str, raw_value: str) -> dict[str, Any] | None:
    combined = f"{label} {raw_value}".lower()
    hour_pattern = r"(?:小时|时长|(?<![a-z])(?:hours?|hrs?|h)(?![a-z]))"
    minute_pattern = r"(?:分钟|(?<![a-z])(?:minutes?|mins?|min)(?![a-z]))"
    if not re.search(f"(?:{hour_pattern}|{minute_pattern})", combined):
        return None
    values = _all_numbers(raw_value)
    if not values:
        return None
    if len(values) > 2:
        return None
    if len(values) == 2 and not re.search(
        r"[0-9]+(?:\.[0-9]+)?\s*(?:-|~|～|至|到|to)\s*"
        r"[0-9]+(?:\.[0-9]+)?",
        raw_value,
        flags=re.IGNORECASE,
    ):
        # Two unrelated numbers (for example a mode count plus a runtime) are
        # not silently reinterpreted as a duration range.
        return None
    if re.search(minute_pattern, combined):
        values = [value / Decimal("60") for value in values]
    return _evidence(
        value=_range_or_value(values),
        unit="h",
        raw_value=raw_value,
        source_label=label,
    )


def _combined_dimensions_spec(label: str, raw_value: str) -> dict[str, Any] | None:
    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:x|×|\*)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:x|×|\*)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(mm|毫米|cm|厘米|m|米|in|inch|英寸)?",
        raw_value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    unit = _dimension_unit(match.group(4) or _unit_from_label(label))
    if unit is None:
        return None
    values = [_decimal(match.group(index)) for index in (1, 2, 3)]
    if any(value is None or value <= 0 for value in values):
        return None
    converted = [_dimension_to_cm(value, unit) for value in values if value is not None]
    if len(converted) != 3:
        return None
    return {
        "length": _evidence(
            value=_json_number(converted[0]),
            unit="cm",
            raw_value=raw_value,
            source_label=label,
        ),
        "width": _evidence(
            value=_json_number(converted[1]),
            unit="cm",
            raw_value=raw_value,
            source_label=label,
        ),
        "height": _evidence(
            value=_json_number(converted[2]),
            unit="cm",
            raw_value=raw_value,
            source_label=label,
        ),
        "unit": "cm",
        "raw_value": raw_value,
        "source_label": label,
    }


def normalize_combined_dimensions(
    label: str,
    raw_value: str,
) -> dict[str, Any] | None:
    """Public fail-safe projection for an evidenced L x W x H value."""

    return _combined_dimensions_spec(label, raw_value)


def _dimension_leaf(label: str, raw_value: str) -> dict[str, Any] | None:
    values = _numbers(raw_value)
    if not values:
        return None
    unit_match = re.search(r"(mm|毫米|cm|厘米|m|米|in|inch|英寸)\b?", raw_value, flags=re.IGNORECASE)
    unit = _dimension_unit(unit_match.group(1) if unit_match else _unit_from_label(label))
    if unit is None:
        return None
    value_cm = _dimension_to_cm(values[0], unit)
    return _evidence(
        value=_json_number(value_cm),
        unit="cm",
        raw_value=raw_value,
        source_label=label,
    )


def _weight_spec(label: str, raw_value: str) -> dict[str, Any] | None:
    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*(kg|千克|公斤|g|克|lb|lbs|pounds?|磅|oz|盎司)",
        raw_value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = _decimal(match.group(1))
    if value is None or value <= 0:
        return None
    unit = match.group(2).lower()
    if unit in {"g", "克"}:
        value /= Decimal("1000")
    elif unit in {"lb", "lbs", "pound", "pounds", "磅"}:
        value *= Decimal("0.45359237")
    elif unit in {"oz", "盎司"}:
        value *= Decimal("0.028349523125")
    return _evidence(
        value=_json_number(value),
        unit="kg",
        raw_value=raw_value,
        source_label=label,
    )


def _merge_standard_spec(output: dict[str, Any], spec_key: str, value: dict[str, Any]) -> None:
    if spec_key.startswith("dimensions."):
        axis = spec_key.split(".", 1)[1]
        dimensions = output.setdefault("dimensions", {"unit": "cm"})
        if isinstance(dimensions, dict) and axis not in dimensions and axis in value:
            dimensions[axis] = value[axis]
            dimensions.setdefault("raw_value", value.get("raw_value"))
            dimensions.setdefault("source_label", value.get("source_label"))
        return
    if spec_key == "certifications" and spec_key in output:
        existing = output[spec_key]
        if isinstance(existing, dict) and isinstance(existing.get("value"), list):
            existing_values = list(existing["value"])
            for item in value.get("value") or []:
                if item not in existing_values:
                    existing_values.append(item)
            existing["value"] = existing_values
        return
    output.setdefault(spec_key, value)


def _merge_detail_measurements(output: dict[str, Any], payload: dict[str, Any]) -> None:
    detail = payload.get("detail_page_crawler")
    detail = detail if isinstance(detail, dict) else {}

    def first_number(*keys: str) -> Decimal | None:
        for key in keys:
            value = payload.get(key)
            if value is None:
                value = detail.get(key)
            parsed = _decimal(value)
            if parsed is not None and parsed > 0:
                return parsed
        return None

    dimensions = output.get("dimensions")
    if not isinstance(dimensions, dict):
        dimensions = {"unit": "cm"}
    for axis in ("length", "width", "height"):
        if axis in dimensions:
            continue
        value = first_number(f"supplier_{axis}_cm", f"{axis}_cm")
        if value is not None:
            dimensions[axis] = _evidence(
                value=_json_number(value),
                unit="cm",
                raw_value=f"{_json_number(value)} cm",
                source_label="1688 detail page",
            )
    if any(axis in dimensions for axis in ("length", "width", "height")):
        output["dimensions"] = dimensions

    if "weight" not in output:
        value = first_number("supplier_actual_weight_kg", "actual_weight_kg")
        if value is not None:
            output["weight"] = _evidence(
                value=_json_number(value),
                unit="kg",
                raw_value=f"{_json_number(value)} kg",
                source_label="1688 detail page",
            )


def _additional_spec(
    label: str,
    raw_value: str,
    *,
    label_en: Any = None,
    value_en: Any = None,
) -> dict[str, Any]:
    ascii_key = re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKC", label).lower()).strip("_")
    if not ascii_key:
        digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:10]
        ascii_key = f"supplier_attribute_{digest}"
    item = {
        "key": ascii_key[:128],
        "label": label[:255],
        "source_label": label[:255],
        "value": raw_value[:1000],
        "raw_value": raw_value[:1000],
    }
    public_label = buyer_english_text(label_en, limit=255)
    if public_label is None:
        public_label = buyer_english_text(label, limit=255)
    public_value = buyer_english_text(value_en, limit=1000)
    if public_value is None:
        public_value = buyer_english_text(raw_value, limit=1000)
    if public_label:
        item["label_en"] = public_label
    if public_value:
        item["value_en"] = public_value
    return item


def _evidence(
    *,
    value: Any,
    raw_value: str,
    source_label: str,
    unit: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "value": value,
        "raw_value": raw_value[:1000],
        "source_label": source_label[:255],
    }
    if unit:
        result["unit"] = unit
    return result


def _numbers(value: str) -> list[Decimal]:
    return _all_numbers(value)[:2]


def _all_numbers(value: str) -> list[Decimal]:
    output: list[Decimal] = []
    for match in re.finditer(r"(?<![A-Za-z0-9])([0-9]+(?:\.[0-9]+)?)", value.replace(",", "")):
        parsed = _decimal(match.group(1))
        if parsed is not None:
            output.append(parsed)
    return output


def _label_unit_measurement_values(value: str) -> list[Decimal]:
    number = r"([0-9]+(?:\.[0-9]+)?)"
    normalized = value.replace(",", "").strip()
    range_match = re.fullmatch(
        rf"{number}\s*(?:-|~|～|至|到)\s*{number}",
        normalized,
    )
    if range_match:
        return [
            parsed
            for raw_number in range_match.groups()
            if (parsed := _decimal(raw_number)) is not None
        ]
    scalar_match = re.fullmatch(number, normalized)
    if scalar_match:
        parsed = _decimal(scalar_match.group(1))
        return [parsed] if parsed is not None else []
    return []


def _range_or_value(values: list[Decimal]) -> Any:
    if len(values) == 1:
        return _json_number(values[0])
    minimum, maximum = values[0], values[1]
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    return {"min": _json_number(minimum), "max": _json_number(maximum)}


def _json_number(value: Decimal) -> int | float:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return int(normalized)
    return float(normalized)


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _dimension_unit(value: Any) -> str | None:
    text = _clean_text(value).lower() if _clean_text(value) else ""
    if text in {"mm", "毫米"}:
        return "mm"
    if text in {"cm", "厘米"}:
        return "cm"
    if text in {"m", "米"}:
        return "m"
    if text in {"in", "inch", "英寸"}:
        return "in"
    return None


def _dimension_to_cm(value: Decimal, unit: str) -> Decimal:
    if unit == "mm":
        return value / Decimal("10")
    if unit == "m":
        return value * Decimal("100")
    if unit == "in":
        return value * Decimal("2.54")
    return value


def _unit_from_label(label: str) -> str | None:
    match = re.search(
        r"(?:\(|（|/|_)(mm|毫米|cm|厘米|m|米|in|inch|英寸)(?:\)|）)?",
        label,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def _usable_value(value: str) -> bool:
    return value.strip().casefold() not in _EMPTY_VALUE_MARKERS


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _clean_text(value) or ""
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        items = [_value_text(item) for item in value]
        return ", ".join(item for item in items if item)[:1000]
    if isinstance(value, dict):
        normalized = {_normalized_key(key): nested for key, nested in value.items()}
        for key in (*_VALUE_KEYS, "text", "title", "name"):
            if key in normalized:
                text = _value_text(normalized[key])
                if text:
                    return text
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)[:1000]
        except (TypeError, ValueError):
            return ""
    return _clean_text(value) or ""


def _label_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE)


def _normalized_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", normalized).strip("_")


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None
