# 1. Mapping purpose

This file maps K08/K09 unit fields to future K07 frontend input controls.

K08 top-level fields remain product-level JSON fields. K09 nested fields are payload contract paths inside those JSON fields, not product-table columns. Future K07 unit input UI should collect explicit numeric value + unit and generate K09 payload shape only.

# 2. Product dimensions mapping

| UI field | K08 top-level field | K09 payload path | Input control | Unit group | Allowed units | Required at creation? | Blocks downstream? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `length` | `dimensions_json` | `dimensions_json.length` | numeric input + unit selector | `length` | `mm`, `cm`, `m`, `in`, `ft` | no | conditional | Product-body length only. Uses common Unit Value Payload when present. |
| `width` | `dimensions_json` | `dimensions_json.width` | numeric input + unit selector | `length` | `mm`, `cm`, `m`, `in`, `ft` | no | conditional | Product-body width only. Do not infer from ambiguous source text. |
| `height` | `dimensions_json` | `dimensions_json.height` | numeric input + unit selector | `length` | `mm`, `cm`, `m`, `in`, `ft` | no | conditional | Product-body height only. Missing is not `0`. |
| `diameter` | `dimensions_json` | `dimensions_json.diameter` | numeric input + unit selector | `length` | `mm`, `cm`, `m`, `in`, `ft` | no | conditional | Use only when source explicitly identifies diameter. |
| `thickness` | `dimensions_json` | `dimensions_json.thickness` | numeric input + unit selector | `length` | `mm`, `cm`, `m`, `in`, `ft` | no | conditional | Use only when source explicitly identifies thickness. |
| `dimension_order` | `dimensions_json` | `dimensions_json.dimension_order` | ordered token selector | `length` | n/a | no | conditional | Records source order; required for multi-part dimensions when known. |
| `dimension_format` | `dimensions_json` | `dimensions_json.dimension_format` | select | `length` | n/a | no | conditional | Examples: `l_w_h`, `length_diameter`, `single_dimension`, `ambiguous_3_part`. |
| `source_text` | `dimensions_json` | `dimensions_json.source_text` | textarea / source display | n/a | n/a | no | no by itself | Preserves source text. K07/K09 does not parse free text in this scope. |

# 3. Package dimensions mapping

| UI field | K08 top-level field | K09 payload path | Input control | Unit group | Allowed units | Required at creation? | Blocks downstream? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `package_length` | `package_dimensions_json` | `package_dimensions_json.package_length` | numeric input + unit selector | `length` | `mm`, `cm`, `m`, `in`, `ft` | no | conditional | Package/shipping length only. Must not backfill product length. |
| `package_width` | `package_dimensions_json` | `package_dimensions_json.package_width` | numeric input + unit selector | `length` | `mm`, `cm`, `m`, `in`, `ft` | no | conditional | Package/shipping width only. |
| `package_height` | `package_dimensions_json` | `package_dimensions_json.package_height` | numeric input + unit selector | `length` | `mm`, `cm`, `m`, `in`, `ft` | no | conditional | Package/shipping height only. |
| `package_diameter` | `package_dimensions_json` | `package_dimensions_json.package_diameter` | numeric input + unit selector | `length` | `mm`, `cm`, `m`, `in`, `ft` | no | conditional | Package diameter only when explicitly sourced. |
| `package_dimension_order` | `package_dimensions_json` | `package_dimensions_json.package_dimension_order` | ordered token selector | `length` | n/a | no | conditional | Records source package dimension order. |
| `package_dimension_format` | `package_dimensions_json` | `package_dimensions_json.package_dimension_format` | select | `length` | n/a | no | conditional | Package-specific format; do not reuse product format automatically. |
| `package_source_text` | `package_dimensions_json` | `package_dimensions_json.package_source_text` | textarea / source display | n/a | n/a | no | no by itself | Preserves package source text without parsing it. |

# 4. Product weight mapping

| UI field | K08 top-level field | K09 payload path | Input control | Unit group | Allowed units | Required at creation? | Blocks downstream? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `net_weight` | `weight_json` | `weight_json.net_weight` | numeric input + unit selector | `weight` | `g`, `kg`, `oz`, `lb` | no | conditional | Product net weight only. Generic `weight: 2 lb` is ambiguous until reviewed. |
| `gross_weight` | `weight_json` | `weight_json.gross_weight` | numeric input + unit selector | `weight` | `g`, `kg`, `oz`, `lb` | no | conditional | Product gross weight only when source explicitly says gross. |
| `source_text` | `weight_json` | `weight_json.source_text` | textarea / source display | n/a | n/a | no | no by itself | Preserves source text; does not infer net/gross. |

# 5. Package weight mapping

| UI field | K08 top-level field | K09 payload path | Input control | Unit group | Allowed units | Required at creation? | Blocks downstream? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `package_weight` | `package_weight_json` | `package_weight_json.package_weight` | numeric input + unit selector | `weight` | `g`, `kg`, `oz`, `lb` | no | conditional | Package weight only. Must not backfill product net weight. |
| `shipping_weight` | `package_weight_json` | `package_weight_json.shipping_weight` | numeric input + unit selector | `weight` | `g`, `kg`, `oz`, `lb` | no | conditional | Shipping weight only when explicitly sourced. |
| `source_text` | `package_weight_json` | `package_weight_json.source_text` | textarea / source display | n/a | n/a | no | no by itself | Preserves package/shipping weight source text. |

# 6. Display fields

| UI field | K08 top-level field | K09 payload path | Input control | Unit group | Allowed units | Required at creation? | Blocks downstream? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `original_value` | any unit JSON field | `*.original_value` | read/write numeric value before review; read-only after reviewer lock | length / weight / future volume / future temperature | by payload group | no | yes when required value is missing | Exact source value. Display conversion must not overwrite it. |
| `original_unit` | any unit JSON field | `*.original_unit` | unit selector | length / weight / future volume / future temperature | by payload group | no | yes when required unit is missing | Exact source unit or canonical unit code. Unsupported units must show error. |
| `normalized_metric_value` | any unit JSON field | `*.normalized_metric_value` | derived read-only | by payload group | n/a | no | no by itself | System-converted metric value. |
| `normalized_metric_unit` | any unit JSON field | `*.normalized_metric_unit` | derived read-only | by payload group | metric default by group | no | no by itself | Metric unit label, such as `cm`, `kg`, `l`, `c`. |
| `normalized_imperial_value` | any unit JSON field | `*.normalized_imperial_value` | derived read-only | by payload group | n/a | no | no by itself | System-converted imperial value. |
| `normalized_imperial_unit` | any unit JSON field | `*.normalized_imperial_unit` | derived read-only | by payload group | imperial default by group | no | no by itself | Imperial unit label, such as `in`, `lb`, `fl_oz`, `f`. |
| `display_value` | any unit JSON field | `*.display_value` | derived read-only / display preview | by payload group | by display unit | no | no by itself | Market display recommendation only. |
| `display_unit` | any unit JSON field | `*.display_unit` | derived display selector preview | by payload group | by display market | no | no by itself | Must not rewrite original unit. |
| `display_market` | any unit JSON field | `*.display_market` | market selector | n/a | `US`, `UK`, `EU`, `AU`, `CA`, `fallback`, `unknown` | no | conditional | Payload-level display context; not the same as `target_market`. |
| `conversion_source` | any unit JSON field | `*.conversion_source` | source badge/select | n/a | `operator_entered`, `supplier_imported`, `system_converted`, `reviewer_corrected`, `ai_structured_from_provided_input`, `unknown` | no | conditional | AI source remains draft until reviewed. |
| `conversion_precision` | any unit JSON field | `*.conversion_precision` | read-only metadata | n/a | `exact`, `2_decimal_places`, `source_precision_preserved`, `conversion_not_possible` | no | no by itself | Must be visible when rounding or conversion is shown. |
| `review_status` | any unit JSON field | `*.review_status` | status select/badge | n/a | `draft`, `needs_review`, `reviewed`, `reviewer_corrected`, `blocked`, `not_applicable`, `unknown` | no | yes when blocked or unreviewed for required use | Payload-level review status. |
| `reviewer_corrected` | any unit JSON field | `*.reviewer_corrected` | checkbox/badge controlled by review action | n/a | boolean | no | no by itself | Human-corrected values win over AI/system drafts. |
| `warnings` | any unit JSON field | `*.warnings` | warning list | n/a | K09 warning vocabulary | no | conditional | Does not always block, but must be visible. |
| `errors` | any unit JSON field | `*.errors` | error list | n/a | K09 error vocabulary | no | yes | Blocks dependent downstream gates until resolved or marked not applicable. |

# 7. Future-only fields

| UI field | K08 top-level field | K09 payload path | Input control | Unit group | Allowed units | Required at creation? | Blocks downstream? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `volume` / `capacity` | future dynamic payload / dynamic attributes | future `volume_payload.volume` / `volume_payload.capacity` | numeric input + unit selector | `volume` | `ml`, `l`, `fl_oz` | no | future conditional | Future-only contract reference. Not required for current K07A/B. |
| `temperature value` / `range` | future dynamic payload / dynamic attributes | future `temperature_payload.temperature_value` / `temperature_range_min` / `temperature_range_max` | numeric or range input + unit selector | `temperature` | `c`, `f` | no | future conditional | Future-only contract reference. Requires explicit context. |
| `context` | future dynamic payload / dynamic attributes | future `temperature_payload.temperature_context` | select | `temperature` | n/a | no | future conditional | Context such as `operating`, `storage`, `warning`, `performance`. |

Future-only 不代表现在 K07 必须实现。

K07A/B 可先不做 volume/temperature UI。
