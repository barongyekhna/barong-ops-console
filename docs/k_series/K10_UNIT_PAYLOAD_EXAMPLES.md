# K10 Unit Payload Examples

Status: K10B docs-only DeepSeek mock adapter payload JSON examples.

Date: 2026-06-12.

# 1. Scope

K10B only documents JSON payload examples for the future DeepSeek mock adapter.

K10B does not write Python code, does not modify backend runtime, does not modify frontend, does not modify tests, does not create or change migrations, does not register routers, does not connect APIs, does not run Docker/Alembic/Postgres/staging/production, does not read env, does not connect live services, does not read or modify P-series workflow JSON, does not modify the n8n draft lane, and does not commit.

All JSON blocks below are standalone JSON values and must remain parseable by `json.loads`.

# 2. Payload rules illustrated here

- The outer shape follows the K10A DeepSeek mock adapter envelope.
- Nested unit payloads follow the K09B Unit Value Payload contract.
- Mock AI output uses `conversion_source = ai_structured_from_provided_input`.
- Mock AI output remains `draft` or `needs_review`; it is not reviewed, approved, canonical, publish-ready, shipping-ready, or reviewer-corrected.
- `source_text`, `source_language`, and `parsed_from_text` are preserved where source text is present.
- `original_value` and `original_unit` preserve explicit source input and are not overwritten by normalized or display values.
- Unknown, missing, ambiguous, or not-applicable numeric values are omitted, represented as `null` only for blocked conversion outputs, or listed in review metadata. They are not represented as `0`.
- Unsupported units return `unsupported_unit` and `conversion_not_possible` errors.
- Precision and unknown-market display risks are warnings and do not approve values.
- `field_diff_json` is draft review metadata only. The mock adapter does not apply the diff.

# 3. Valid current unit payloads

This example contains all current K09 unit payload families:

- `dimensions_json`
- `package_dimensions_json`
- `weight_json`
- `package_weight_json`

The display market is `US`, so metric source values may display as imperial. Display values do not rewrite original values.

```json
{
  "adapter_name": "deepseek_mock",
  "adapter_mode": "mock",
  "provider": "deepseek",
  "live_provider_called": false,
  "provider_request_id": null,
  "provider_model": null,
  "draft_review_status": "needs_review",
  "source": {
    "raw_input_text": "Product dimensions: length 20 cm, width 10 cm, height 5 cm. Package dimensions: length 12 in, width 8 in, height 4 in. Net weight: 1.2 kg. Package weight: 3 lb.",
    "raw_input_language": "en",
    "source_record_id": "mock-local-example-001",
    "display_market": "US"
  },
  "unit_payloads": {
    "dimensions_json": {
      "unit_group": "length",
      "dimension_order": [
        "length",
        "width",
        "height"
      ],
      "dimension_format": "l_w_h",
      "source_text": "Product dimensions: length 20 cm, width 10 cm, height 5 cm.",
      "source_language": "en",
      "parsed_from_text": true,
      "display_market": "US",
      "review_status": "needs_review",
      "length": {
        "value_kind": "length",
        "original_value": 20,
        "original_unit": "cm",
        "normalized_metric_value": 20,
        "normalized_metric_unit": "cm",
        "normalized_imperial_value": 7.87,
        "normalized_imperial_unit": "in",
        "display_value": 7.87,
        "display_unit": "in",
        "display_market": "US",
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Product dimensions: length 20 cm, width 10 cm, height 5 cm.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "review_required",
          "precision_loss_warning"
        ],
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
        "display_value": 3.94,
        "display_unit": "in",
        "display_market": "US",
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Product dimensions: length 20 cm, width 10 cm, height 5 cm.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "review_required",
          "precision_loss_warning"
        ],
        "errors": []
      },
      "height": {
        "value_kind": "length",
        "original_value": 5,
        "original_unit": "cm",
        "normalized_metric_value": 5,
        "normalized_metric_unit": "cm",
        "normalized_imperial_value": 1.97,
        "normalized_imperial_unit": "in",
        "display_value": 1.97,
        "display_unit": "in",
        "display_market": "US",
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Product dimensions: length 20 cm, width 10 cm, height 5 cm.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "review_required",
          "precision_loss_warning"
        ],
        "errors": []
      },
      "warnings": [
        "review_required",
        "precision_loss_warning"
      ],
      "errors": []
    },
    "package_dimensions_json": {
      "package_unit_group": "length",
      "package_dimension_order": [
        "package_length",
        "package_width",
        "package_height"
      ],
      "package_dimension_format": "l_w_h",
      "package_source_text": "Package dimensions: length 12 in, width 8 in, height 4 in.",
      "source_language": "en",
      "parsed_from_text": true,
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
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Package dimensions: length 12 in, width 8 in, height 4 in.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "review_required"
        ],
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
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Package dimensions: length 12 in, width 8 in, height 4 in.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "review_required"
        ],
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
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Package dimensions: length 12 in, width 8 in, height 4 in.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "review_required"
        ],
        "errors": []
      },
      "warnings": [
        "review_required"
      ],
      "errors": []
    },
    "weight_json": {
      "unit_group": "weight",
      "source_text": "Net weight: 1.2 kg.",
      "source_language": "en",
      "parsed_from_text": true,
      "display_market": "US",
      "review_status": "needs_review",
      "net_weight": {
        "value_kind": "weight",
        "original_value": 1.2,
        "original_unit": "kg",
        "normalized_metric_value": 1.2,
        "normalized_metric_unit": "kg",
        "normalized_imperial_value": 2.65,
        "normalized_imperial_unit": "lb",
        "display_value": 2.65,
        "display_unit": "lb",
        "display_market": "US",
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Net weight: 1.2 kg.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "review_required",
          "precision_loss_warning"
        ],
        "errors": []
      },
      "warnings": [
        "review_required",
        "precision_loss_warning"
      ],
      "errors": []
    },
    "package_weight_json": {
      "unit_group": "weight",
      "source_text": "Package weight: 3 lb.",
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
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Package weight: 3 lb.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "review_required",
          "precision_loss_warning"
        ],
        "errors": []
      },
      "warnings": [
        "review_required",
        "precision_loss_warning"
      ],
      "errors": []
    }
  },
  "dynamic_attributes_json": [],
  "missing_field_hints": [],
  "ai_warnings_json": [
    {
      "code": "review_required",
      "path": "unit_payloads",
      "message": "Mock AI unit payloads require human review before downstream use."
    },
    {
      "code": "precision_loss_warning",
      "path": "unit_payloads.dimensions_json.length",
      "message": "Imperial display value is rounded to two decimal places."
    }
  ],
  "field_diff_json": [],
  "warnings": [
    "review_required",
    "precision_loss_warning"
  ],
  "errors": []
}
```

# 4. Ambiguous dimension order example

The source has three values and one unit, but no labels. The mock adapter preserves candidates in review metadata and does not write `length`, `width`, or `height`.

```json
{
  "adapter_name": "deepseek_mock",
  "adapter_mode": "mock",
  "provider": "deepseek",
  "live_provider_called": false,
  "provider_request_id": null,
  "provider_model": null,
  "draft_review_status": "needs_review",
  "source": {
    "raw_input_text": "10 x 5 x 3 cm",
    "raw_input_language": "en",
    "source_record_id": "mock-local-example-002",
    "display_market": "unknown"
  },
  "unit_payloads": {
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
      "warnings": [
        "dimension_order_missing",
        "market_display_unknown",
        "review_required"
      ],
      "errors": [
        "ambiguous_dimension_format"
      ]
    },
    "package_dimensions_json": null,
    "weight_json": null,
    "package_weight_json": null
  },
  "dynamic_attributes_json": [],
  "missing_field_hints": [
    {
      "path": "dimensions_json.dimension_order",
      "reason": "dimension_order_missing",
      "source_text": "10 x 5 x 3 cm",
      "proposed_action": "set_dimension_order"
    }
  ],
  "ai_warnings_json": [
    {
      "code": "dimension_order_missing",
      "path": "unit_payloads.dimensions_json.dimension_order",
      "message": "The source order is preserved as unknown positions, not assigned to length, width, or height."
    },
    {
      "code": "market_display_unknown",
      "path": "unit_payloads.dimensions_json.display_market",
      "message": "Display market is unknown, so no market-specific display value is approved."
    }
  ],
  "field_diff_json": [
    {
      "path": "dimensions_json.unassigned_dimension_candidates",
      "current_value": null,
      "draft_value": {
        "provided_values": [
          10,
          5,
          3
        ],
        "provided_unit": "cm",
        "source_text": "10 x 5 x 3 cm",
        "source_language": "en",
        "parsed_from_text": true
      },
      "source_text": "10 x 5 x 3 cm",
      "warnings": [
        "dimension_order_missing",
        "market_display_unknown",
        "review_required"
      ],
      "errors": [
        "ambiguous_dimension_format"
      ],
      "proposed_action": "set_dimension_order"
    }
  ],
  "warnings": [
    "dimension_order_missing",
    "market_display_unknown",
    "review_required"
  ],
  "errors": [
    "ambiguous_dimension_format"
  ]
}
```

# 5. Missing value is not zero example

Height is explicitly unknown. The mock adapter keeps `height` missing and does not emit `original_value = 0`.

```json
{
  "adapter_name": "deepseek_mock",
  "adapter_mode": "mock",
  "provider": "deepseek",
  "live_provider_called": false,
  "provider_request_id": null,
  "provider_model": null,
  "draft_review_status": "needs_review",
  "source": {
    "raw_input_text": "Product size: length 10 cm, width 5 cm, height unknown.",
    "raw_input_language": "en",
    "source_record_id": "mock-local-example-003",
    "display_market": "unknown"
  },
  "unit_payloads": {
    "dimensions_json": {
      "unit_group": "length",
      "dimension_order": [
        "length",
        "width"
      ],
      "dimension_format": "l_w_partial",
      "source_text": "Product size: length 10 cm, width 5 cm, height unknown.",
      "source_language": "en",
      "parsed_from_text": true,
      "display_market": "unknown",
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
        "display_market": "unknown",
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Product size: length 10 cm, width 5 cm, height unknown.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "market_display_unknown",
          "precision_loss_warning",
          "review_required"
        ],
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
        "display_market": "unknown",
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Product size: length 10 cm, width 5 cm, height unknown.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "market_display_unknown",
          "precision_loss_warning",
          "review_required"
        ],
        "errors": []
      },
      "warnings": [
        "missing_value",
        "market_display_unknown",
        "precision_loss_warning",
        "review_required"
      ],
      "errors": []
    },
    "package_dimensions_json": null,
    "weight_json": null,
    "package_weight_json": null
  },
  "dynamic_attributes_json": [],
  "missing_field_hints": [
    {
      "path": "dimensions_json.height",
      "reason": "missing_value",
      "source_text": "Product size: length 10 cm, width 5 cm, height unknown.",
      "proposed_action": "request_review"
    }
  ],
  "ai_warnings_json": [
    {
      "code": "missing_value",
      "path": "unit_payloads.dimensions_json.height",
      "message": "The source says height is unknown, so no numeric height is emitted."
    },
    {
      "code": "market_display_unknown",
      "path": "unit_payloads.dimensions_json.display_market",
      "message": "Unknown display market falls back to metric display without approving the value."
    }
  ],
  "field_diff_json": [],
  "warnings": [
    "missing_value",
    "market_display_unknown",
    "precision_loss_warning",
    "review_required"
  ],
  "errors": []
}
```

# 6. Unsupported unit error example

The source unit `stone` is preserved as evidence and returns errors. The mock adapter does not convert it to kilograms, pounds, or zero.

```json
{
  "adapter_name": "deepseek_mock",
  "adapter_mode": "mock",
  "provider": "deepseek",
  "live_provider_called": false,
  "provider_request_id": null,
  "provider_model": null,
  "draft_review_status": "needs_review",
  "source": {
    "raw_input_text": "Net weight: 10 stone.",
    "raw_input_language": "en",
    "source_record_id": "mock-local-example-004",
    "display_market": "UK"
  },
  "unit_payloads": {
    "dimensions_json": null,
    "package_dimensions_json": null,
    "weight_json": {
      "unit_group": "weight",
      "source_text": "Net weight: 10 stone.",
      "source_language": "en",
      "parsed_from_text": true,
      "display_market": "UK",
      "review_status": "needs_review",
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
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "conversion_not_possible",
        "source_text": "Net weight: 10 stone.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "market_display_unknown",
          "review_required"
        ],
        "errors": [
          "unsupported_unit",
          "conversion_not_possible"
        ]
      },
      "warnings": [
        "market_display_unknown",
        "review_required"
      ],
      "errors": [
        "unsupported_unit",
        "conversion_not_possible"
      ]
    },
    "package_weight_json": null
  },
  "dynamic_attributes_json": [],
  "missing_field_hints": [],
  "ai_warnings_json": [
    {
      "code": "market_display_unknown",
      "path": "unit_payloads.weight_json.display_market",
      "message": "UK display behavior is mixed unless reviewed context is explicit."
    }
  ],
  "field_diff_json": [],
  "warnings": [
    "market_display_unknown",
    "review_required"
  ],
  "errors": [
    "unsupported_unit",
    "conversion_not_possible"
  ]
}
```

# 7. Generic weight ambiguity example

The source has a numeric weight and supported unit, but it does not identify net, gross, package, or shipping context. The mock adapter does not silently write `weight_json.net_weight`.

```json
{
  "adapter_name": "deepseek_mock",
  "adapter_mode": "mock",
  "provider": "deepseek",
  "live_provider_called": false,
  "provider_request_id": null,
  "provider_model": null,
  "draft_review_status": "needs_review",
  "source": {
    "raw_input_text": "weight: 2 lb",
    "raw_input_language": "en",
    "source_record_id": "mock-local-example-005",
    "display_market": "US"
  },
  "unit_payloads": {
    "dimensions_json": null,
    "package_dimensions_json": null,
    "weight_json": {
      "unit_group": "weight",
      "source_text": "weight: 2 lb",
      "source_language": "en",
      "parsed_from_text": true,
      "display_market": "US",
      "review_status": "needs_review",
      "warnings": [
        "net_vs_gross_weight_ambiguous",
        "review_required"
      ],
      "errors": []
    },
    "package_weight_json": null
  },
  "dynamic_attributes_json": [],
  "missing_field_hints": [
    {
      "path": "weight_json.net_weight",
      "reason": "net_vs_gross_weight_ambiguous",
      "source_text": "weight: 2 lb",
      "proposed_action": "request_review"
    },
    {
      "path": "package_weight_json.package_weight",
      "reason": "review_required",
      "source_text": "weight: 2 lb",
      "proposed_action": "request_review"
    }
  ],
  "ai_warnings_json": [
    {
      "code": "net_vs_gross_weight_ambiguous",
      "path": "unit_payloads.weight_json",
      "message": "The source does not state whether the weight is net, gross, package, or shipping weight."
    }
  ],
  "field_diff_json": [
    {
      "path": "weight_json.unassigned_weight_candidate",
      "current_value": null,
      "draft_value": {
        "candidate_value": 2,
        "candidate_unit": "lb",
        "source_text": "weight: 2 lb",
        "source_language": "en",
        "parsed_from_text": true
      },
      "source_text": "weight: 2 lb",
      "warnings": [
        "net_vs_gross_weight_ambiguous",
        "review_required"
      ],
      "errors": [],
      "proposed_action": "request_review"
    }
  ],
  "warnings": [
    "net_vs_gross_weight_ambiguous",
    "review_required"
  ],
  "errors": []
}
```

# 8. AI draft does not overwrite reviewed values

This example shows a draft candidate compared against an existing reviewed value. `field_diff_json.current_value` is read-only comparison metadata. The mock output does not mark the draft as reviewed or reviewer-corrected.

```json
{
  "adapter_name": "deepseek_mock",
  "adapter_mode": "mock",
  "provider": "deepseek",
  "live_provider_called": false,
  "provider_request_id": null,
  "provider_model": null,
  "draft_review_status": "needs_review",
  "source": {
    "raw_input_text": "Net weight: 1.0 kg.",
    "raw_input_language": "en",
    "source_record_id": "mock-local-example-006",
    "display_market": "US"
  },
  "unit_payloads": {
    "dimensions_json": null,
    "package_dimensions_json": null,
    "weight_json": {
      "unit_group": "weight",
      "source_text": "Net weight: 1.0 kg.",
      "source_language": "en",
      "parsed_from_text": true,
      "display_market": "US",
      "review_status": "needs_review",
      "net_weight": {
        "value_kind": "weight",
        "original_value": 1,
        "original_unit": "kg",
        "normalized_metric_value": 1,
        "normalized_metric_unit": "kg",
        "normalized_imperial_value": 2.2,
        "normalized_imperial_unit": "lb",
        "display_value": 2.2,
        "display_unit": "lb",
        "display_market": "US",
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Net weight: 1.0 kg.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "precision_loss_warning",
          "review_required"
        ],
        "errors": []
      },
      "warnings": [
        "precision_loss_warning",
        "review_required"
      ],
      "errors": []
    },
    "package_weight_json": null
  },
  "dynamic_attributes_json": [],
  "missing_field_hints": [],
  "ai_warnings_json": [
    {
      "code": "review_required",
      "path": "field_diff_json.weight_json.net_weight",
      "message": "The draft differs from a reviewed value and must not be applied automatically."
    }
  ],
  "field_diff_json": [
    {
      "path": "weight_json.net_weight",
      "current_value": {
        "value_kind": "weight",
        "original_value": 1.1,
        "original_unit": "kg",
        "review_status": "reviewed",
        "reviewer_corrected": false
      },
      "draft_value": {
        "value_kind": "weight",
        "original_value": 1,
        "original_unit": "kg",
        "display_value": 2.2,
        "display_unit": "lb",
        "review_status": "needs_review",
        "reviewer_corrected": false
      },
      "source_text": "Net weight: 1.0 kg.",
      "warnings": [
        "precision_loss_warning",
        "review_required"
      ],
      "errors": [],
      "proposed_action": "request_review"
    }
  ],
  "warnings": [
    "precision_loss_warning",
    "review_required"
  ],
  "errors": []
}
```

# 9. Future volume and temperature fields

Future volume and temperature payloads remain draft-only K09B contract examples. They do not create DB fields, runtime behavior, API routes, UI state, or live provider calls.

```json
{
  "adapter_name": "deepseek_mock",
  "adapter_mode": "mock",
  "provider": "deepseek",
  "live_provider_called": false,
  "provider_request_id": null,
  "provider_model": null,
  "draft_review_status": "needs_review",
  "source": {
    "raw_input_text": "Capacity: 750 ml. Operating temperature: -10 C to 45 C.",
    "raw_input_language": "en",
    "source_record_id": "mock-local-example-007",
    "display_market": "US"
  },
  "unit_payloads": {
    "dimensions_json": null,
    "package_dimensions_json": null,
    "weight_json": null,
    "package_weight_json": null,
    "volume_payload": {
      "contract_status": "future_only",
      "unit_group": "volume",
      "supported_units": [
        "ml",
        "l",
        "fl_oz"
      ],
      "source_text": "Capacity: 750 ml.",
      "source_language": "en",
      "parsed_from_text": true,
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
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Capacity: 750 ml.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "precision_loss_warning",
          "review_required"
        ],
        "errors": []
      },
      "warnings": [
        "precision_loss_warning",
        "review_required"
      ],
      "errors": []
    },
    "temperature_payload": {
      "contract_status": "future_only",
      "unit_group": "temperature",
      "supported_units": [
        "c",
        "f"
      ],
      "temperature_context": "operating",
      "source_text": "Operating temperature: -10 C to 45 C.",
      "source_language": "en",
      "parsed_from_text": true,
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
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Operating temperature: -10 C to 45 C.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "review_required"
        ],
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
        "conversion_source": "ai_structured_from_provided_input",
        "conversion_precision": "2_decimal_places",
        "source_text": "Operating temperature: -10 C to 45 C.",
        "source_language": "en",
        "parsed_from_text": true,
        "review_status": "needs_review",
        "reviewer_corrected": false,
        "warnings": [
          "review_required"
        ],
        "errors": []
      },
      "warnings": [
        "review_required"
      ],
      "errors": []
    }
  },
  "dynamic_attributes_json": [],
  "missing_field_hints": [],
  "ai_warnings_json": [
    {
      "code": "precision_loss_warning",
      "path": "unit_payloads.volume_payload.capacity",
      "message": "Fluid ounce display value is rounded to two decimal places."
    },
    {
      "code": "review_required",
      "path": "unit_payloads.temperature_payload",
      "message": "Future temperature payloads are draft-only and require human review."
    }
  ],
  "field_diff_json": [],
  "warnings": [
    "precision_loss_warning",
    "review_required"
  ],
  "errors": []
}
```

# 10. Non-integration note

These examples are contract examples only. They do not approve backend runtime integration, frontend integration, router registration, service create/update behavior, DB writes, operation log writes, n8n draft lane consumption, P-series workflow consumption, live DeepSeek credentials, or live DeepSeek calls.
