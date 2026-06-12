# K10 DeepSeek Mock Adapter Output Rules

Status: K10A docs-only mock adapter output rules.

Date: 2026-06-12.

# 1. K10A scope

K10A defines the DeepSeek mock adapter output contract for K Product Knowledge unit fields.

K10A is documentation only:

- No Python code.
- No runtime wiring.
- No backend service or router registration.
- No frontend changes.
- No tests or migration changes.
- No live DeepSeek call.
- No n8n draft lane change.
- No P-series workflow JSON read or write.
- No commit.

The K10 mock adapter output described here is a future contract. It does not approve runtime integration.

# 2. Source materials

This contract is based on:

- K08 field system and AI/human review policy.
- K08B unit field clarification.
- K09A storage and display baseline.
- K09B unit payload contract.
- K09C `unit_conversion.py` behavior.
- K09E `unit_payloads.py` behavior.
- K09D/K09E unit helper tests.
- K09G K07 unit input design.
- K09H K10 AI unit output rules and mapping.

# 3. Hard boundaries

The mock adapter must not:

- Call live DeepSeek or any live provider.
- Read provider credentials, env vars, secrets, headers, cookies, API keys, or tokens.
- Write to DB.
- Write to backend runtime state.
- Register a FastAPI router.
- Modify `main.py`.
- Import or depend on frontend runtime.
- Modify frontend state.
- Modify migrations.
- Modify tests.
- Call Docker, Alembic, Postgres, staging, or production.
- Call n8n.
- Read or modify P-series workflow JSON.
- Promote any value to reviewed, approved, canonical, publish-ready, shipping-ready, or reviewer-corrected.

The mock adapter may produce deterministic draft JSON only.

# 4. Input policy

Allowed input references for the mock output contract:

- `raw_input_text`
- `raw_input_language`
- `raw_input_payload_json`
- supplier text or supplier payload copied into an approved local input object
- operator notes copied into an approved local input object
- manual `source_text`
- future visual extraction notes, draft only
- display or target market supplied as local request context

The mock adapter must preserve source metadata. If source text is not provided, it must not invent it.

The mock adapter must not treat a product title, category, image, marketplace convention, or prior product as evidence for a missing unit fact.

# 5. Top-level JSON contract shape

The mock adapter output should use one deterministic top-level envelope:

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
    "raw_input_text": null,
    "raw_input_language": "unknown",
    "source_record_id": null,
    "display_market": "unknown"
  },
  "unit_payloads": {
    "dimensions_json": null,
    "package_dimensions_json": null,
    "weight_json": null,
    "package_weight_json": null
  },
  "dynamic_attributes_json": [],
  "missing_field_hints": [],
  "ai_warnings_json": [],
  "field_diff_json": [],
  "warnings": [
    "review_required"
  ],
  "errors": []
}
```

Envelope rules:

- `adapter_mode` must be `mock`.
- `live_provider_called` must be `false`.
- `provider_request_id` and `provider_model` must be `null` in K10 mock output.
- `draft_review_status` must be `draft` or `needs_review`; `needs_review` is recommended for any unit-bearing output.
- `unit_payloads` may include only K09-shaped unit payloads.
- `dynamic_attributes_json` may include unit-bearing dynamic attributes only when the source provides explicit numeric value and unit.
- `missing_field_hints` are review hints, not facts.
- `ai_warnings_json` and `field_diff_json` are draft review support, not canonical writes.

# 6. Unit Value Payload contract

Whenever the mock adapter emits an individual unit value, the object must follow the K09 Unit Value Payload shape:

```json
{
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
  "source_text": "length 10 cm",
  "source_language": "en",
  "parsed_from_text": true,
  "review_status": "needs_review",
  "reviewer_corrected": false,
  "warnings": [],
  "errors": []
}
```

Unit Value Payload rules:

- `original_value` and `original_unit` must preserve explicit source input.
- `original_value` must not be set to `0` for missing, unknown, not applicable, or ambiguous values.
- `original_unit` must not be replaced by `display_unit`.
- `normalized_metric_*`, `normalized_imperial_*`, and `display_*` are derived suggestions only.
- `conversion_source` for mock AI output must be `ai_structured_from_provided_input`.
- `review_status` must be `draft` or `needs_review`.
- `reviewer_corrected` must be `false`.
- `source_text`, `source_language`, and `parsed_from_text` must be preserved when present.
- Unsupported, missing, invalid, or ambiguous values must carry warnings or errors.

# 7. Supported units

K10 mock output must follow the K09 supported unit set.

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

Future volume:

- `ml`
- `l`
- `fl_oz`

Future temperature:

- `c`
- `f`

Safe aliases may be canonicalized only when K09 helper behavior makes the alias explicit, such as `inch` to `in`, `kilograms` to `kg`, or `litres` to `l`.

Unsupported unit strings must be preserved as source evidence and marked with `unsupported_unit`. The mock adapter must not silently convert an unsupported unit into a supported default.

# 8. AI draft output rules

Allowed:

- Structure explicit numeric value plus explicit supported unit into a draft unit payload.
- Preserve exact source text for review.
- Produce deterministic metric, imperial, and display suggestions when K09 conversion rules allow it.
- Emit missing field hints when a required context appears incomplete.
- Emit warning/error codes when the source is ambiguous or invalid.
- Emit `field_diff_json` candidates when an AI draft differs from current canonical or reviewed values.

Forbidden:

- Guess missing dimensions.
- Guess missing weight.
- Guess package dimensions.
- Guess net weight versus gross weight.
- Guess product weight versus package or shipping weight.
- Guess dimension order from `10 x 5 x 3 cm`.
- Treat unknown or missing as `0`.
- Treat package dimensions as product dimensions.
- Treat product dimensions as package dimensions.
- Treat package or shipping weight as product net weight.
- Use `display_value` or `display_unit` as original source values.
- Output reviewed, approved, canonical, publish-ready, shipping-ready, or reviewer-corrected state.
- Overwrite human-confirmed values.

# 9. Unit payload families

The mock adapter may emit these K09 payload families:

- `dimensions_json`: product body dimensions only.
- `package_dimensions_json`: package or shipping dimensions only.
- `weight_json`: product body weight only.
- `package_weight_json`: package or shipping weight only.
- `dynamic_attributes_json`: unit-bearing category or marketplace attributes, draft only.
- Future volume payloads, draft only.
- Future temperature payloads, draft only.

Product payloads and package payloads must remain separate. A value may be copied from one family to another only after a human reviewer explicitly edits or accepts it in a future review surface.

# 10. Display and conversion rules

Display choice must not rewrite stored original values.

Market defaults follow K09 behavior:

- `US`: imperial display by default.
- `EU`: metric display by default.
- `AU`: metric display by default.
- `fallback`: metric display by default.
- `UK`: mixed; use warning `market_display_unknown` unless reviewed context is explicit.
- `CA`: mixed; use warning `market_display_unknown` unless reviewed context is explicit.
- Unknown markets: metric fallback with `market_display_unknown`.

Conversion rules:

- Convert only when `original_value` is valid numeric and `original_unit` is supported for `value_kind`.
- Cross-group conversion must fail with `conversion_not_possible`.
- Missing values, missing units, invalid numbers, and unsupported units must not produce display values.
- `conversion_precision` should be `2_decimal_places` for normal mock output unless conversion is blocked.
- If conversion is blocked, `conversion_precision` should be `conversion_not_possible`.

# 11. Error policy

Errors are blocking for downstream use of the affected field. K10 mock output still remains draft and must not decide final downstream blocking behavior.

Required error codes:

| Code | When to use |
| --- | --- |
| `missing_value` | Unit or field context exists but no numeric value is provided. |
| `missing_unit` | Numeric value exists but unit is missing. |
| `unsupported_unit` | Source unit is outside the K09 supported unit set. |
| `invalid_numeric_value` | Value cannot be represented safely as numeric. |
| `ambiguous_dimension_format` | Dimension order or separators are ambiguous. |
| `product_vs_package_conflict` | Product and package/shipping contexts are mixed. |
| `net_vs_gross_weight_ambiguous` | Weight source does not identify net, gross, package, or shipping context. |
| `ai_guessing_forbidden` | Producing the value would require AI invention or inference. |
| `conversion_not_possible` | Value, unit, group, or rule prevents deterministic conversion. |
| `original_value_missing` | Normalized or display values exist without preserved original value. |
| `dimension_value_missing` | K09E payload-level validation found no dimension value. |
| `weight_value_missing` | K09E payload-level validation found no weight value. |

`dimension_value_missing` and `weight_value_missing` are K09E helper-level payload validation errors. They should appear at payload level or validation-report level, not as replacements for Unit Value Payload errors.

# 12. Warning policy

Warnings preserve review context. They do not approve values.

Required warning codes:

| Code | When to use |
| --- | --- |
| `review_required` | All AI unit output suggestions. |
| `precision_loss_warning` | Conversion or rounding may overstate source precision. |
| `market_display_unknown` | Display market cannot be resolved or is mixed. |
| `display_market_missing` | Intended use needs display market but none is supplied. |
| `dimension_order_missing` | Multiple dimension values exist but order metadata is absent. |
| `optional_field_missing` | Optional field is absent and useful for review context. |
| `free_text_parsing_not_supported` | Source text cannot be safely parsed inside the K09/K10 mock boundary. |

Warnings may still block publishing, shipping, Woo draft, or product fact use when the downstream context requires reviewed values.

# 13. Field diff policy

AI differences must be written as draft review metadata, not as canonical updates.

Each `field_diff_json` item should include:

- `path`: K09 payload path, such as `dimensions_json.length`.
- `current_value`: current canonical or reviewed value when available.
- `draft_value`: AI draft candidate.
- `source_text`: source evidence.
- `warnings`: warning codes related to this diff.
- `errors`: error codes related to this diff.
- `proposed_action`: one of `accept`, `edit`, `reject`, `request_review`, `set_dimension_order`, `move_to_package_payload`, or `move_to_product_payload`.

The mock adapter must not apply the diff.

# 14. Human review policy

All AI unit output requires human review before publish-facing, shipping-facing, Woo draft, product-claim, or downstream API use.

Allowed human actions in a future review surface:

- Accept: human intentionally moves the draft into reviewed state.
- Edit: human writes a corrected value; corrected value wins.
- Reject: draft must not be used downstream.
- Mark not applicable: field is explicitly not applicable and must not be represented as `0`.
- Request review: ambiguity or conflict remains unresolved.

The mock adapter cannot perform any of these actions. It can only prepare draft candidates and review metadata.

# 15. No direct integration approval

K10 mock adapter output rules do not approve:

- Backend runtime integration.
- Frontend integration.
- Router registration.
- Service create/update behavior changes.
- DB writes.
- Migration changes.
- Operation log writes.
- n8n consumption.
- P-series consumption.
- Live DeepSeek adapter behavior.

Any future runtime, backend, frontend, n8n, P-series, provider credential, or live DeepSeek work requires a separate owner-approved task.
