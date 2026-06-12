# K09 Unit Payload Examples

Status: K09B JSON contract examples draft, pending owner review.

Date: 2026-06-12.

# 1. Metric product dimensions example

Product dimensions: `10 x 5 x 3 cm`.

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
    "source_text": "10 x 5 x 3 cm",
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
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "10 x 5 x 3 cm",
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
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "10 x 5 x 3 cm",
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
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "10 x 5 x 3 cm",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "warnings": [],
    "errors": []
  }
}
```

# 2. Imperial product dimensions example

Product dimensions: `7 in length, 2.25 in diameter`.

Width and height are not represented as `0`.

```json
{
  "dimensions_json": {
    "unit_group": "length",
    "dimension_order": [
      "length",
      "diameter"
    ],
    "dimension_format": "length_diameter",
    "source_text": "7 in length, 2.25 in diameter",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "US",
    "review_status": "needs_review",
    "length": {
      "value_kind": "length",
      "original_value": 7,
      "original_unit": "in",
      "normalized_metric_value": 17.78,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 7,
      "normalized_imperial_unit": "in",
      "display_value": 7,
      "display_unit": "in",
      "display_market": "US",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "7 in length, 2.25 in diameter",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "diameter": {
      "value_kind": "length",
      "original_value": 2.25,
      "original_unit": "in",
      "normalized_metric_value": 5.72,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 2.25,
      "normalized_imperial_unit": "in",
      "display_value": 2.25,
      "display_unit": "in",
      "display_market": "US",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "7 in length, 2.25 in diameter",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "missing_fields": [
      "width",
      "height"
    ],
    "warnings": [],
    "errors": []
  }
}
```

# 3. Package dimensions example

Package dimensions: `12 x 8 x 4 in`.

This example uses `package_dimensions_json` only and does not mix in `dimensions_json`.

```json
{
  "package_dimensions_json": {
    "package_unit_group": "length",
    "package_dimension_order": [
      "package_length",
      "package_width",
      "package_height"
    ],
    "package_dimension_format": "l_w_h",
    "package_source_text": "12 x 8 x 4 in",
    "display_market": "US",
    "review_status": "needs_review",
    "package_length": {
      "value_kind": "length",
      "original_value": 12,
      "original_unit": "in",
      "normalized_metric_value": 30.48,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 12,
      "normalized_imperial_unit": "in",
      "display_value": 12,
      "display_unit": "in",
      "display_market": "US",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "12 x 8 x 4 in",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "package_width": {
      "value_kind": "length",
      "original_value": 8,
      "original_unit": "in",
      "normalized_metric_value": 20.32,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 8,
      "normalized_imperial_unit": "in",
      "display_value": 8,
      "display_unit": "in",
      "display_market": "US",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "12 x 8 x 4 in",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "package_height": {
      "value_kind": "length",
      "original_value": 4,
      "original_unit": "in",
      "normalized_metric_value": 10.16,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 4,
      "normalized_imperial_unit": "in",
      "display_value": 4,
      "display_unit": "in",
      "display_market": "US",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "12 x 8 x 4 in",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "warnings": [],
    "errors": []
  }
}
```

# 4. Product weight example

Product net weight: `1.2 kg`.

```json
{
  "weight_json": {
    "unit_group": "weight",
    "source_text": "net weight: 1.2 kg",
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
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "net weight: 1.2 kg",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "warnings": [],
    "errors": []
  }
}
```

# 5. Package weight example

Package weight: `3 lb`.

```json
{
  "package_weight_json": {
    "unit_group": "weight",
    "source_text": "package weight: 3 lb",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "US",
    "review_status": "needs_review",
    "package_weight": {
      "value_kind": "weight",
      "original_value": 3,
      "original_unit": "lb",
      "normalized_metric_value": 1.36,
      "normalized_metric_unit": "kg",
      "normalized_imperial_value": 3,
      "normalized_imperial_unit": "lb",
      "display_value": 3,
      "display_unit": "lb",
      "display_market": "US",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "package weight: 3 lb",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "warnings": [],
    "errors": []
  }
}
```

# 6. Ambiguous weight example

Input: `weight: 2 lb`.

The value is explicit, but net/gross/package context is ambiguous and requires review.

```json
{
  "weight_json": {
    "unit_group": "weight",
    "source_text": "weight: 2 lb",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "US",
    "review_status": "needs_review",
    "net_weight": {
      "value_kind": "weight",
      "original_value": 2,
      "original_unit": "lb",
      "normalized_metric_value": 0.91,
      "normalized_metric_unit": "kg",
      "normalized_imperial_value": 2,
      "normalized_imperial_unit": "lb",
      "display_value": 2,
      "display_unit": "lb",
      "display_market": "US",
      "conversion_source": "operator_entered",
      "conversion_precision": "2_decimal_places",
      "source_text": "weight: 2 lb",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [
        "net_vs_gross_weight_ambiguous"
      ],
      "errors": []
    },
    "warnings": [
      "net_vs_gross_weight_ambiguous"
    ],
    "errors": []
  }
}
```

# 7. Unsupported unit example

Input: `10 stone`.

```json
{
  "weight_json": {
    "unit_group": "weight",
    "source_text": "10 stone",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "UK",
    "review_status": "blocked",
    "net_weight": {
      "value_kind": "weight",
      "original_value": 10,
      "original_unit": "stone",
      "normalized_metric_value": null,
      "normalized_metric_unit": null,
      "normalized_imperial_value": null,
      "normalized_imperial_unit": null,
      "display_value": null,
      "display_unit": null,
      "display_market": "UK",
      "conversion_source": "operator_entered",
      "conversion_precision": "conversion_not_possible",
      "source_text": "10 stone",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "blocked",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": [
        "unsupported_unit",
        "conversion_not_possible"
      ]
    },
    "warnings": [],
    "errors": [
      "unsupported_unit",
      "conversion_not_possible"
    ]
  }
}
```

# 8. Missing unit example

Input: `length: 10`.

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
    "review_status": "blocked",
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
      "conversion_source": "operator_entered",
      "conversion_precision": "conversion_not_possible",
      "source_text": "length: 10",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "blocked",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": [
        "missing_unit",
        "conversion_not_possible"
      ]
    },
    "warnings": [
      "display_market_missing"
    ],
    "errors": [
      "missing_unit",
      "conversion_not_possible"
    ]
  }
}
```

# 9. AI structured from provided input example

AI only structures values explicitly present in source text. Missing height is not guessed.

```json
{
  "dimensions_json": {
    "unit_group": "length",
    "dimension_order": [
      "length",
      "width"
    ],
    "dimension_format": "l_w_partial",
    "source_text": "Product size: length 20 cm, width 10 cm.",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "EU",
    "review_status": "needs_review",
    "length": {
      "value_kind": "length",
      "original_value": 20,
      "original_unit": "cm",
      "normalized_metric_value": 20,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 7.87,
      "normalized_imperial_unit": "in",
      "display_value": 20,
      "display_unit": "cm",
      "display_market": "EU",
      "conversion_source": "ai_structured_from_provided_input",
      "conversion_precision": "2_decimal_places",
      "source_text": "Product size: length 20 cm, width 10 cm.",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "width": {
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
      "source_text": "Product size: length 20 cm, width 10 cm.",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "missing_fields": [
      "height"
    ],
    "warnings": [],
    "errors": []
  }
}
```

# 10. Reviewer corrected example

Original input remains preserved while reviewer corrected value takes precedence.

```json
{
  "weight_json": {
    "unit_group": "weight",
    "source_text": "net weight: 1.0 kg",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "EU",
    "review_status": "reviewer_corrected",
    "net_weight": {
      "value_kind": "weight",
      "original_value": 1,
      "original_unit": "kg",
      "normalized_metric_value": 1.1,
      "normalized_metric_unit": "kg",
      "normalized_imperial_value": 2.43,
      "normalized_imperial_unit": "lb",
      "display_value": 1.1,
      "display_unit": "kg",
      "display_market": "EU",
      "conversion_source": "reviewer_corrected",
      "conversion_precision": "2_decimal_places",
      "source_text": "net weight: 1.0 kg",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "reviewer_corrected",
      "reviewer_corrected": true,
      "reviewer_corrected_value": 1.1,
      "reviewer_corrected_unit": "kg",
      "field_diff_reference": "field_diff_json.weight_json.net_weight.2026-06-12T00:00:00Z",
      "warnings": [],
      "errors": []
    },
    "warnings": [],
    "errors": []
  }
}
```

# 11. US display example

Original metric value is stored. US display selects imperial without rewriting original.

```json
{
  "dimensions_json": {
    "unit_group": "length",
    "dimension_order": [
      "length"
    ],
    "dimension_format": "single_dimension",
    "source_text": "length: 25 cm",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "US",
    "review_status": "needs_review",
    "length": {
      "value_kind": "length",
      "original_value": 25,
      "original_unit": "cm",
      "normalized_metric_value": 25,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 9.84,
      "normalized_imperial_unit": "in",
      "display_value": 9.84,
      "display_unit": "in",
      "display_market": "US",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "length: 25 cm",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "warnings": [],
    "errors": []
  }
}
```

# 12. EU display example

Original imperial value is stored. EU display selects metric without rewriting original.

```json
{
  "weight_json": {
    "unit_group": "weight",
    "source_text": "net weight: 2 lb",
    "source_language": "en",
    "parsed_from_text": true,
    "display_market": "EU",
    "review_status": "needs_review",
    "net_weight": {
      "value_kind": "weight",
      "original_value": 2,
      "original_unit": "lb",
      "normalized_metric_value": 0.91,
      "normalized_metric_unit": "kg",
      "normalized_imperial_value": 2,
      "normalized_imperial_unit": "lb",
      "display_value": 0.91,
      "display_unit": "kg",
      "display_market": "EU",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "net weight: 2 lb",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "warnings": [],
    "errors": []
  }
}
```

# 13. Unknown is not zero example

Missing height is not represented as `0`. Downstream gates must not treat unknown as a valid numeric value.

```json
{
  "dimensions_json": {
    "unit_group": "length",
    "dimension_order": [
      "length",
      "width"
    ],
    "dimension_format": "l_w_partial",
    "source_text": "10 x 5 cm, height unknown",
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
      "conversion_source": "operator_entered",
      "conversion_precision": "2_decimal_places",
      "source_text": "10 x 5 cm, height unknown",
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
      "conversion_source": "operator_entered",
      "conversion_precision": "2_decimal_places",
      "source_text": "10 x 5 cm, height unknown",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "missing_fields": [
      "height"
    ],
    "downstream_gate": {
      "ready_for_woo_draft": false,
      "reason_codes": [
        "missing_value"
      ],
      "unknown_must_not_be_treated_as_zero": true
    },
    "warnings": [
      "missing_value"
    ],
    "errors": []
  }
}
```

# 14. Temperature future example

Future-only temperature range with explicit operating context.

```json
{
  "temperature_payload": {
    "contract_status": "future_only",
    "unit_group": "temperature",
    "supported_units": [
      "c",
      "f"
    ],
    "temperature_context": "operating",
    "source_text": "Operating temperature: -10 C to 45 C",
    "source_language": "en",
    "display_market": "US",
    "review_status": "needs_review",
    "temperature_range_min": {
      "value_kind": "temperature",
      "original_value": -10,
      "original_unit": "c",
      "normalized_metric_value": -10,
      "normalized_metric_unit": "c",
      "normalized_imperial_value": 14,
      "normalized_imperial_unit": "f",
      "display_value": 14,
      "display_unit": "f",
      "display_market": "US",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "Operating temperature: -10 C to 45 C",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "temperature_range_max": {
      "value_kind": "temperature",
      "original_value": 45,
      "original_unit": "c",
      "normalized_metric_value": 45,
      "normalized_metric_unit": "c",
      "normalized_imperial_value": 113,
      "normalized_imperial_unit": "f",
      "display_value": 113,
      "display_unit": "f",
      "display_market": "US",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "Operating temperature: -10 C to 45 C",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "warnings": [],
    "errors": []
  }
}
```

# 15. Volume future example

Future-only capacity payload using supported volume units.

```json
{
  "volume_payload": {
    "contract_status": "future_only",
    "unit_group": "volume",
    "supported_units": [
      "ml",
      "l",
      "fl_oz"
    ],
    "source_text": "Capacity: 750 ml",
    "source_language": "en",
    "display_market": "US",
    "review_status": "needs_review",
    "capacity": {
      "value_kind": "volume",
      "original_value": 750,
      "original_unit": "ml",
      "normalized_metric_value": 0.75,
      "normalized_metric_unit": "l",
      "normalized_imperial_value": 25.36,
      "normalized_imperial_unit": "fl_oz",
      "display_value": 25.36,
      "display_unit": "fl_oz",
      "display_market": "US",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places",
      "source_text": "Capacity: 750 ml",
      "source_language": "en",
      "parsed_from_text": true,
      "review_status": "needs_review",
      "reviewer_corrected": false,
      "warnings": [],
      "errors": []
    },
    "warnings": [],
    "errors": []
  }
}
```

- These examples are contract examples only.
- They are not runtime code.
- They do not create DB rows.
- They do not modify migrations.
- They do not connect live providers.
- They do not read or modify P-series workflows.
