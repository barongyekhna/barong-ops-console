# 1. Validation state purpose

This file defines how future K07 frontend should display K09 unit payload validation states.

K09G only defines UI states and does not implement runtime validation. Future K07 should surface payload-level `errors`, `warnings`, and `review_status` clearly, without converting missing / unknown values to `0` and without treating AI draft values as approved facts.

# 2. Error states

| Error | Meaning | UI severity | Blocking behavior | Operator action | Downstream impact |
| --- | --- | --- | --- | --- | --- |
| `unsupported_unit` | Unit is not in the K09 supported unit set. | error | Block the affected field and dependent gates. | Select a supported unit or reject the value. | Blocks shipping/display/product-fact gates that depend on the value. |
| `missing_unit` | Numeric value exists but unit is missing. | error | Block conversion and dependent gates. | Choose the correct unit from the allowed selector. | Blocks normalized/display values and any downstream use requiring a unit. |
| `missing_value` | Unit or field exists but numeric value is missing. | error | Block conversion and dependent gates. | Enter the value, mark not applicable, or request review. | Blocks dependent dimensions/weight/package/shipping gates. |
| `invalid_numeric_value` | Value is not numeric or cannot be represented safely. | error | Block conversion and dependent gates. | Correct the numeric input. | Blocks all downstream use of that field. |
| `ambiguous_dimension_format` | Dimension order or separators are ambiguous. | error | Block any use that needs exact L/W/H or exact package order. | Set explicit `dimension_order` / `dimension_format` or request review. | Blocks shipping, fit, media scale, content claims, Woo draft, or publish review when exact dimensions matter. |
| `product_vs_package_conflict` | Product-body values and package/shipping values are mixed or conflicted. | error | Block the affected payload and dependent gates. | Move the value to the correct product/package section or request review. | Blocks gates relying on product/package separation. |
| `net_vs_gross_weight_ambiguous` | Weight source does not identify net, gross, package, or shipping context. | error | Block product net/gross use until clarified. | Choose net/gross/package/shipping explicitly or mark unknown. | Blocks product weight claims, shipping, Woo draft, and publish review when weight is required. |
| `ai_guessing_forbidden` | AI attempted to invent or fill a unit-bearing fact. | error | Block the draft from acceptance as reviewed value. | Reject AI draft or replace with explicit operator/reviewer value. | Blocks all downstream use of the AI-guessed field. |
| `conversion_not_possible` | Conversion cannot run because value, unit, group, or rule is unavailable. | error | Block normalized/display values and dependent gates. | Fix value/unit/group or mark not applicable. | Blocks any downstream workflow needing normalized metric/imperial/display values. |
| `original_value_missing` | Normalized or display value exists but original value is absent. | error | Block trust in derived values. | Restore original value or reject the derived payload. | Blocks review, reconciliation, and publish-facing use. |

# 3. Warning states

| Warning | Meaning | UI severity | Operator action | Downstream impact |
| --- | --- | --- | --- | --- |
| `precision_loss_warning` | Conversion or rounding may lose source precision. | warning | Review precision and accept or edit. | May allow `ready_with_warnings` when non-critical and human-accepted. |
| `market_display_unknown` | Display market cannot be resolved or is mixed/uncertain. | warning | Choose display market or accept conservative fallback. | May warn in display/feed gates; does not overwrite original values. |
| `display_market_missing` | Display market is required for intended use but absent. | warning | Select display market or approved fallback. | Can block only when downstream display/feed context requires a market. |
| `dimension_order_missing` | Multiple dimension values exist but order metadata is absent. | warning | Add source order or request review. | May block exact-dimension gates; may remain warning for non-critical display. |
| `optional_field_missing` | Optional unit field is absent. | info/warning | Leave absent, mark not applicable, or fill if needed. | Should not block unless a downstream context makes it required. |
| `review_required` | Payload is present but needs human review. | warning | Review, accept, edit, reject, or request specialist review. | Blocks publish-facing or shipping-facing use until reviewed if value is required. |
| `free_text_parsing_not_supported` | Source text exists, but K09/K07 does not parse free text in this scope. | warning | Enter explicit numeric fields manually or request a future parser task. | Prevents treating source text as parsed payload; may block if numeric fields are missing. |

# 4. Review states

| Review state | Meaning | UI display rule | Downstream behavior |
| --- | --- | --- | --- |
| `draft` | Payload is present but not ready for approved use. | Draft badge; editable. | Not publish-ready and not approved for dependent gates. |
| `needs_review` | Payload requires human review. | Review-needed badge with warnings/errors visible. | Blocks required downstream use until reviewed. |
| `reviewed` | Payload has been reviewed and accepted without correction. | Reviewed badge. | Can satisfy dependent gates if no blocking errors remain. |
| `reviewer_corrected` | Reviewer corrected the payload and corrected value should win. | Corrected badge; show diff/source where available. | Highest precedence over AI/system draft values. |
| `blocked` | Payload cannot be used until errors are resolved. | Blocked badge with errors expanded. | Blocks dependent gates. |
| `not_applicable` | Field is explicitly not applicable for this product/context. | Not applicable badge; no numeric zero. | Does not satisfy required value, but can clear optional field ambiguity. |
| `unknown` | Review state is unknown. | Unknown badge; conservative treatment. | Must not be treated as approved. |

# 5. Readiness gate display

- gate blocked 显示 errors。
- gate ready_with_warnings 显示 warnings。
- operator 可以修正后 rerun gate check。
- AI 不能 mark gate approved。
- unit payload errors 会阻断依赖尺寸/重量/包装/运输信息的 gates。
- K09G 只定义 UI 状态，不实现 runtime validation。
- Blocking unit payload errors should remain linked to the exact field and top-level payload path, for example `dimensions_json.length.errors`.
- Future K07 must show whether a gate is blocked by product dimensions, package dimensions, product weight, or package/shipping weight.

# 6. Market display UI

- US 默认 imperial。
- EU/AU 默认 metric。
- UK/CA mixed，当前无上下文时显示 conservative fallback + warning。
- display choice 不覆盖 original values。
- operator 可以查看 original / metric / imperial 三组值。
- Unknown or unsupported market should use conservative metric fallback with a warning, not silently approve display values.
- `display_market` is payload-level display context; it is not a replacement for readiness/request `target_market`.
