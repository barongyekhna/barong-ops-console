# K09 Unit Conversion Baseline

Status: K09A unit storage and conversion baseline, pending owner review.

Date: 2026-06-12.

# 1. K09A 目标

K09A 只定义单位存储与换算基准。

K09A 不写代码、不改 migration、不改 runtime。

K09A 是以下后续工作的前置材料：

- K09B payload contract.
- K09C conversion module.
- K09D tests.
- K07 unit input UI.
- K10 AI unit output rules.

# 2. 设计依据

- K04 已定义 unit and market conversion model。
- K08 已定义 dimensions / weight 字段体系。
- English canonical 是主记录，但单位原始输入必须保留。
- AI 不得猜测尺寸、重量、体积、包装尺寸或温度。
- 人工确认值优先级高于 AI draft。
- K09A 不接 DeepSeek live。
- K09A 不接 frontend。
- K09A 不接 P-series。
- K09A 不接 staging/production。

# 3. 支持单位

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

Optional volume:

- `ml`
- `l`
- `fl_oz`

Optional temperature:

- `c`
- `f`

K09A 只定义支持单位，不实现换算代码。

不支持的单位必须进入 validation error / warning。不要把未知单位静默当成默认单位。

# 4. 核心存储原则

每个 structured unit payload 必须尽量保留：

- `original_value`
- `original_unit`
- `normalized_metric_value`
- `normalized_metric_unit`
- `normalized_imperial_value`
- `normalized_imperial_unit`
- `display_market`
- `conversion_source`
- `conversion_precision`

Storage rules:

- `original_value` / `original_unit` 不得被系统静默改写。
- normalized values 是系统计算结果，不替代原始值。
- `conversion_precision` 必须记录 rounding / precision。
- `reviewer_corrected` 值必须保留来源。
- missing value 不能由 AI 补成真值。
- `unknown` 不等于 `0`。

Recommended `conversion_source` values:

- `operator_entered`
- `supplier_imported`
- `system_converted`
- `reviewer_corrected`
- `unknown`

# 5. K09 涉及字段

- `dimensions_json`: 产品本体尺寸 payload，应保存 length / width / height 的原始单位、metric normalized 值、imperial normalized 值、display market、conversion source、precision 和 review status。
- `package_dimensions_json`: 包装尺寸 payload，规则同 `dimensions_json`，但代表 shipping/package context，不得与产品本体尺寸混用。
- `weight_json`: 产品本体重量 payload，应保存原始重量、原始单位、metric normalized 值、imperial normalized 值、display market、conversion source、precision 和 review status。
- `package_weight_json`: 包装重量 payload，规则同 `weight_json`，但代表 shipping/package context。
- dynamic attributes 中的 `attribute_unit`: category-specific、marketplace-specific、B2B 或 Amazon-like product type 字段里的单位字段；K09 后续可读取并校验，但 K09A 不改变 attribute schema。
- future volume payload: future category or marketplace fields may need `ml` / `l` / `fl_oz`; K09A 只定义支持单位和存储原则，不新增 DB 字段。
- future temperature payload: future category or compliance fields may need `c` / `f`; K09A 只定义支持单位和存储原则，不新增 DB 字段。

# 6. K09 不做事项

- 不改 K05 migration。
- 不新增 DB 字段。
- 不改 K06 backend runtime。
- 不接 K API。
- 不接 frontend。
- 不运行 staging/production。
- 不接 live provider。
- 不读取 P workflow。
- 不让 n8n 直接写 Barong DB。
