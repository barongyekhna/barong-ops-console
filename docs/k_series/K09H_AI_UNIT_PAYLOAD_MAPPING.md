# 1. Mapping purpose

This file maps future K10 AI mock adapter unit output to the K09 payload contract.

K10 mock output may structure explicit numeric value + unit evidence already provided by a user, supplier, operator, or approved source. It must not guess dimensions, weight, packaging context, net/gross meaning, or missing units.

# 2. AI input sources

Allowed AI input source references:

- `raw_input_text`
- `raw_input_language`
- `raw_input_payload_json`
- supplier text
- operator notes
- manual `source_text`
- future image/visual extracted notes as draft only

All AI output from these sources must preserve `source_text`, `source_language`, and `parsed_from_text` where applicable. Visual extracted notes remain draft-only and cannot become reviewed facts without human review.

# 3. Product dimensions output mapping

| AI extracted item | K09 payload path | Required evidence | Allowed output status | Required warning/error if ambiguous | Human review required? |
| --- | --- | --- | --- | --- | --- |
| `length` | `dimensions_json.length` | Explicit product length numeric value + supported length unit. | `draft` / `needs_review` | `missing_value`, `missing_unit`, `unsupported_unit`, or `review_required` | yes |
| `width` | `dimensions_json.width` | Explicit product width numeric value + supported length unit. | `draft` / `needs_review` | `missing_value`, `missing_unit`, `unsupported_unit`, or `review_required` | yes |
| `height` | `dimensions_json.height` | Explicit product height numeric value + supported length unit. | `draft` / `needs_review` | `missing_value`, `missing_unit`, `unsupported_unit`, or `review_required` | yes |
| `diameter` | `dimensions_json.diameter` | Source explicitly identifies diameter. | `draft` / `needs_review` | `ambiguous_dimension_format` if only implied by shape or category. | yes |
| `thickness` | `dimensions_json.thickness` | Source explicitly identifies thickness. | `draft` / `needs_review` | `ambiguous_dimension_format` if only implied by category. | yes |
| `dimension_order` | `dimensions_json.dimension_order` | Explicit source order or reviewed labels such as length/width/height. | `draft` / `needs_review` | `dimension_order_missing`, `ambiguous_dimension_format` | yes |
| `dimension_format` | `dimensions_json.dimension_format` | Explicit or safely classified format such as `l_w_h`, `length_diameter`, or `single_dimension`. | `draft` / `needs_review` | `ambiguous_dimension_format` | yes |
| `source_text` | `dimensions_json.source_text` | Original text that produced the draft. | `draft` / `needs_review` | `free_text_parsing_not_supported` or `review_required` if text cannot be safely mapped. | yes |

Product dimensions must not be copied to `package_dimensions_json`.

# 4. Package dimensions output mapping

| AI extracted item | K09 payload path | Required evidence | Allowed output status | Required warning/error if ambiguous | Human review required? |
| --- | --- | --- | --- | --- | --- |
| `package_length` | `package_dimensions_json.package_length` | Explicit package/shipping length numeric value + supported length unit. | `draft` / `needs_review` | `missing_value`, `missing_unit`, `unsupported_unit`, or `product_vs_package_conflict` | yes |
| `package_width` | `package_dimensions_json.package_width` | Explicit package/shipping width numeric value + supported length unit. | `draft` / `needs_review` | `missing_value`, `missing_unit`, `unsupported_unit`, or `product_vs_package_conflict` | yes |
| `package_height` | `package_dimensions_json.package_height` | Explicit package/shipping height numeric value + supported length unit. | `draft` / `needs_review` | `missing_value`, `missing_unit`, `unsupported_unit`, or `product_vs_package_conflict` | yes |
| `package_diameter` | `package_dimensions_json.package_diameter` | Source explicitly identifies package diameter. | `draft` / `needs_review` | `ambiguous_dimension_format` or `product_vs_package_conflict` | yes |
| `package_dimension_order` | `package_dimensions_json.package_dimension_order` | Explicit package source order or reviewed package labels. | `draft` / `needs_review` | `dimension_order_missing`, `ambiguous_dimension_format` | yes |
| `package_dimension_format` | `package_dimensions_json.package_dimension_format` | Explicit or safely classified package format. | `draft` / `needs_review` | `ambiguous_dimension_format` | yes |
| `package_source_text` | `package_dimensions_json.package_source_text` | Original package/shipping source text. | `draft` / `needs_review` | `free_text_parsing_not_supported`, `product_vs_package_conflict`, or `review_required` | yes |

Package dimensions must not be copied to `dimensions_json`.

# 5. Product weight output mapping

| AI extracted item | K09 payload path | Required evidence | Allowed output status | Required warning/error if ambiguous | Human review required? |
| --- | --- | --- | --- | --- | --- |
| `net_weight` | `weight_json.net_weight` | Source explicitly says product net weight, item weight, or an owner-approved equivalent. | `draft` / `needs_review` | `net_vs_gross_weight_ambiguous` when net/gross context is unclear. | yes |
| `gross_weight` | `weight_json.gross_weight` | Source explicitly says product gross weight. | `draft` / `needs_review` | `net_vs_gross_weight_ambiguous` when gross context is unclear. | yes |
| `source_text` | `weight_json.source_text` | Original product weight source text. | `draft` / `needs_review` | `review_required` if source is generic. | yes |
| net_vs_gross ambiguity | `weight_json.errors[]` / `weight_json.warnings[]` | Generic weight text such as `weight: 2 lb` without net/gross/package/shipping context. | `needs_review` | `net_vs_gross_weight_ambiguous` | yes |

Generic `weight: 2 lb` must not be silently written as `net_weight`.

# 6. Package weight output mapping

| AI extracted item | K09 payload path | Required evidence | Allowed output status | Required warning/error if ambiguous | Human review required? |
| --- | --- | --- | --- | --- | --- |
| `package_weight` | `package_weight_json.package_weight` | Source explicitly says package weight. | `draft` / `needs_review` | `product_vs_package_conflict` or `net_vs_gross_weight_ambiguous` | yes |
| `shipping_weight` | `package_weight_json.shipping_weight` | Source explicitly says shipping weight. | `draft` / `needs_review` | `product_vs_package_conflict` or `net_vs_gross_weight_ambiguous` | yes |
| `source_text` | `package_weight_json.source_text` | Original package/shipping weight source text. | `draft` / `needs_review` | `review_required` if source is generic. | yes |
| package vs product ambiguity | `package_weight_json.errors[]` / `package_weight_json.warnings[]` | Source mixes item, product, package, gross, or shipping language. | `needs_review` | `product_vs_package_conflict`, `review_required` | yes |

Package or shipping weight must not be copied to product `weight_json.net_weight`.

# 7. Unit Value Payload output mapping

| K09 field | AI output rule | Required evidence | Allowed output status |
| --- | --- | --- | --- |
| `value_kind` | Must match the unit group, such as `length` or `weight`. | Target K09 payload path and unit group. | `draft` / `needs_review` |
| `original_value` | Preserve explicit numeric source value. Never use `0` for missing. | Explicit numeric value. | `draft` / `needs_review` |
| `original_unit` | Preserve explicit source unit or `null` when missing. Must not use `display_unit` as substitute. | Explicit source unit. | `draft` / `needs_review` |
| `normalized_metric_value` | May be produced only from explicit original value + supported unit + deterministic K09 conversion rule. | Supported unit and valid numeric value. | `draft` / `needs_review` or `null` with errors |
| `normalized_metric_unit` | Must match K09 metric unit for the group if conversion is possible. | Supported unit group. | `draft` / `needs_review` or `null` with errors |
| `normalized_imperial_value` | May be produced only from explicit original value + supported unit + deterministic K09 conversion rule. | Supported unit and valid numeric value. | `draft` / `needs_review` or `null` with errors |
| `normalized_imperial_unit` | Must match K09 imperial unit for the group if conversion is possible. | Supported unit group. | `draft` / `needs_review` or `null` with errors |
| `display_value` | Display suggestion only. Must not overwrite original value. | Resolved display market and supported conversion. | `draft` / `needs_review` or `null` with warnings/errors |
| `display_unit` | Display suggestion only. Must not overwrite original unit. | Resolved display market and unit group. | `draft` / `needs_review` or `null` with warnings/errors |
| `display_market` | Preserve supplied market or set `unknown`/fallback with warning. | Explicit market context or safe fallback rule. | `draft` / `needs_review` |
| `conversion_source` | For AI should be `ai_structured_from_provided_input`. | AI structured an explicit value already present in input. | `draft` / `needs_review` |
| `conversion_precision` | Use deterministic conversion precision or `conversion_not_possible`. | Conversion result or blocking conversion error. | `draft` / `needs_review` |
| `source_text` | Preserve exact source text where available. | Source fragment or manual source text. | `draft` / `needs_review` |
| `source_language` | Preserve source language or `unknown`. | Input language metadata. | `draft` / `needs_review` |
| `parsed_from_text` | Means AI attempted to structure source text only. It is not human confirmation. | Source-text based extraction attempt. | `draft` / `needs_review` |
| `review_status` | Should be `draft` or `needs_review`. | AI output lifecycle state. | `draft` / `needs_review` only |
| `reviewer_corrected` | Must be `false`. | AI cannot perform reviewer correction. | `draft` / `needs_review` |
| `warnings` | Attach K09 warning codes. | Ambiguity, display fallback, review requirement, or optional missing fields. | `draft` / `needs_review` |
| `errors` | Attach K09 error codes. | Missing value/unit, unsupported unit, invalid value, ambiguity, or forbidden guessing. | `draft` / `needs_review` |

`conversion_source` for AI should be `ai_structured_from_provided_input`.

`review_status` should be `draft` or `needs_review`.

`reviewer_corrected` must be `false`.

AI cannot output `reviewed` / `reviewer_corrected`.

# 8. Examples

## 8.1 Clear product dimensions from provided text

```json
{
  "dimensions_json": {
    "unit_group": "length",
    "dimension_order": [
      "length",
      "width",
      "height"
    ],
    "dimension_format": "l_w_h",
    "source_text": "Product dimensions: length 10 cm, width 5 cm, height 3 cm.",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "EU",
    "review_status": "needs_review",
    "length": {
      "value_kind": "length",
      "original_value": 10,
      "original_unit": "cm",
      "normalized_metric_value": 10,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 3.94,
      "normalized_imperial_unit": "in",
      "display_value": 10,
      "display_unit": "cm",
      "display_market": "EU",
      "conversion_source": "ai_structured_from_provided_input",
      "conversion_precision": "2_decimal_places",
      "source_text": "Product dimensions: length 10 cm, width 5 cm, height 3 cm.",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "width": {
      "value_kind": "length",
      "original_value": 5,
      "original_unit": "cm",
      "normalized_metric_value": 5,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 1.97,
      "normalized_imperial_unit": "in",
      "display_value": 5,
      "display_unit": "cm",
      "display_market": "EU",
      "conversion_source": "ai_structured_from_provided_input",
      "conversion_precision": "2_decimal_places",
      "source_text": "Product dimensions: length 10 cm, width 5 cm, height 3 cm.",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "height": {
      "value_kind": "length",
      "original_value": 3,
      "original_unit": "cm",
      "normalized_metric_value": 3,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 1.18,
      "normalized_imperial_unit": "in",
      "display_value": 3,
      "display_unit": "cm",
      "display_market": "EU",
      "conversion_source": "ai_structured_from_provided_input",
      "conversion_precision": "2_decimal_places",
      "source_text": "Product dimensions: length 10 cm, width 5 cm, height 3 cm.",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "warnings": [
      "review_required"
    ],
    "errors": []
  }
}
```

## 8.2 Ambiguous 10 x 5 x 3 cm requiring dimension_order warning

```json
{
  "dimensions_json": {
    "unit_group": "length",
    "dimension_order": [
      "unknown_1",
      "unknown_2",
      "unknown_3"
    ],
    "dimension_format": "ambiguous_3_part",
    "source_text": "10 x 5 x 3 cm",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "unknown",
    "review_status": "needs_review",
    "missing_field_hints": [
      "length",
      "width",
      "height"
    ],
    "ai_warnings_json": [
      {
        "code": "dimension_order_missing",
        "message": "AI preserved the three provided values but did not assign them to length, width, or height."
      },
      {
        "code": "review_required",
        "message": "Human review must set dimension_order before downstream use."
      }
    ],
    "field_diff_json": {
      "dimensions_json.unassigned_dimension_candidates": {
        "provided_values": [
          10,
          5,
          3
        ],
        "provided_unit": "cm",
        "source_text": "10 x 5 x 3 cm",
        "conversion_source": "ai_structured_from_provided_input",
        "proposed_action": "review_dimension_order"
      }
    },
    "warnings": [
      "dimension_order_missing",
      "review_required"
    ],
    "errors": [
      "ambiguous_dimension_format"
    ]
  }
}
```

## 8.3 Product weight 1.2 kg clear

```json
{
  "weight_json": {
    "unit_group": "weight",
    "source_text": "Net weight: 1.2 kg",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "EU",
    "review_status": "needs_review",
    "net_weight": {
      "value_kind": "weight",
      "original_value": 1.2,
      "original_unit": "kg",
      "normalized_metric_value": 1.2,
      "normalized_metric_unit": "kg",
      "normalized_imperial_value": 2.65,
      "normalized_imperial_unit": "lb",
      "display_value": 1.2,
      "display_unit": "kg",
      "display_market": "EU",
      "conversion_source": "ai_structured_from_provided_input",
      "conversion_precision": "2_decimal_places",
      "source_text": "Net weight: 1.2 kg",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "warnings": [
      "review_required"
    ],
    "errors": []
  }
}
```

## 8.4 Generic weight: 2 lb ambiguous net/gross

```json
{
  "weight_json": {
    "unit_group": "weight",
    "source_text": "weight: 2 lb",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "US",
    "review_status": "needs_review",
    "missing_field_hints": [
      "net_weight",
      "gross_weight",
      "package_weight",
      "shipping_weight"
    ],
    "field_diff_json": {
      "weight_json.unassigned_weight_candidate": {
        "provided_value": 2,
        "provided_unit": "lb",
        "source_text": "weight: 2 lb",
        "conversion_source": "ai_structured_from_provided_input",
        "proposed_action": "review_net_gross_or_package_context"
      }
    },
    "warnings": [
      "review_required"
    ],
    "errors": [
      "net_vs_gross_weight_ambiguous"
    ]
  }
}
```

## 8.5 AI source with missing unit

```json
{
  "dimensions_json": {
    "unit_group": "length",
    "dimension_order": [
      "length"
    ],
    "dimension_format": "single_dimension",
    "source_text": "length: 10",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "unknown",
    "review_status": "needs_review",
    "length": {
      "value_kind": "length",
      "original_value": 10,
      "original_unit": null,
      "normalized_metric_value": null,
      "normalized_metric_unit": null,
      "normalized_imperial_value": null,
      "normalized_imperial_unit": null,
      "display_value": null,
      "display_unit": null,
      "display_market": "unknown",
      "conversion_source": "ai_structured_from_provided_input",
      "conversion_precision": "conversion_not_possible",
      "source_text": "length: 10",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": [
        "missing_unit",
        "conversion_not_possible"
      ]
    },
    "warnings": [
      "display_market_missing",
      "review_required"
    ],
    "errors": [
      "missing_unit",
      "conversion_not_possible"
    ]
  }
}
```
