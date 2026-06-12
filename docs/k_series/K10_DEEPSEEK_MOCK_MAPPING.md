# K10 DeepSeek Mock Mapping

Status: K10A docs-only mock mapping.

Date: 2026-06-12.

# 1. Mapping purpose

This document maps future K10 DeepSeek mock adapter draft output to K09 unit payload paths and K07 review sections.

The mapping is draft only. It does not connect runtime, backend, frontend, n8n, P-series, or live DeepSeek.

# 2. Mapping principles

- AI may structure only explicit numeric value plus explicit unit from provided source material.
- AI must preserve `source_text`, `source_language`, and `parsed_from_text`.
- AI must use `conversion_source = ai_structured_from_provided_input`.
- AI must use `review_status = draft` or `needs_review`.
- AI must use `reviewer_corrected = false`.
- AI must not output canonical, reviewed, approved, publish-ready, shipping-ready, or reviewer-corrected facts.
- AI must not guess product/package context.
- AI must not guess net/gross/shipping context.
- AI must not guess L/W/H order.
- AI must not convert missing or unknown to `0`.

# 3. Input source mapping

| Source input | Mock output location | Rule |
| --- | --- | --- |
| `raw_input_text` | `source.raw_input_text`, payload `source_text` | Preserve exact text. Do not fabricate. |
| `raw_input_language` | `source.raw_input_language`, payload `source_language` | Use provided language or `unknown`. |
| `raw_input_payload_json` | `source` and field-specific `source_text` references | Use only explicit unit facts. |
| supplier text | payload `source_text` | Draft only until reviewed. |
| operator note | payload `source_text` | Draft only unless future review accepts it. |
| display market | payload `display_market` | Controls display suggestion only. |
| current canonical value | `field_diff_json.current_value` | Read-only comparison reference. |
| AI draft candidate | `field_diff_json.draft_value` | Review candidate only. |

# 4. K07 section mapping

| K07 section | K10 mock payload | Required separation |
| --- | --- | --- |
| Product dimensions | `unit_payloads.dimensions_json` | Product body dimensions only. |
| Package dimensions | `unit_payloads.package_dimensions_json` | Package/shipping dimensions only. |
| Product weight | `unit_payloads.weight_json` | Product net/gross weight only. |
| Package/shipping weight | `unit_payloads.package_weight_json` | Package/shipping weight only. |
| Future volume | future volume draft payload or dynamic attribute | Future-only; no DB/runtime implication. |
| Future temperature | future temperature draft payload or dynamic attribute | Future-only; context required. |

# 5. Product dimensions mapping

| Extracted item | K09 path | Required evidence | Warning/error if unsafe |
| --- | --- | --- | --- |
| length | `dimensions_json.length` | Explicit product length value and supported length unit. | `missing_value`, `missing_unit`, `unsupported_unit`, `review_required` |
| width | `dimensions_json.width` | Explicit product width value and supported length unit. | `missing_value`, `missing_unit`, `unsupported_unit`, `review_required` |
| height | `dimensions_json.height` | Explicit product height value and supported length unit. | `missing_value`, `missing_unit`, `unsupported_unit`, `review_required` |
| diameter | `dimensions_json.diameter` | Source explicitly says diameter. | `ambiguous_dimension_format` if inferred from shape/category. |
| thickness | `dimensions_json.thickness` | Source explicitly says thickness. | `ambiguous_dimension_format` if inferred from category. |
| source order | `dimensions_json.dimension_order` | Explicit labels or reviewed order. | `dimension_order_missing`, `ambiguous_dimension_format` |
| source format | `dimensions_json.dimension_format` | Explicit or safely classified format. | `ambiguous_dimension_format` |
| source text | `dimensions_json.source_text` | Original text. | `free_text_parsing_not_supported`, `review_required` |

Mapping rules:

- `10 x 5 x 3 cm` without explicit labels must not become L/W/H.
- It may become unassigned dimension candidates in `field_diff_json`.
- Product dimensions must not be copied into `package_dimensions_json`.

# 6. Package dimensions mapping

| Extracted item | K09 path | Required evidence | Warning/error if unsafe |
| --- | --- | --- | --- |
| package length | `package_dimensions_json.package_length` | Explicit package/shipping length value and supported length unit. | `missing_value`, `missing_unit`, `unsupported_unit`, `product_vs_package_conflict` |
| package width | `package_dimensions_json.package_width` | Explicit package/shipping width value and supported length unit. | `missing_value`, `missing_unit`, `unsupported_unit`, `product_vs_package_conflict` |
| package height | `package_dimensions_json.package_height` | Explicit package/shipping height value and supported length unit. | `missing_value`, `missing_unit`, `unsupported_unit`, `product_vs_package_conflict` |
| package diameter | `package_dimensions_json.package_diameter` | Source explicitly says package diameter. | `ambiguous_dimension_format`, `product_vs_package_conflict` |
| package source order | `package_dimensions_json.package_dimension_order` | Explicit package labels or reviewed order. | `dimension_order_missing`, `ambiguous_dimension_format` |
| package source format | `package_dimensions_json.package_dimension_format` | Explicit or safely classified package format. | `ambiguous_dimension_format` |
| package source text | `package_dimensions_json.package_source_text` | Original package/shipping text. | `free_text_parsing_not_supported`, `product_vs_package_conflict`, `review_required` |

Mapping rules:

- Package dimensions must not be copied into `dimensions_json`.
- Mixed product/package language must produce `product_vs_package_conflict`.

# 7. Product weight mapping

| Extracted item | K09 path | Required evidence | Warning/error if unsafe |
| --- | --- | --- | --- |
| net weight | `weight_json.net_weight` | Source explicitly says net weight, item weight, or an owner-approved equivalent. | `net_vs_gross_weight_ambiguous`, `review_required` |
| gross weight | `weight_json.gross_weight` | Source explicitly says gross weight. | `net_vs_gross_weight_ambiguous`, `review_required` |
| product weight source text | `weight_json.source_text` | Original product weight text. | `free_text_parsing_not_supported`, `review_required` |
| generic weight | `weight_json.warnings[]` and `field_diff_json` | Text such as `weight: 2 lb` without context. | `net_vs_gross_weight_ambiguous` |

Mapping rules:

- Generic `weight: 2 lb` must not be silently written to `net_weight`.
- Product weight must not be copied from package or shipping weight.

# 8. Package weight mapping

| Extracted item | K09 path | Required evidence | Warning/error if unsafe |
| --- | --- | --- | --- |
| package weight | `package_weight_json.package_weight` | Source explicitly says package weight. | `product_vs_package_conflict`, `net_vs_gross_weight_ambiguous` |
| shipping weight | `package_weight_json.shipping_weight` | Source explicitly says shipping weight. | `product_vs_package_conflict`, `net_vs_gross_weight_ambiguous` |
| package weight source text | `package_weight_json.source_text` | Original package/shipping weight text. | `free_text_parsing_not_supported`, `review_required` |
| mixed item/package weight | `package_weight_json.warnings[]` and `field_diff_json` | Source mixes product, item, gross, package, or shipping language. | `product_vs_package_conflict`, `review_required` |

Mapping rules:

- Package or shipping weight must not be copied to `weight_json.net_weight`.
- Mixed weight language requires review.

# 9. Unit Value Payload field mapping

| K09 field | K10 mock rule |
| --- | --- |
| `value_kind` | Match unit group: `length`, `weight`, `volume`, or `temperature`. |
| `original_value` | Preserve explicit numeric source value; never use `0` for missing. |
| `original_unit` | Preserve source unit, canonicalizing only safe K09 aliases. |
| `normalized_metric_value` | Derive only from explicit valid value plus supported unit. |
| `normalized_metric_unit` | Use K09 default metric unit for the group. |
| `normalized_imperial_value` | Derive only from explicit valid value plus supported unit. |
| `normalized_imperial_unit` | Use K09 default imperial unit for the group. |
| `display_value` | Display suggestion only; never replaces original value. |
| `display_unit` | Display suggestion only; never replaces original unit. |
| `display_market` | Preserve supplied market or set `unknown` with warning where needed. |
| `conversion_source` | Must be `ai_structured_from_provided_input`. |
| `conversion_precision` | Use deterministic precision, usually `2_decimal_places`, or `conversion_not_possible`. |
| `source_text` | Preserve exact source fragment when available. |
| `source_language` | Preserve language or use `unknown`. |
| `parsed_from_text` | Means AI attempted structure from text; it is not review approval. |
| `review_status` | `draft` or `needs_review` only. |
| `reviewer_corrected` | Always `false` in mock output. |
| `warnings` | Attach K09/K09E warnings. |
| `errors` | Attach K09/K09E errors. |

# 10. Dynamic attribute mapping

Dynamic attributes may carry unit values only as draft candidates.

Required dynamic attribute evidence:

- `attribute_key`
- `attribute_label`
- explicit numeric value
- explicit unit
- `source_text`
- `source_language` or `unknown`

Suggested shape:

```json
{
  "attribute_key": "capacity",
  "attribute_label": "Capacity",
  "attribute_unit": {
    "value_kind": "volume",
    "original_value": 750,
    "original_unit": "ml",
    "normalized_metric_value": 0.75,
    "normalized_metric_unit": "l",
    "normalized_imperial_value": 25.36,
    "normalized_imperial_unit": "fl_oz",
    "display_value": 0.75,
    "display_unit": "l",
    "display_market": "EU",
    "conversion_source": "ai_structured_from_provided_input",
    "conversion_precision": "2_decimal_places",
    "source_text": "capacity 750 ml",
    "source_language": "en",
    "parsed_from_text": true,
    "review_status": "needs_review",
    "reviewer_corrected": false,
    "warnings": [
      "review_required"
    ],
    "errors": []
  }
}
```

Dynamic attributes must not be used to bypass K09 product/package dimension and weight payload separation.

# 11. Future volume mapping

| Extracted item | K09/future path | Required evidence | Warning/error if unsafe |
| --- | --- | --- | --- |
| volume | future `volume` unit payload or dynamic attribute | Explicit numeric value and `ml`, `l`, or `fl_oz`. | `missing_value`, `missing_unit`, `unsupported_unit` |
| capacity | future `capacity` unit payload or dynamic attribute | Explicit numeric value and `ml`, `l`, or `fl_oz`. | `missing_value`, `missing_unit`, `unsupported_unit` |

Future volume output remains draft-only and does not create DB fields or runtime behavior.

# 12. Future temperature mapping

| Extracted item | K09/future path | Required evidence | Warning/error if unsafe |
| --- | --- | --- | --- |
| single temperature | future `temperature_value` unit payload or dynamic attribute | Explicit numeric value, `c` or `f`, and context. | `missing_value`, `missing_unit`, `unsupported_unit` |
| temperature range | future min/max unit payloads or dynamic attributes | Explicit min/max values, units, and context. | `missing_value`, `missing_unit`, `unsupported_unit` |
| temperature context | future `temperature_context` | Explicit `operating`, `storage`, `warning`, `performance`, or reviewed context. | `review_required` |

Future temperature output remains draft-only and must not guess operating, storage, warning, or performance context.

# 13. Ambiguous source examples

## 13.1 Ambiguous dimensions

Source:

```text
10 x 5 x 3 cm
```

Allowed draft handling:

- Preserve `source_text`.
- Set `parsed_from_text = true`.
- Add `dimension_order_missing`.
- Add `ambiguous_dimension_format`.
- Add `review_required`.
- Put unassigned values in `field_diff_json` as candidates.

Forbidden handling:

- Do not write `length = 10`, `width = 5`, `height = 3` unless labels are explicit or reviewed.

## 13.2 Generic weight

Source:

```text
weight: 2 lb
```

Allowed draft handling:

- Preserve `source_text`.
- Add `net_vs_gross_weight_ambiguous`.
- Add `review_required`.
- Put the value in review candidates if useful.

Forbidden handling:

- Do not write `weight_json.net_weight.original_value = 2` unless net/item/product context is explicit or reviewed.

## 13.3 Package conflict

Source:

```text
Product size 10 cm. Shipping box 12 x 8 x 4 in.
```

Allowed draft handling:

- Keep product size in `dimensions_json` only if the value path is explicit.
- Keep shipping box values in `package_dimensions_json` only if package order is explicit or reviewed.
- Add `product_vs_package_conflict` when source language is mixed or cannot be safely split.

Forbidden handling:

- Do not copy shipping box dimensions into product dimensions.

# 14. Review metadata mapping

`missing_field_hints` should identify missing or unresolved paths:

```json
[
  {
    "path": "dimensions_json.dimension_order",
    "reason": "dimension_order_missing",
    "source_text": "10 x 5 x 3 cm",
    "proposed_action": "set_dimension_order"
  }
]
```

`field_diff_json` should compare current values with draft candidates:

```json
[
  {
    "path": "weight_json.net_weight",
    "current_value": null,
    "draft_value": {
      "candidate_value": 2,
      "candidate_unit": "lb"
    },
    "source_text": "weight: 2 lb",
    "warnings": [
      "net_vs_gross_weight_ambiguous",
      "review_required"
    ],
    "errors": [],
    "proposed_action": "request_review"
  }
]
```

Review metadata must never write canonical values directly.

# 15. Non-integration note

This mapping does not approve:

- Backend runtime imports.
- Backend API exposure.
- Router registration.
- Frontend rendering.
- K07 activation.
- DB writes.
- Operation log writes.
- n8n draft lane consumption.
- P-series workflow consumption.
- Live DeepSeek credentials or calls.

Those require separate owner approval.
