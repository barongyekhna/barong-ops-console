# 1. K09H 目标

K09H 只定义未来 K10 AI mock adapter 的单位输出规则。

- K09H 不写 K10 code。
- K09H 不接 DeepSeek live。
- K09H 不接 API。
- K09H 不改 runtime。
- K09H 是 K10 mock adapter 的前置设计材料。
- K09H 只把 K09A-G 已完成的单位存储、payload contract、module-local helper、tests 和 K07 输入设计，转成未来 K10 mock adapter 的单位输出约束。

# 2. AI 单位输出总原则

- AI 可以结构化已提供的 numeric value + unit。
- AI 可以把 `source_text` 中明确提供的单位信息整理成 draft payload。
- AI 不得猜测缺失尺寸。
- AI 不得猜测缺失重量。
- AI 不得猜测包装尺寸。
- AI 不得猜测净重/毛重区别。
- AI 不得猜测 `product dimensions` 与 `package dimensions` 区别。
- AI 不得把 `unknown` / `missing` 转成 `0`。
- AI 不得把 unsupported unit 静默换成默认单位。
- AI 输出必须是 `draft` / `needs_review`。
- AI 输出不得自动进入 `reviewed` / `reviewer_corrected`。
- AI 不得静默覆盖人工确认字段。
- AI 输出必须保留 `source_text` / `source_language` / `parsed_from_text`。
- AI 不得调用 live provider in K09H。

K10 mock adapter 的单位输出只能表示 AI 对已提供资料的结构化尝试。它不是事实确认、人工审核、物流确认、发布确认或 Woo draft 确认。

# 3. K10 mock adapter 允许输出

K10 mock adapter 未来可输出以下 draft-only 单位相关内容：

- `dimensions_json` draft。
- `package_dimensions_json` draft。
- `weight_json` draft。
- `package_weight_json` draft。
- dynamic attributes with `attribute_unit`。
- `ai_warnings_json`。
- `field_diff_json`。
- missing field hints。
- unsupported unit warnings/errors。
- review_required warnings。

Allowed output rules:

- 如果来源明确写出 `length 10 cm`，AI 可以把 `10` 和 `cm` 结构化到对应 K09 Unit Value Payload。
- 如果来源明确写出 `net weight 1.2 kg`，AI 可以结构化到 `weight_json.net_weight`。
- 如果来源只写 `weight 2 lb`，AI 可以保留来源和候选信息，但不得自动判定为 `net_weight`、`gross_weight`、`package_weight` 或 `shipping_weight`。
- 如果来源只写 `10 x 5 x 3 cm`，AI 可以保留三段数值和单位的来源提示，但不得无证据输出确定的 L/W/H。
- 如果来源明确写出 package/shipping context，AI 可以输出 package payload；否则必须要求 review。

# 4. K10 mock adapter 禁止输出

- 不输出 `reviewed` 状态。
- 不输出 `reviewer_corrected` 状态。
- 不输出 human-confirmed values。
- 不输出没有来源的尺寸/重量。
- 不输出猜测的 L/W/H 顺序。
- 不输出猜测的 `net_weight`。
- 不输出猜测的 `package_weight`。
- 不把 free-text-only source 解析成确定 L/W/H。
- 不把 product dimensions 复制到 package dimensions。
- 不把 package dimensions 复制到 product dimensions。
- 不把 package weight 复制到 product net weight。
- 不把 `display_unit` 当 `original_unit`。
- 不直接写 DB。
- 不直接调用 n8n。
- 不连接 live provider。

AI output 不能因为 marketplace、品类、图片、标题或经验规则补齐缺失单位事实。缺失字段只能进入 missing hints、warnings、errors 或 `field_diff_json` 建议区。

# 5. Source handling

- `source_text` 必须保留。
- `source_language` 必须保留。
- `parsed_from_text` 只能表示“AI 尝试结构化来源文本”，不代表人工确认。
- 如果 `source_text` 模糊，必须 warnings/errors。
- 如果单位缺失，必须 `missing_unit`。
- 如果数值缺失，必须 `missing_value`。
- 如果格式模糊，必须 `ambiguous_dimension_format`。
- 如果产品/包装不明确，必须 `product_vs_package_conflict` 或 `review_required`。
- 如果 net/gross 不明确，必须 `net_vs_gross_weight_ambiguous`。

Source handling rules:

- AI 不得伪造 `source_text`。
- AI 不得把产品级 raw input 当成单位字段的人工确认来源。
- `parsed_from_text = true` 只说明结构化尝试来自文本，不说明字段可以 publish-facing 或 shipping-facing 使用。
- 无法安全结构化时，AI 应保留 source metadata，并输出 warning/error，而不是填默认值。

# 6. K10 与 K09 helper 的关系

- K09 `unit_conversion.py` 和 `unit_payloads.py` 是 backend module-local helper。
- K10 mock adapter 可以按 K09 payload contract 输出 JSON。
- K10 mock adapter 不应直接依赖 frontend。
- K10 mock adapter 不应直接写 DB。
- K10 mock adapter 未来应通过 backend service 接入，但 K09H 不批准 runtime integration。
- K10 live adapter 仍 blocked until C14/C09 provider rules。

K09H 不批准 K10 mock adapter runtime wiring。未来如接入 backend service、API、router、DeepSeek live、operation logs、Woo draft、n8n 或 P-series consumption，必须另行 owner approval。
