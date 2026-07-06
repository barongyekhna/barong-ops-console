# R-A 供应商关键词与变体匹配 Skill

## 目标

R-A 利润测算只寻找可销售的同类产品供应商，不寻找品牌同款。所有 Serper、1688、拼多多、淘宝、京东搜索词必须去掉品牌名、店铺名、ASIN、UPC、专利词和明显商标词。

## 关键词抽取

- 从亚马逊原标题和中文名中抽取产品主体词，例如 `neck fan` / `挂脖风扇`、`shade sail` / `遮阳帆`。
- 保留会影响成本的属性：材质、容量、功率、功能、套装数量、尺寸、颜色只在必要时保留。
- 不要把完整标题当关键词；搜索词长度应短，优先 2 到 8 个核心词。
- 不要在关键词中包含品牌。品牌只作为侵权风险和搜索禁用词保存。
- 如果标题里有多个用途，以产品实体为准，不要使用场景词替代产品词。例如 `bakery label printer` 的产品实体是 `label printer` / `标签打印机`，不是 `bakery` / `面包`。

## 供应商搜索

- 1688 优先词：`{中文主体词} 一件代发`、`{中文主体词} 一件起批`、`{中文主体词} 批发 厂家`。
- 零售平台补充词：`拼多多 {中文主体词}`、`淘宝 {中文主体词}`、`京东 {中文主体词}`。
- 平台搜索页可以保留给人工扩展选择，但正式利润只使用具体产品详情页的价格。
- 供应商详情候选必须尽量达到 3 到 5 条；不足 3 条时只展示候选，不生成正式利润结论。

## 匹配守门

- 供应商标题、摘要或页面文本必须与产品主体一致。
- 发现品牌词时视为侵权风险，不能用于利润计算。
- 发现相互冲突的形态时视为错配，例如 `挂脖` 与 `挂腰`、`餐桌` 与 `桌布`、`遮阳帆` 与 `遮阳伞`。
- 亚马逊是多件装时，供应商价格必须按同等数量换算；无法确认数量时不计算利润。
- 按尺寸销售的产品必须对齐尺寸，例如遮阳帆、桌布、胶带、围栏、软管、地垫。无法确认尺寸时不计算利润。
- 尺寸单位允许换算，英寸、英尺、厘米、米统一换算为厘米。

## 供应商详情匹配 JSON

每一个供应商详情页都必须再做一次 DeepSeek 判断。DeepSeek 的职责是动态理解任意产品，不允许只依赖固定产品词典。代码只负责校验 JSON、执行硬阻断和成本换算。

需要返回严格 JSON，不要解释文字：

```json
{
  "match_status": "match",
  "match_score": 88,
  "match_reason": "供应商产品主体、数量和尺寸与亚马逊产品一致。",
  "amazon_subject": "挂脖风扇",
  "supplier_subject": "挂脖风扇",
  "same_product_type": true,
  "brand_risk": false,
  "brand_terms_found": [],
  "shape_conflict": false,
  "quantity": {
    "status": "aligned",
    "amazon_pack_count": 2,
    "supplier_pack_count": 1,
    "cost_multiplier": 2,
    "reason": "亚马逊为2只装，供应商为单只价格，成本乘以2。"
  },
  "dimensions": {
    "status": "not_required",
    "cost_multiplier": null,
    "reason": ""
  },
  "warnings": []
}
```

字段约束：

- `match_status` 只能是 `match`、`review`、`mismatch`。
- `match` 才允许进入正式利润计算。
- 无法确认是否同类时必须返回 `review`，不能猜测通过。
- 发现不是同类产品、品牌同款风险、形态冲突时必须返回 `mismatch`。
- 多件装或尺寸销售无法确认时必须返回 `review`。
- `cost_multiplier` 只允许用于数量或尺寸换算，不允许用于乐观估算。

## DeepSeek 输出 JSON

需要返回严格 JSON，不要解释文字：

```json
{
  "brand": "需要禁用的品牌名",
  "forbidden_terms": ["品牌或商标词"],
  "product_type": "short English product type",
  "product_type_zh": "中文产品主体词",
  "core_keywords_zh": ["中文主体词", "必要属性词"],
  "search_queries": {
    "1688": ["中文主体词 一件代发", "中文主体词 一件起批", "中文主体词 批发 厂家"],
    "pdd": ["拼多多 中文主体词"],
    "taobao": ["淘宝 中文主体词"],
    "jd": ["京东 中文主体词"]
  },
  "pack_count": 1,
  "dimensions": {
    "raw": ["10 x 12 ft"],
    "requires_alignment": false
  },
  "attributes": {
    "material": "",
    "function_terms": []
  }
}
```
