# 1. Review policy

- AI unit output is always `draft` / `needs_review`.
- Human review required before publish-facing use.
- Human review required before shipping-facing use.
- Human review required before claims involving dimensions/weight.
- Human review required before Woo draft if dimensions/weight affect shipping or product facts.
- Operator can accept/edit/reject.
- Operator correction wins.

AI draft acceptance is an explicit human action. K10 mock adapter cannot promote its own output to reviewed, approved, canonical, shipping-ready, publish-ready, or reviewer-corrected.

# 2. Error policy

| Error | AI should output? | Blocks what? | Human action |
| --- | --- | --- | --- |
| `missing_value` | Yes, when unit or field context exists but no numeric value is provided. | Conversion, normalized/display values, and downstream use of the affected field. | Enter a numeric value, mark not applicable, or reject the draft. |
| `missing_unit` | Yes, when numeric value exists without a unit. | Conversion and any use requiring unit-safe dimensions/weight. | Select the correct unit from K09 supported units or reject the value. |
| `unsupported_unit` | Yes, when source unit is outside K09 supported units. | Conversion, display suggestion, shipping/product-fact gates that depend on the value. | Replace with supported unit after confirming source meaning, or reject. |
| `invalid_numeric_value` | Yes, when value cannot be represented safely as numeric. | All downstream use of that value. | Correct the number or reject the draft. |
| `ambiguous_dimension_format` | Yes, when order/separators do not safely identify dimensions. | Exact L/W/H use, package dimensions use, shipping, Woo draft, and product claims requiring exact dimensions. | Set explicit `dimension_order` / `dimension_format`, edit fields, or reject. |
| `product_vs_package_conflict` | Yes, when source mixes product body and package/shipping context. | Product/package field acceptance and dependent shipping/product fact gates. | Move value to correct payload, split source, request supplier clarification, or reject. |
| `net_vs_gross_weight_ambiguous` | Yes, when weight source does not identify net, gross, package, or shipping context. | Product weight claims, shipping weight use, Woo draft, and publish-facing weight facts. | Choose net/gross/package/shipping explicitly or reject the draft. |
| `ai_guessing_forbidden` | Yes, when a suggested value would require AI invention or inference. | Acceptance of the AI draft and all downstream use of the guessed field. | Reject the AI draft or replace with explicit operator/reviewer value. |
| `conversion_not_possible` | Yes, when value/unit/rule/group prevents deterministic conversion. | Normalized metric/imperial values, display values, and dependent gates. | Fix value/unit/group, choose supported unit, or mark not applicable. |
| `original_value_missing` | Yes, if normalized or display values exist without preserved original value. K10 should avoid producing this. | Trust in derived values, review acceptance, reconciliation, and publish-facing use. | Restore original value from source or reject derived payload. |

K10 mock adapter may include errors while keeping `review_status` as `draft` or `needs_review`. Blocking behavior belongs to downstream review/gate logic, not to AI self-approval.

# 3. Warning policy

| Warning | Meaning | AI should output? | Human action |
| --- | --- | --- | --- |
| `precision_loss_warning` | Conversion or rounding may lose source precision. | Yes, when displayed precision may overstate source certainty. | Review precision and accept/edit. |
| `market_display_unknown` | Display market cannot be resolved or is mixed. | Yes, when display market is absent, unknown, or ambiguous. | Select display market or accept approved fallback. |
| `display_market_missing` | Intended use requires display market but it is absent. | Yes, when no display market is available for the suggestion. | Choose display market or mark display suggestion unavailable. |
| `dimension_order_missing` | Multiple dimension values exist but order metadata is absent. | Yes, when source order cannot be mapped safely. | Add explicit order or reject dimension draft. |
| `optional_field_missing` | Optional field is absent. | Yes, only when useful for review context. | Leave absent, mark not applicable, or fill if required later. |
| `review_required` | Payload exists but must be checked by human. | Yes, on all AI unit payload suggestions. | Accept, edit, reject, or request review. |
| `free_text_parsing_not_supported` | Source text exists but cannot be safely parsed by the current K09/K07 helper boundary. | Yes, when text cannot be converted into explicit fields without a separate parser approval. | Enter explicit numeric fields or wait for approved parser work. |

Warnings do not approve a value. A warning can still block downstream use when a downstream context requires confirmed dimensions, weight, packaging, or display-market values.

# 4. Field diff policy

- AI unit output differences go to `field_diff_json`.
- canonical values are not overwritten automatically.
- operator can accept/edit/reject unit payload suggestions.
- `operation_logs` future integration waits for K21.
- K09H does not modify `operation_logs`.

`field_diff_json` should show the affected K09 path, current canonical/reviewed value when present, AI draft value or candidate, source text, warning/error references, and proposed human action. Human-confirmed values win over AI draft values.

# 5. Future K10 mock adapter requirements

- K10 mock adapter must produce deterministic payload shape.
- K10 mock adapter must preserve `source_text`.
- K10 mock adapter must attach warnings/errors.
- K10 mock adapter must never output secret/provider data.
- K10 mock adapter must not call live DeepSeek in mock stage.
- K10 live adapter waits for C14/C09 approval.

K09H is not runtime integration approval. K10 mock adapter wiring, service behavior, API exposure, provider credentials, live provider calls, and downstream consumption require separate owner approval.
