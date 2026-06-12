# K09 Storage And Display Rules

Status: K09A storage and display baseline, pending owner review.

Date: 2026-06-12.

# 1. Storage model rules

Structured unit payload means a JSON-compatible unit payload that preserves source input and stores normalized values for predictable validation, display, search, and downstream draft generation.

The payload concept includes:

- original values: exact values supplied by operator, supplier, approved import, or reviewed source material.
- normalized metric values: system-converted metric values with explicit metric units.
- normalized imperial values: system-converted imperial values with explicit imperial units.
- display market: market context used to choose display unit family.
- conversion source: source of the value or conversion, such as `operator_entered`, `supplier_imported`, `system_converted`, `reviewer_corrected`, or `unknown`.
- conversion precision: explicit rounding and precision metadata.
- review status: lifecycle state showing whether the unit payload is draft, needs review, reviewed, approved, blocked, or archived.

Storage rules:

- Display choice must not rewrite stored original values.
- `original_value` and `original_unit` must stay available for review and reconciliation.
- Normalized values are derived values and do not replace source values.
- Missing values stay missing until supplied by an operator, supplier, approved import, or reviewer.
- `unknown` is not numeric zero.

# 2. Market display defaults

- US: imperial by default.
- UK: mixed; weight may be metric, selected length fields may be metric or imperial by context.
- EU: metric by default.
- AU: metric by default.
- CA: mixed.
- fallback: metric.

Display choice must not rewrite stored original values.

Display market may come from product/workspace/default request context.

`target_market` is readiness/request context, not required products-table column in K09A.

K09A does not implement runtime storage.

# 3. Rounding / precision rules

- keep original input exact.
- conversion should use explicit precision.
- do not overstate precision.

Default suggested precision:

- length metric: 2 decimals unless small unit `mm`.
- length imperial: 2 decimals.
- weight metric: 2 decimals for `kg`, integer or 1 decimal for `g` depending source.
- weight imperial: 2 decimals for `lb`/`oz`.

Future K09C may refine these rules.

# 4. Error / warning categories

- `unsupported_unit`: unit is not in the K09 supported unit set.
- `missing_unit`: value exists but unit is missing.
- `missing_value`: unit exists but numeric value is missing.
- `invalid_numeric_value`: value is not numeric or cannot be represented safely.
- `ambiguous_dimension_format`: source text has ambiguous dimension order or separators.
- `ai_guessing_forbidden`: AI attempted to invent dimensions, weight, volume, package dimensions, or temperature.
- `precision_loss_warning`: conversion or rounding may lose source precision.
- `market_display_unknown`: display market cannot be resolved.
- `original_value_missing`: normalized or display values exist but source value is absent.
- `conversion_not_possible`: conversion cannot be produced because value, unit, or conversion rule is unavailable.

# 5. Human review rules

- dimensions and weight require human review before publish.
- AI can structure provided values but cannot invent values.
- `reviewer_corrected` source overrides system conversion.
- `field_diff_json` can record conversion disagreements.
- future K21 operation logs may record corrections, but K09A does not modify `operation_logs`.
