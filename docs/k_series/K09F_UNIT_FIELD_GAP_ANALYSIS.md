# K09F Unit Field Gap Analysis

Status: K09F docs-only gap analysis, pending owner review.

Date: 2026-06-12.

# 1. Gap analysis scope

This file only analyzes field gaps found after K09A-E.

- It does not change K08 fields.
- It does not add product-table columns.
- It does not change K09 Python code.
- It does not change tests.
- It does not create migrations.
- It does not connect runtime, DB, API, frontend, staging, production, or live services.

# 2. Unit payload fields introduced by K09

## Unit Value Payload

- `value_kind`
- `original_value`
- `original_unit`
- `normalized_metric_value`
- `normalized_metric_unit`
- `normalized_imperial_value`
- `normalized_imperial_unit`
- `display_value`
- `display_unit`
- `display_market`
- `conversion_source`
- `conversion_precision`
- `source_text`
- `source_language`
- `parsed_from_text`
- `review_status`
- `reviewer_corrected`
- `warnings`
- `errors`

## Dimensions payload

- `unit_group`
- `length`
- `width`
- `height`
- `diameter`
- `thickness`
- `dimension_order`
- `dimension_format`
- `source_text`
- `source_language`
- `parsed_from_text`
- `display_market`
- `review_status`
- `warnings`
- `errors`

## Package dimensions payload

- `package_unit_group`
- `package_length`
- `package_width`
- `package_height`
- `package_diameter`
- `package_dimension_order`
- `package_dimension_format`
- `package_source_text`
- `source_language`
- `parsed_from_text`
- `display_market`
- `review_status`
- `warnings`
- `errors`

## Weight payload

- `unit_group`
- `net_weight`
- `gross_weight`
- `source_text`
- `source_language`
- `parsed_from_text`
- `display_market`
- `review_status`
- `warnings`
- `errors`

## Package weight payload

- `unit_group`
- `package_weight`
- `shipping_weight`
- `source_text`
- `source_language`
- `parsed_from_text`
- `display_market`
- `review_status`
- `warnings`
- `errors`

# 3. Product table vs JSON payload distinction

- K09 fields are mostly nested JSON payload fields inside existing K08 fields.
- K09F does not recommend adding all nested unit payload fields as product-table columns.
- `dimensions_json` / `package_dimensions_json` / `weight_json` / `package_weight_json` remain the product-level canonical fields.
- Nested payload fields are contract-level fields inside those JSON payloads.
- No migration change is recommended in K09F.

The practical interpretation is:

- Product-table schema should keep the K08 top-level JSON field model.
- K09 Unit Value Payload fields should be treated as JSON contract fields for validators, UI forms, AI adapter output constraints, and future API payload documentation.
- K09F does not recommend denormalizing `length`, `net_weight`, `display_value`, `conversion_precision`, `warnings`, or `errors` into separate product-table columns.

# 4. Potential K08B clarifications

- K08 field dictionary should treat nested payload fields as examples / contract links, not as new products-table columns.
- K08 readiness gates should explicitly state that unit payload `errors` block downstream gates that rely on those values, especially Woo draft, publish review, shipping display, and content claims involving dimensions or weight.
- K08 AI/human review policy should add: AI may structure provided unit values but cannot infer missing dimensions or net/gross/package distinction.
- K08 downstream mapping should mention the K09 `unit_payloads.py` helper as a module-local helper and future contract reference, without implying runtime integration is already approved.
- K08 required/optional matrix should clarify product dimensions vs package dimensions separate gate behavior, and product weight vs package/shipping weight separate gate behavior.

# 5. Gap severity table

| Gap | Severity | Impact | Recommended action | Immediate blocker? |
| --- | --- | --- | --- | --- |
| K08 does not enumerate nested Unit Value Payload fields. | low | Reviewers may not know where `display_value`, `conversion_precision`, or `reviewer_corrected` live. | K08B should link K08 top-level JSON fields to K09B contract examples. | no |
| K08 does not explicitly state all nested payload fields are not product-table columns. | low | Future implementers could over-normalize JSON contract fields into migration scope. | K08B should add product-table vs JSON contract wording. | no |
| Product dimensions and package dimensions are separate in K08, but gate behavior is not detailed. | low | A downstream task may incorrectly accept package dimensions as product dimensions. | K08B should clarify separate gate behavior. | no |
| Product weight and package/shipping weight are separate, but net/gross ambiguity is not explicit in K08. | medium | Shipping or product fact claims could use ambiguous `weight: 2 lb` incorrectly. | K08B should document `net_vs_gross_weight_ambiguous` review behavior. | no |
| K08 readiness gates do not explicitly say unit payload errors block dependent downstream gates. | medium | A future Woo draft or content gate could ignore nested payload errors. | K08B should add unit payload error gate policy. | no |
| K08 AI policy forbids guessing, but does not name net/gross/package distinction. | medium | AI adapter rules could structure explicit values but infer the wrong weight context. | K08B should add the unit-specific no-inference sentence. | no |
| K08 does not define K09C/E no free-text parser boundary. | medium | A future helper integration might expect `source_text` to be parsed automatically. | K08B should state K09 helpers preserve source text but do not parse free text without a separately approved parser task. | no |
| `display_market` vs `target_market` relationship exists but is split across K08/K09 docs. | low | UI/API docs may conflate request market and payload display market. | K08B should define display precedence at documentation level only. | no |
| Future volume and temperature contracts are only in K09 docs. | low | Category-specific unit fields may miss contract references. | K08B can reference future-only payloads under dynamic attributes. | no |
| K09E helper is not mentioned by K08 downstream mapping. | low | Future K09I planning may miss the already-created contract helper. | K08B can mention it as a future candidate helper, not an approved runtime dependency. | no |
