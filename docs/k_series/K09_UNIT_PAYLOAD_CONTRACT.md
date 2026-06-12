# K09 Unit Payload Contract

Status: K09B payload contract draft, pending owner review.

Date: 2026-06-12.

# 1. K09B 目标

K09B 只定义单位 payload contract 和文档级 JSON shape。

K09B 不写 Python 代码、不改 migration、不改 backend runtime、不改 frontend runtime、不注册 router、不修改 `main.py`、不修改 core config、core permissions 或 core auth/deps。

K09B 是以下后续工作的前置材料：

- K09C unit conversion pure functions.
- K09D non-DB unit conversion tests.
- K07 unit input UI.
- K10 AI mock adapter unit output constraints.

K09B 不连接 DB、不读取 env、不连接 live services、不读取或修改 P-series workflow JSON、不修改 n8n draft lane。

# 2. 通用 Unit Value Payload

通用 Unit Value Payload 适用于 length / weight / volume / temperature。任何带单位的单值字段都应使用同一组字段语义。

Required fields:

| Field | Meaning |
| --- | --- |
| `value_kind` | Unit value category. Suggested values: `length`, `weight`, `volume`, `temperature`. |
| `original_value` | 原始输入数值，来自 operator、supplier、approved import、AI structured provided input 或 reviewer correction。 |
| `original_unit` | 原始输入单位，必须保留原始语义。 |
| `normalized_metric_value` | 系统换算出的 metric 数值。 |
| `normalized_metric_unit` | 系统换算出的 metric 单位。 |
| `normalized_imperial_value` | 系统换算出的 imperial 数值。 |
| `normalized_imperial_unit` | 系统换算出的 imperial 单位。 |
| `display_value` | 推荐展示数值，基于 display market 或 reviewed target market。 |
| `display_unit` | 推荐展示单位，基于 display market 或 reviewed target market。 |
| `display_market` | 展示市场，例如 `US`, `UK`, `EU`, `AU`, `CA`, `fallback` 或 `unknown`。 |
| `conversion_source` | 当前值或换算的来源，见 section 9。 |
| `conversion_precision` | rounding / precision metadata，例如 `exact`, `2_decimal_places`, `source_precision_preserved`。 |
| `source_text` | 原始文本片段。没有文本来源时可为 `null`，但不得伪造。 |
| `source_language` | 原始文本语言，例如 `en`, `zh`, `unknown`。 |
| `parsed_from_text` | 是否从 source text 解析。 |
| `review_status` | 审核状态，见 section 10。 |
| `reviewer_corrected` | 是否为人工修正值。人工确认或修正值优先级最高。 |
| `warnings` | Warning code array。 |
| `errors` | Error code array。 |

Rules:

- `original_value` / `original_unit` 必须保留原始输入，不得被系统换算、市场展示或 AI draft 静默覆盖。
- `normalized_metric_value` / `normalized_imperial_value` 是系统换算值，不是原始输入。
- `display_value` / `display_unit` 是展示建议，不得覆盖 `original_value` / `original_unit`。
- `unknown` 不等于 `0`。
- `missing` 不等于 `0`。
- AI 不得猜测缺失值。
- AI 只能结构化已提供输入中明确存在的值。
- `reviewer_corrected = true` 的人工确认值优先级最高，并应保留原始输入和 field diff reference where practical。
- Unsupported unit、missing unit、missing value 或 invalid numeric value 必须进入 `warnings` 或 `errors`，不得静默落成默认单位或零值。

# 3. dimensions_json contract

`dimensions_json` 表示产品本体尺寸，不表示包装尺寸。

Required payload fields:

| Field | Meaning |
| --- | --- |
| `length` | Product length, uses the common Unit Value Payload. |
| `width` | Product width, uses the common Unit Value Payload. |
| `height` | Product height, uses the common Unit Value Payload. |
| `diameter` | Product diameter, uses the common Unit Value Payload. |
| `thickness` | Product thickness, uses the common Unit Value Payload. |
| `unit_group` | Must be `length`. |
| `dimension_order` | Source order of dimensions as provided, for example `["length", "width", "height"]` or `["unknown_1", "unknown_2", "unknown_3"]`. |
| `dimension_format` | Source format, for example `l_w_h`, `length_diameter`, `ambiguous_3_part`, `single_dimension`. |
| `source_text` | Original source text for the whole dimension payload. |
| `source_language` | Source language for the whole dimension payload. |
| `parsed_from_text` | Whether the payload was parsed from text. |
| `display_market` | Market used for display recommendation. |
| `review_status` | Payload-level review status. |
| `warnings` | Payload-level warnings. |
| `errors` | Payload-level errors. |

Rules:

- `length` / `width` / `height` / `diameter` / `thickness` all use the common Unit Value Payload when present.
- Fields may be absent when unknown or not applicable, but unknown values must not be represented as `0`.
- If `source_text` is `10 x 5 x 3 cm`, `dimension_order` must record the source order.
- `ambiguous_dimension_format` must be written to `warnings` or `errors`.
- The system must not silently assume L/W/H order.
- AI may parse explicit values from provided text, but must not invent missing dimensions.
- `display_market` controls display suggestion only. It does not rewrite original values.

# 4. package_dimensions_json contract

`package_dimensions_json` 表示包装或运输尺寸，必须与 product dimensions 分开。

Required payload fields:

| Field | Meaning |
| --- | --- |
| `package_length` | Package length, uses the common Unit Value Payload. |
| `package_width` | Package width, uses the common Unit Value Payload. |
| `package_height` | Package height, uses the common Unit Value Payload. |
| `package_diameter` | Optional package diameter, uses the common Unit Value Payload. |
| `package_unit_group` | Must be `length`. |
| `package_dimension_order` | Source order for package dimensions. |
| `package_dimension_format` | Source package dimension format. |
| `package_source_text` | Original source text for package dimensions. |
| `display_market` | Market used for package display recommendation. |
| `review_status` | Payload-level review status. |
| `warnings` | Payload-level warnings. |
| `errors` | Payload-level errors. |

Rules:

- Package dimensions and product dimensions are separate payloads.
- Do not treat package dimensions as product body dimensions.
- Do not treat product dimensions as package dimensions.
- Unknown package values must remain missing or unknown, not `0`.
- Ambiguous package dimension format must be warning or error, not silently assumed.

# 5. weight_json contract

`weight_json` 表示产品本体重量，不表示包装重量或运输重量。

Required payload fields:

| Field | Meaning |
| --- | --- |
| `net_weight` | Product net weight, uses the common Unit Value Payload. |
| `gross_weight` | Optional product gross weight, uses the common Unit Value Payload. |
| `unit_group` | Must be `weight`. |
| `source_text` | Original source text for the whole weight payload. |
| `source_language` | Source language for the whole weight payload. |
| `parsed_from_text` | Whether the payload was parsed from text. |
| `display_market` | Market used for display recommendation. |
| `review_status` | Payload-level review status. |
| `warnings` | Payload-level warnings. |
| `errors` | Payload-level errors. |

Rules:

- `net_weight` uses the common Unit Value Payload.
- `gross_weight` is optional.
- If source input cannot distinguish net weight from gross weight, add `net_vs_gross_weight_ambiguous` to `warnings` or `errors`.
- AI must not automatically treat shipping weight as product net weight.
- AI must not infer net weight from package weight, product category, image, or description if the value is not explicitly provided.

# 6. package_weight_json contract

`package_weight_json` 表示包装或运输重量，必须与 product `weight_json` 分开。

Required payload fields:

| Field | Meaning |
| --- | --- |
| `package_weight` | Package weight, uses the common Unit Value Payload. |
| `shipping_weight` | Optional shipping weight, uses the common Unit Value Payload. |
| `unit_group` | Must be `weight`. |
| `source_text` | Original source text for the whole package weight payload. |
| `source_language` | Source language for the whole package weight payload. |
| `parsed_from_text` | Whether the payload was parsed from text. |
| `display_market` | Market used for package display recommendation. |
| `review_status` | Payload-level review status. |
| `warnings` | Payload-level warnings. |
| `errors` | Payload-level errors. |

Rules:

- `package_weight` / `shipping_weight` are separate from product `net_weight`.
- Do not treat package weight as product weight.
- Do not treat product weight as package weight.
- If a payload mixes product and package language, add `product_vs_package_conflict`.

# 7. future volume payload contract

Future volume payload supports category-specific capacity, volume, liquid amount, container amount, or marketplace fields. K09B defines the contract only and does not require every current product to have volume.

Required payload fields:

| Field | Meaning |
| --- | --- |
| `volume` | Optional volume value, uses the common Unit Value Payload. |
| `capacity` | Optional capacity value, uses the common Unit Value Payload. |
| `unit_group` | Must be `volume`. |
| `supported_units` | Must be limited to `ml`, `l`, `fl_oz`. |
| `source_text` | Original source text for the whole volume payload. |
| `source_language` | Source language for the whole volume payload. |
| `display_market` | Market used for display recommendation. |
| `review_status` | Payload-level review status. |
| `warnings` | Payload-level warnings. |
| `errors` | Payload-level errors. |

Rules:

- K09B only defines a future contract. It does not add DB fields or runtime behavior.
- `volume` / `capacity` missing values must not be guessed by AI.
- Missing volume/capacity is not `0`.

# 8. future temperature payload contract

Future temperature payload supports operating, storage, warning, performance, compliance, or category-specific temperature fields. K09B defines the contract only.

Required payload fields:

| Field | Meaning |
| --- | --- |
| `temperature_value` | Optional single temperature value, uses the common Unit Value Payload. |
| `temperature_range_min` | Optional min range value, uses the common Unit Value Payload. |
| `temperature_range_max` | Optional max range value, uses the common Unit Value Payload. |
| `unit_group` | Must be `temperature`. |
| `supported_units` | Must be limited to `c`, `f`. |
| `temperature_context` | Must state `operating`, `storage`, `warning`, `performance`, or another reviewed explicit context. |
| `source_text` | Original source text for the whole temperature payload. |
| `source_language` | Source language for the whole temperature payload. |
| `display_market` | Market used for display recommendation. |
| `review_status` | Payload-level review status. |
| `warnings` | Payload-level warnings. |
| `errors` | Payload-level errors. |

Rules:

- K09B only defines a future contract. It does not add DB fields or runtime behavior.
- Temperature range must clearly state whether it is operating, storage, warning, or performance context.
- AI must not guess temperature ranges.
- Missing temperature values are not `0`.

# 9. conversion_source values

Allowed values:

| Value | Meaning |
| --- | --- |
| `operator_entered` | The value was directly entered by an operator. Conversion may still be derived later, but the original value comes from operator input. |
| `supplier_imported` | The value came from supplier-provided data or an approved import source. |
| `system_converted` | The normalized or display value was produced by deterministic system conversion from an explicit source value. |
| `reviewer_corrected` | A reviewer corrected or confirmed the value. This has the highest precedence. |
| `ai_structured_from_provided_input` | AI structured an explicit value already present in provided input. AI did not invent missing facts. |
| `unknown` | Source is unknown or not yet classified. This must not imply a numeric value is valid. |

# 10. review_status values

Allowed values:

| Value | Meaning |
| --- | --- |
| `draft` | Payload is present but not ready for downstream approved use. |
| `needs_review` | Payload requires human review before publish-facing or shipping-facing use. |
| `reviewed` | Payload has been reviewed and accepted without correction. |
| `reviewer_corrected` | Payload was corrected by a reviewer and the corrected value should win. |
| `blocked` | Payload cannot be used until errors are resolved. |
| `not_applicable` | Field is explicitly not applicable for this product or context. |
| `unknown` | Review state is unknown and must not be treated as approved. |

# 11. error / warning vocabulary

Allowed warning/error codes:

| Code | Meaning |
| --- | --- |
| `unsupported_unit` | Unit is not in the supported K09 unit set. |
| `missing_unit` | Numeric value exists but unit is missing. |
| `missing_value` | Unit or field exists but numeric value is missing. |
| `invalid_numeric_value` | Value is not numeric or cannot be represented safely. |
| `ambiguous_dimension_format` | Dimension order or separators are ambiguous. |
| `ai_guessing_forbidden` | AI attempted to invent a unit-bearing fact. |
| `precision_loss_warning` | Conversion or rounding may lose source precision. |
| `market_display_unknown` | Display market cannot be resolved. |
| `original_value_missing` | Normalized or display value exists but original value is absent. |
| `conversion_not_possible` | Conversion cannot run because value, unit, or conversion rule is unavailable. |
| `product_vs_package_conflict` | Product body values and package/shipping values are mixed or conflicted. |
| `net_vs_gross_weight_ambiguous` | Weight source does not clearly identify net, gross, package, or shipping context. |
| `display_market_missing` | Display market is required for the intended use but is absent. |

# 12. K09C implementation notes

K09C can use this contract to implement deterministic pure functions for parsing, validating, normalizing, and selecting display values.

K09C constraints:

- K09C should not connect DB.
- K09C should not modify service create/update behavior.
- K09C should not register router.
- K09C should not modify `main.py`.
- K09C should not read env.
- K09C should not connect live services.
- K09C should not read or modify P-series workflow JSON.
- K09C should keep conversion behavior deterministic and testable without Postgres, Alembic, Docker, staging, or production.
