# K04 Unit And Market Conversion Model

Status: K04 unit and market conversion draft, pending owner review.

Date: 2026-06-11.

## 1. 目标

This document designs how K Product Knowledge should represent dimensions, weight, units, and target-market display rules.

Goals:

- preserve original operator or supplier input;
- normalize units for predictable search, validation, and downstream generation;
- support target-market display without losing source values;
- prevent AI from guessing missing dimensions or weights.

## 2. 支持单位

Length:

- `mm`
- `cm`
- `m`
- `in`
- `ft`

Weight:

- `g`
- `kg`
- `oz`
- `lb`

Optional volume:

- `ml`
- `l`
- `fl_oz`

Optional temperature:

- `c`
- `f`

## 3. 存储原则

Every structured unit payload should preserve:

- `original_value`
- `original_unit`
- `normalized_metric_value`
- `normalized_metric_unit`
- `normalized_imperial_value`
- `normalized_imperial_unit`
- `display_market`
- `conversion_source`
- `conversion_precision`

Recommended conversion source values:

- `operator_entered`
- `supplier_imported`
- `system_converted`
- `reviewer_corrected`
- `unknown`

Recommended precision rule:

- Keep raw input exactly in `original_value` and `original_unit`.
- Store normalized values as numeric values with explicit units.
- Record rounding or precision in `conversion_precision`.
- Do not silently change a human-confirmed original value.

## 4. 目标市场显示规则

Market defaults:

- US: default display is imperial.
- UK: mixed display; weight may be metric, and some length fields may be imperial or metric depending on product context.
- EU: default display is metric.
- AU: default display is metric.
- CA: mixed display.
- Fallback: metric.

Recommended market codes:

- `US`
- `UK`
- `EU`
- `AU`
- `CA`
- `fallback`

Display rules should be data-driven in future runtime. K04 only defines the storage shape and review expectations.

## 5. 数据库表示

### `dimensions_json` example

```json
{
  "display_market": "US",
  "unit_family": "length",
  "values": {
    "length": {
      "original_value": 30,
      "original_unit": "cm",
      "normalized_metric_value": 30,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 11.81,
      "normalized_imperial_unit": "in",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places"
    },
    "width": {
      "original_value": 20,
      "original_unit": "cm",
      "normalized_metric_value": 20,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 7.87,
      "normalized_imperial_unit": "in",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places"
    },
    "height": {
      "original_value": 10,
      "original_unit": "cm",
      "normalized_metric_value": 10,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 3.94,
      "normalized_imperial_unit": "in",
      "conversion_source": "system_converted",
      "conversion_precision": "2_decimal_places"
    }
  },
  "review_status": "needs_review"
}
```

### `weight_json` example

```json
{
  "display_market": "US",
  "unit_family": "weight",
  "value": {
    "original_value": 1.2,
    "original_unit": "kg",
    "normalized_metric_value": 1.2,
    "normalized_metric_unit": "kg",
    "normalized_imperial_value": 2.65,
    "normalized_imperial_unit": "lb",
    "conversion_source": "system_converted",
    "conversion_precision": "2_decimal_places"
  },
  "review_status": "needs_review"
}
```

### `package_dimensions_json` example

```json
{
  "display_market": "EU",
  "unit_family": "length",
  "values": {
    "length": {
      "original_value": 42,
      "original_unit": "cm",
      "normalized_metric_value": 42,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 16.54,
      "normalized_imperial_unit": "in",
      "conversion_source": "supplier_imported",
      "conversion_precision": "2_decimal_places"
    },
    "width": {
      "original_value": 25,
      "original_unit": "cm",
      "normalized_metric_value": 25,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 9.84,
      "normalized_imperial_unit": "in",
      "conversion_source": "supplier_imported",
      "conversion_precision": "2_decimal_places"
    },
    "height": {
      "original_value": 14,
      "original_unit": "cm",
      "normalized_metric_value": 14,
      "normalized_metric_unit": "cm",
      "normalized_imperial_value": 5.51,
      "normalized_imperial_unit": "in",
      "conversion_source": "supplier_imported",
      "conversion_precision": "2_decimal_places"
    }
  },
  "review_status": "reviewed"
}
```

### `package_weight_json` example

```json
{
  "display_market": "EU",
  "unit_family": "weight",
  "value": {
    "original_value": 1450,
    "original_unit": "g",
    "normalized_metric_value": 1.45,
    "normalized_metric_unit": "kg",
    "normalized_imperial_value": 3.2,
    "normalized_imperial_unit": "lb",
    "conversion_source": "supplier_imported",
    "conversion_precision": "2_decimal_places"
  },
  "review_status": "reviewed"
}
```

## 6. 不允许事项

- Do not store only one free-text size field.
- Do not lose the original input unit.
- Do not let AI guess missing dimensions or weight.
- Do not silently change human-confirmed numbers.
- Do not mix metric and imperial values without explicit unit labels.
- Do not use dimensions or weights for WooCommerce draft or publish output until required values are reviewed.
