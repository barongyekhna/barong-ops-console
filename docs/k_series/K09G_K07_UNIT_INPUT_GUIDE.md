# 1. K09G 目标

K09G 只定义未来 K07 前端单位输入 UI 规则。

- K09G 不写 frontend code。
- K09G 不接 API。
- K09G 不改 runtime。
- K09G 是 K07 hidden UI shell 的前置设计材料。
- K09G 将 K09A-E 已完成的单位存储、换算、payload contract、helper 和测试约束，转成未来 K07 单位输入的设计规则。

# 2. K07 单位输入总原则

- K07 未来只能 hidden-by-default。
- 不挂正式菜单。
- 不接正式 scope。
- 不接 live provider。
- 不接 production/staging。
- 不直接写数据库。
- 不直接调用 n8n。
- 单位输入只生成 K09 payload shape。
- 原始值不得被展示单位覆盖。
- missing / unknown 不得显示为 0。
- AI 不得猜测尺寸、重量、包装尺寸、净重/毛重、产品/包装区别。
- `source_text` 可展示，但 K09/K07 不做 free-text parser。
- `display_value` / `display_unit` 只能作为展示建议，不能替代 `original_value` / `original_unit`。
- product dimensions、package dimensions、product weight、package/shipping weight 必须分区显示和分区保存。

# 3. UI 输入分区

## A. Product dimensions

Purpose: 输入产品本体尺寸，只生成 `dimensions_json` payload。

Required UI elements:

- `length`
- `width`
- `height`
- `diameter`
- `thickness`
- unit selector
- `dimension_order`
- `dimension_format`
- `source_text`
- warnings/errors

Rules:

- 单位 selector 只允许 K09 length units: `mm`, `cm`, `m`, `in`, `ft`。
- `dimension_order` 必须表达来源顺序；如果来源只写 `10 x 5 x 3 cm` 且没有明确 L/W/H，必须保留 ambiguous 状态。
- `dimension_format` 可记录 `l_w_h`, `length_diameter`, `single_dimension`, `ambiguous_3_part` 等格式。
- Product dimensions 不得回填 package dimensions。

## B. Package dimensions

Purpose: 输入包装或运输尺寸，只生成 `package_dimensions_json` payload。

Required UI elements:

- `package_length`
- `package_width`
- `package_height`
- `package_diameter`
- unit selector
- `package_dimension_order`
- `package_dimension_format`
- `package_source_text`
- warnings/errors

Rules:

- 单位 selector 只允许 K09 length units: `mm`, `cm`, `m`, `in`, `ft`。
- package dimension order 和 format 独立于 product dimension order 和 format。
- Package dimensions 不得回填 product dimensions。

## C. Product weight

Purpose: 输入产品本体重量，只生成 `weight_json` payload。

Required UI elements:

- `net_weight`
- `gross_weight`
- unit selector
- `source_text`
- warnings/errors

Rules:

- 单位 selector 只允许 K09 weight units: `g`, `kg`, `oz`, `lb`。
- `net_weight` 和 `gross_weight` 必须可区分。
- Generic `weight: 2 lb` 不得自动写入 `net_weight`。

## D. Package / shipping weight

Purpose: 输入包装或运输重量，只生成 `package_weight_json` payload。

Required UI elements:

- `package_weight`
- `shipping_weight`
- unit selector
- `source_text`
- warnings/errors

Rules:

- 单位 selector 只允许 K09 weight units: `g`, `kg`, `oz`, `lb`。
- `package_weight` / `shipping_weight` 不得回填 product `net_weight` / `gross_weight`。

## E. Future optional volume

Purpose: future-only 输入容量或体积。当前 K07A/B 可不实现。

Required future UI elements:

- `capacity` / `volume`
- unit selector
- future-only note

Rules:

- 单位 selector future-only 支持 `ml`, `l`, `fl_oz`。
- Future-only 不代表现在 K07 必须实现，不新增 DB 字段，不接 runtime。

## F. Future optional temperature

Purpose: future-only 输入温度值或温度范围。当前 K07A/B 可不实现。

Required future UI elements:

- `temperature_value` / range
- unit selector
- context selector
- future-only note

Rules:

- 单位 selector future-only 支持 `c`, `f`。
- context selector 必须明确 `operating`, `storage`, `warning`, `performance` 或其他 reviewed explicit context。
- Future-only 不代表现在 K07 必须实现，不新增 DB 字段，不接 runtime。

# 4. UI 必须防止的错误

- 不把 package dimensions 当 product dimensions。
- 不把 product dimensions 当 package dimensions。
- 不把 package weight 当 product net weight。
- 不把 generic weight: 2 lb 当 net_weight。
- 不从 10 x 5 x 3 cm 自动推断 L/W/H。
- 不把 unsupported unit 静默转成默认单位。
- 不把 missing value / missing unit 当成 0。
- 不允许 AI draft 自动覆盖人工确认值。
- 不让 `display_market` 或 `target_market` 改写 `original_value` / `original_unit`。
- 不在只有 `source_text` 的情况下声称 K07/K09 已经解析 free text。

# 5. Operator interaction

- operator enter: 操作员直接输入数值、单位、来源文本、format/order、display market 和 review intent。
- AI draft shown as draft only: AI 结构化输出只能显示为 draft / `needs_review`，不得自动成为 reviewed value。
- accept: 操作员明确接受 draft 或当前输入后，payload 可进入 reviewed 相关状态，并应保留来源。
- edit: 操作员修改数值、单位、order、format 或 context 后，修改值优先于 AI draft。
- reject: 操作员拒绝 draft 后，draft 不得用于 downstream payload。
- mark not_applicable: 操作员明确标记字段或 payload 对当前产品/context 不适用，不能用 0 表示。
- request review: 操作员将 payload 标记为需要 reviewer 处理，尤其是 ambiguity、unsupported unit、product/package conflict 或 net/gross ambiguity。
- rerun validation: 操作员修正后可重新触发 future validation/gate check；K09G 只定义状态，不实现 runtime validation。

# 6. K07 与 K09 helper 的关系

- K09 `unit_conversion.py` 和 `unit_payloads.py` 是 module-local helper。
- K09G 不表示它们已经接入 runtime。
- K07 前端未来可参考 K09 payload contract。
- K07 不直接 import backend helper。
- K07 不直接写 DB。
- K07 未来应通过 Barong backend API，但 API registration 当前仍未完成。
- K07 hidden UI shell 可以展示 payload shape、warnings/errors 和 review state，但不能暗示 K09I runtime integration 已完成。
