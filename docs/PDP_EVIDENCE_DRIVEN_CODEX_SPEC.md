# PDP 第二轮大改 · Codex 规格(证据驱动 + Bug 修复)

> 背景:第一轮 PDP 大改上架的测试品(Woo #3803,SKU CCD-001,`portable-cassette-stove...`)经严格审计,判为 ~80/100。核心病根:**管线在"无中生有地编声明和配图",而不是"拿证据说话"**——抗风无证据、幽灵卖点、FAQ 复读、图片证明不了卖点。本轮把管线改成**证据驱动生成**,并修掉一批 SEO/schema/overlay 致命 bug。
>
> **注意:无远程仓库,不需要 push。** 本仓库同时被 Claude 改 `product-image-art-direction/SKILL.md`(图组指令契约)与家规 CSS,避开该文件。测试品 #3803 **必须保留不动**(用户要对比两次上架)。

---

## Part 0 — SEO 体检结论(修复目标的量化依据)
真实抓取 #3803 的结论:
- `<title>` / meta description ✅ 已 OK。
- **Product JSON-LD `offers.price = null` / `priceCurrency = null`** ❌❌ 致命:无价格=丢富摘要/Shopping 资格。
- `additionalProperty = 0` ❌:12 条真规格没进 schema(MU 插件钩子没对上,疑似站点用 Yoast 出 Product schema,插件挂的是 WooCommerce 钩子)。
- Product `description` 断词("takes **you**Packable")❌:schema 描述还在用剥标签老路,没用干净 `seo.meta_description`。
- Product `name` = 超长 H1 + 未转义 `&amp;` ⚠️:与短 `<title>` 不一致。
- URL slug 96 字符 / 15 词 ❌:未用 K 已生成的短 `seo.url_slug`。
- FAQPage 内容复读参数 ⚠️:低质,谷歌负信号。

---

## Part 1 — Bug 修复(独立、优先、可并行)

### 1.1 F→K 导入 scope 占位(致命,阻断全链)
`import-to-k` 建的 K 产品 scope 写成占位 `workspace_key=default_independent_store` / `scope_mode=adapter_pending`,而 K API `_scope_context` 认真租户 `workspace_key=org_4b828c8fdf...` / `scope_mode=production` → 产品建成但 **K API 404**。修:F 导入用真租户 scope(参考 `r_to_k_transfer.py` 的 scope 处理)。`backend/app/modules/f_series/enrichment/service.py` 的 `import_candidate_to_k`。

### 1.2 F→K / R→K 导入不建 variant
导入不建 `k_product_knowledge_variants` 行 → 图片上传/存图 404(`_variant_by_sku` 不自动建)。修:导入时按 `product.sku`(SKU 发号器结果)建默认 variant 行。

### 1.3 Product schema 无价格(致命 SEO)
Product JSON-LD `offers.price`/`priceCurrency` 为 null。定位:站点侧 Product schema 由 **Yoast** 还是 WooCommerce 输出?`kp-product-structured-data.php` 目前挂 `woocommerce_structured_data_product`,若站点用 Yoast,钩子不触发。修:
- 让 MU 插件挂**站点实际生效的 schema 过滤器**(Yoast: `wpseo_schema_product` / `wpseo_schema_graph_pieces`;或确认 WooCommerce 原生 schema 是否被 Yoast 关掉)。
- **必须保证 `offers.price` = 售价(sale 优先,否则 regular)、`priceCurrency`、`priceValidUntil`、`availability`、`itemCondition` 齐全**。这是富摘要硬要求。

### 1.4 Product schema 补规格(additionalProperty)
同 1.3 的钩子修好后,把 `_kp_additional_property`(n8n 已写)映射进 Product schema 的 `additionalProperty`(PropertyValue name/value/unitText)。

### 1.5 Product schema description 断词
schema `description` 改用 **`seo.meta_description` 或专门的纯文本摘要**,禁止"剥 HTML 标签拼接"(现在粘成 "youPackable")。

### 1.6 Product schema name 清洗
schema `name` 用**干净短标题**(与 `<title>` 一致或去掉品牌后缀),HTML 实体解码(`&amp;`→`&`)。

### 1.7 slug 用短 url_slug
P 上架设 WooCommerce 产品 slug = K 文案的 **`seo.url_slug`**(短,3-5 词),不要让 WP 用长 H1 兜底。`assemble.py` / n8n 转 Woo 节点补 `slug` 字段。

---

## Part 2 — 证据驱动架构(核心,治本)

**总纲:卖点是脊椎,一切要有证据。** 数据模型分三层,严格分家:
1. **规格 `structured_specs_json`**(事实):抓取 OR 运营手填。流向=规格表 + Woo 属性 + schema。点火方式、燃料、材质、容量等都住这。
2. **卖点 `selling_points`**(带证据的营销声明):脊椎。流向=文案/卖点网格/**图片证明**/标题。
3. **痛点/FAQ 来源**(真实买家问题):Serper 抓,不复读规格。

### 2.1 卖点录入 + 人工审查门(新功能)
- **K 手动上传路径**:运营页出现**两个独立区**——「卖点」区 + 「规格」区(写 `structured_specs_json` 的手填字段)。别把规格塞进卖点。
- **F 自动路径**:AI 从抓取数据 + 规格**生成候选卖点** → **人工审查门**(逐条 approve / edit / reject)→ 落成 `selling_points_approved`(唯一权威)。
- 审查门做成 K 工作流的一个 gate(类似风险词审查)。下游**只读已审卖点**。

### 2.2 卖点必须挂证据(治"抗风"虚假承诺 + 幽灵卖点)
- 每条卖点带一个 `evidence` 字段,来源枚举:`spec:<field>` / `verified_feature:<id>` / `operator_fact`。
- **无证据不得生成/通过**:AI 生成卖点时,若某声明(如 windproof)在规格/特征里找不到支撑,**不许输出该卖点**(或标 `unverified` 走人工补证据)。抗风必须有"防风设计"证据才成立。
- **标题↔正文一致性门**:`seo.title` / H1 里每个卖点词,必须在**已审卖点或正文**里出现且有支撑,否则从标题剔除(治 "home use" 幽灵词;顺带 home use 对燃气炉有室内 CO 安全风险,更该剔)。

### 2.3 图片严格读卖点 + 每张图证明一条卖点(治"图片零信息/全摆拍/白底泛滥")
- **图片指令(image-brief)生成时,必须把「已审卖点」喂进去**(现在没喂,导致图片和卖点脱节)。
- **图组重配比(硬约束)**:**白底 `main` 只留 1 张**;其余全部是**证据图/真实场景图/信息图**,不许一堆白底副图。
- **每张证据图对应一条卖点,把证据拍出来**(proof shot):
  - "抗风" → 火焰在草木被风吹弯时依然稳定
  - "户外烧饭" → **真营地**(帐篷/山景/黄昏)**真点火、锅里真在烧、冒热气**
  - "收纳小" → 嵌套网袋、挨着背包对比
  - "8件套" → 配件平铺开箱
- **场景图真实使用**:露营炊具就要有真点火/真烹饪/真露营环境,禁止全是干净摆拍。(与 SKILL.md 的反假图层铁律配合:image-to-image、同一打光、真实接触阴影、自发光溢出。)

### 2.4 尺寸图修复 + 挪进主副图
- **位置**:`dimension` 图从 description 挪进 **gallery(主副图)**。
- **单位英制**:美国市场,叠字用 **inch / lb**(overlay 渲染时换算 cm→in、kg→lb;`structured_specs` 存公制,展示层换算)。
- **尺寸线几何吸附**:现在线坐标是作图 AI 瞎猜的归一化值,对不上产品。修:**叠字合成器自动检测产品实际轮廓/包围盒**(渲染出的干净基底图上做前景/边缘检测),把尺寸线**吸附到产品真实边缘**,不再用 AI 猜的坐标画线。
- **文字居中不出框**:overlay 文本框自适应、不溢出、与引线锚点对齐。

### 2.5 info_overlay 修 callout + spec 两类(现在只有 dimension 生效)
三类信息图里 `feature_callout` / `spec` 的文字没渲染上(只有 `dimension` 成功)。排查 `info_overlay.py` 的 callout/spec 分支(字段解析、锚点、绘制),保证三类都能把真规格标注叠上。

### 2.6 FAQ 改真实痛点(Serper,治复读机 FAQ)
- **新增 FAQ 生成阶段**:上架前用 **Serper** 爬谷歌该品类的 **People Also Ask + 真实买家提问/论坛/差评痛点** → 聚类 → 生成**答真问题**的 FAQ(如"高海拔火力会不会变弱""气罐低温打不着火""能不能过安检托运")。
- **禁止复读规格**:FAQ 答案不许只是把规格换个问法复述;要答**搜索意图里的真实顾虑**。
- 复用现有 SEO 系列的 Serper 通道(见 [[n8n-existing-estate]] 的 SEO 工作流 / 已有 serper 调用)。
- FAQPage schema 只在 FAQ 是真问答时输出(低质就别输出,避免谷歌负信号)。

---

## 硬约束(全任务)
- **别造假**:抓不到/无证据的规格与声明一律留空/不生成,不编数值。
- P 上架保持 fail-safe:任一环节失败降级继续 + 记日志,不阻断上架。
- 品牌硬门不动(schema 品牌永远 Barong Yekhna)。
- **#3803 不许动**;重上架产生新 SKU(CCD-002)+ 新 URL。
- 迁移前先 `ls` versions 找 head 从它分叉(单 head);迁移不自动跑。测试 `bash scripts/run_backend_tests.sh unit`。
- 与 Claude 侧契约:SKILL.md 会按本文档 2.3/2.4 重排图组并输出 proof-shot 意图 + overlay(imperial、gallery 定位);字段/枚举定稿后与 Claude 对齐。

## 交付
本地分支(不 push)+ 单测全绿 + 每任务一句根因与修法。
