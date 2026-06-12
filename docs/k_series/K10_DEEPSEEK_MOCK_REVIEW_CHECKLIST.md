# K10 DeepSeek Mock Review Checklist

Status: K10A docs-only review checklist.

Date: 2026-06-12.

# 1. Scope checklist

- [ ] Only docs were created or changed.
- [ ] No Python files were created or changed.
- [ ] No backend runtime files were changed.
- [ ] No frontend files were changed.
- [ ] No tests were changed.
- [ ] No migrations were created or changed.
- [ ] No router was registered.
- [ ] No `main.py` change was made.
- [ ] No env file was read.
- [ ] No Docker, Alembic, Postgres, staging, or production command was run.
- [ ] No live DeepSeek or live provider was called.
- [ ] No n8n draft lane file was read or changed.
- [ ] No P-series workflow JSON was read or changed.
- [ ] No commit was made.

# 2. Required files

- [ ] `docs/k_series/K10_DEEPSEEK_MOCK_ADAPTER_OUTPUT_RULES.md` exists.
- [ ] `docs/k_series/K10_DEEPSEEK_MOCK_MAPPING.md` exists.
- [ ] `docs/k_series/K10_DEEPSEEK_MOCK_REVIEW_CHECKLIST.md` exists.

# 3. Adapter boundary checks

- [ ] The docs state K10 mock output is deterministic draft JSON only.
- [ ] The docs state `adapter_mode = mock`.
- [ ] The docs state `live_provider_called = false`.
- [ ] The docs prohibit provider credentials, env reads, provider request IDs, and live model calls.
- [ ] The docs prohibit DB writes.
- [ ] The docs prohibit backend runtime integration.
- [ ] The docs prohibit frontend integration.
- [ ] The docs prohibit n8n and P-series direct consumption.

# 4. AI draft status checks

- [ ] AI unit payloads are limited to `draft` or `needs_review`.
- [ ] AI unit payloads cannot output `reviewed`.
- [ ] AI unit payloads cannot output `approved`.
- [ ] AI unit payloads cannot output `reviewer_corrected`.
- [ ] AI unit payloads cannot output publish-ready or shipping-ready facts.
- [ ] `reviewer_corrected` is always `false` for mock output.
- [ ] `conversion_source` for AI unit values is `ai_structured_from_provided_input`.
- [ ] `review_required` is included for AI unit suggestions.

# 5. Source preservation checks

- [ ] `source_text` is preserved when provided.
- [ ] `source_language` is preserved or set to `unknown`.
- [ ] `parsed_from_text` is present when output came from source text.
- [ ] Missing source text is not fabricated.
- [ ] Raw input is not treated as reviewed fact.
- [ ] Visual or free-text extraction notes remain draft-only.

# 6. Unit contract checks

- [ ] Unit Value Payload shape includes all K09 required fields.
- [ ] `original_value` preserves explicit source number.
- [ ] `original_unit` preserves explicit source unit.
- [ ] Missing values are not represented as `0`.
- [ ] Unknown values are not represented as `0`.
- [ ] `display_value` does not overwrite `original_value`.
- [ ] `display_unit` does not overwrite `original_unit`.
- [ ] Metric and imperial values are derived only when conversion is possible.
- [ ] Conversion failures keep derived/display values `null`.

# 7. Supported unit checks

- [ ] Length units are limited to `mm`, `cm`, `m`, `in`, `ft`.
- [ ] Weight units are limited to `g`, `kg`, `oz`, `lb`.
- [ ] Future volume units are limited to `ml`, `l`, `fl_oz`.
- [ ] Future temperature units are limited to `c`, `f`.
- [ ] Safe aliases are canonicalized only when K09 helper behavior explicitly supports them.
- [ ] Unsupported units produce `unsupported_unit`.
- [ ] Unsupported units are not silently converted into default units.

# 8. Product/package separation checks

- [ ] Product dimensions map only to `dimensions_json`.
- [ ] Package dimensions map only to `package_dimensions_json`.
- [ ] Product weight maps only to `weight_json`.
- [ ] Package/shipping weight maps only to `package_weight_json`.
- [ ] Product dimensions are not copied to package dimensions.
- [ ] Package dimensions are not copied to product dimensions.
- [ ] Package or shipping weight is not copied to product net weight.
- [ ] Mixed product/package language produces `product_vs_package_conflict` or review metadata.

# 9. Ambiguity checks

- [ ] `10 x 5 x 3 cm` without labels does not become L/W/H.
- [ ] Missing dimension order produces `dimension_order_missing`.
- [ ] Ambiguous dimension format produces `ambiguous_dimension_format`.
- [ ] Generic `weight: 2 lb` does not become `net_weight`.
- [ ] Generic weight produces `net_vs_gross_weight_ambiguous`.
- [ ] Free-text-only source that cannot be safely parsed produces `free_text_parsing_not_supported`.
- [ ] AI invention produces or would require `ai_guessing_forbidden`.

# 10. Error and warning checks

- [ ] `missing_value` is used when a unit or field context exists without a numeric value.
- [ ] `missing_unit` is used when numeric value exists without unit.
- [ ] `unsupported_unit` is used for unsupported units.
- [ ] `invalid_numeric_value` is used for nonnumeric unsafe values.
- [ ] `conversion_not_possible` is used when deterministic conversion cannot run.
- [ ] `original_value_missing` is used when derived values exist without source value.
- [ ] `dimension_value_missing` is documented as K09E payload-level validation.
- [ ] `weight_value_missing` is documented as K09E payload-level validation.
- [ ] `market_display_unknown` is used for unresolved or mixed display market.
- [ ] `display_market_missing` is used when intended use requires a display market.
- [ ] `precision_loss_warning` is used when rounding may overstate precision.

# 11. Human review checks

- [ ] Human review is required before publish-facing use.
- [ ] Human review is required before shipping-facing use.
- [ ] Human review is required before Woo draft use.
- [ ] Human review is required before dimensions/weight claims.
- [ ] Accept/edit/reject are described as human actions, not adapter actions.
- [ ] Human edits win over AI draft.
- [ ] Human correction is the only path to `reviewer_corrected`.
- [ ] `field_diff_json` records draft differences without applying them.
- [ ] `missing_field_hints` are review hints only.

# 12. Mapping completeness checks

- [ ] Product dimensions mapping covers length, width, height, diameter, thickness, order, format, source text.
- [ ] Package dimensions mapping covers package length, width, height, diameter, order, format, source text.
- [ ] Product weight mapping covers net weight, gross weight, generic weight ambiguity.
- [ ] Package weight mapping covers package weight, shipping weight, product/package ambiguity.
- [ ] Dynamic unit attributes are draft-only and cannot bypass K09 payload separation.
- [ ] Future volume mapping is draft-only and does not imply runtime or DB changes.
- [ ] Future temperature mapping is draft-only and requires explicit context.

# 13. Final local verification

Run these before handoff:

```bash
pwd
git branch --show-current
git rev-parse HEAD
git status --short --untracked-files=all
git diff --name-only
git diff --check
```

Expected handoff state:

- Only the three K10A docs files are untracked.
- `git diff --name-only` is empty because the files are untracked.
- `git diff --check` reports no tracked whitespace errors.
- No commit exists for K10A.
