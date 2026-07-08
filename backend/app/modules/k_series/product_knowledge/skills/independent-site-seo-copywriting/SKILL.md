---
name: independent-site-seo-copywriting
description: 【独立站 · 产品页 SEO 文案与谷歌排名】撰写/优化独立站（Shopify/WooCommerce 等 DTC 站点）产品页与配套内容，匹配谷歌 2025-2026 排名体系：核心更新后的 helpfulness 站点级信号、E-E-A-T 第一手体验证据、Product/Offer 结构化数据、AI Overviews 与 AI Mode 的引用机制（GEO/AEO）。只要用户提到独立站文案、产品页 SEO、Shopify 文案、产品描述、落地页文案、谷歌排名、谷歌收录、AI Overviews、GEO、AEO、title tag、meta description、集合页/类目页文案、购买指南，即使没有明说"写文案"，都应使用本 skill。
---

# 独立站产品页文案与 SEO（Google 2025-2026 + AI Overviews 适配版）

## 排名机制一页纸（为什么这样写）

1. **Helpfulness 是站点级信号**：2024 年 3 月起 Helpful Content 系统已并入核心算法，按**整站**评估质量——大量厂商模板化的稀薄产品页会拖垮全站，而不只是那几页。所以"每页文案独一无二"不是修辞，是生死线。
2. **E-E-A-T 与第一手体验**：谷歌评论系统奖励**能证明真用过**的内容——实拍图/视频、实测数据、诚实的缺点、与替代品的对比。改写供应商规格表的页面会被过滤（不是惩罚，是"沉底"）。
3. **AI Overviews / AI Mode 的引用逻辑（2025-2026 已验证的部分）**：AI Mode 用 query fan-out（把一个问题拆成多个子查询分别检索再拼装答案），所以**被引用 ≠ 排名高**——约 80% 被 AI Overview 引用的页面并不在该词自然前 10。谷歌官方明确：无需任何特殊标记或"AI 专用 schema"，只要可索引、可出摘要。经证实有效的做法：① 内容里放**可引用的统计数字**（普林斯顿 GEO 论文：AI 可见度 +30-40%，最被复现的发现）；② **自包含的可抽取段落**（问题式小标题 + 首句直接给答案 + HTML 表格）；③ **全网品牌提及比外链更相关**（Ahrefs 7.5 万品牌研究：相关系数 0.664 vs 0.218）。
4. **电商引用的关键洞察（Aleyda Solis 研究）**：AI 答案引用最多的电商页面往往**不是产品页**，而是尺码表、退换货政策、购买指南、兼容性说明——"回答用户决策问题的页面"。但 AI 带来的**流量**却更多落在产品页。结论：产品页负责接单，围绕它建一圈决策支持内容负责被 AI 引用并内链导流。
5. **Shopping Graph 与 Merchant Center**：Gemini 回答购物问题时查询的是 Shopping Graph（500 亿+ 商品条目）。**没投广告也要接 Merchant Center**，feed 完整度 + feed/页面/结构化数据三者一致，是进入 AI 购物表面的前提，常常比传统页面 SEO 更起决定作用。

算法细节与来源见 [references/algorithm-notes.md](references/algorithm-notes.md)（改版前、或用户质疑某条规则时先读它）。

## 开工前必须收集的输入

- 产品事实：材质、尺寸、兼容性、认证、差异化（要数字和实测，不要形容词）
- 平台（Shopify/WooCommerce/其他）、目标市场与语言（默认美国英文）
- 是否有真实的第一手素材：实拍图、测试数据、创始人笔记、已有评论——没有就明确告诉用户哪些声明写不了
- 目标关键词或竞品 URL；现有页面 URL（优化场景）
- 是否已接 Google Merchant Center

## 工作流

### Step 1 — 意图分层与页面分工

先画内容地图，再动笔：

| 搜索意图 | 承接页面 | 例子 |
|---|---|---|
| 交易型（buy/型号词/品牌+品类） | 产品页 PDP | "24oz insulated water bottle" |
| 对比/选购型 | 购买指南、对比页 | "best water bottle for hiking"、"X vs Y" |
| 决策支持型 | 尺码表、兼容性、退换货、FAQ 页 | "does X fit Y"、"return policy" |

**不要让产品页去抢信息型关键词**——那是指南页的活，指南页内链到 PDP。这个 hub 结构同时是 AI 引用的主要入口。

### Step 2 — Title tag / H1 / URL

- Title tag ≤60 字符：`[品牌] [产品名] – [关键属性/用途] | [店铺名]`，属性词（材质、尺寸、"for X"）前置，每页唯一
- H1 = 产品名，与 title tag、Merchant Center feed 标题保持一致（Shopping Graph 靠一致性对齐实体）
- URL 短、含品类词、全站唯一

### Step 3 — 产品描述（信息增益是核心标准）

铁律：**永远不用厂商描述原文或轻度改写**——那是和几百个站雷同的近重复内容。每段文案自问："这句话是否提供了搜索结果里其他页面没有的信息？"（信息增益）。必须覆盖：

1. **这是给谁的、解决什么问题**（首段，直接了当）
2. **第一手体验证据**：实测数据（"实测 -5°C 保温 11.5 小时"）、尺寸实测、使用感受、诚实的适用边界（"不适合 XX 场景"——这是 E-E-A-T 信号，也建立信任）
3. **可引用的具体数字**：GEO 已验证的最强杠杆，把模糊形容词全部换成数字
4. **规格用 HTML 表格**呈现（不是图片），方便 AI 抽取
5. 品牌自己的声音，覆盖属性实体（材质/尺寸/兼容/认证），与 schema 严格一致

**Example:**
- 差: `This premium water bottle is made of high-quality stainless steel and keeps your drinks cold. Perfect for everyone!`
- 好: `Built for 12-hour shifts and long trail days: in our lab test, ice water stayed below 40°F for 11.5 hours at 75°F room temperature. The 24oz body fits standard car cup holders (base diameter: 2.87"). Not recommended for carbonated drinks — the leakproof lid seals too tight for pressure release.`

### Step 4 — 面向 AI 抽取的排版（chunk-level 优化）

AI Mode 按"段落块"检索，每一块都要能脱离上下文独立成立：
- 用**问题式 H2/H3**（"How long does it keep drinks cold?"），首 1-2 句直接给答案，再展开
- 每个 H2 下的内容自包含：不写"如上所述"，关键实体（品牌名、产品名）在块内重现
- FAQ 富媒体结果已死（2026 年 5 月起完全停止展示），但**页面上的 FAQ 内容本身仍然重要**——它是长尾匹配和 AI 抽取的原料，继续写，只是别指望搜索结果里出现下拉。

### Step 5 — 结构化数据（与可见内容、feed 三方一致）

产品页（merchant listing 级别）必配：
- `Product` + `Offer`（price、availability 必填）+ `GTIN/MPN` + `shippingDetails` + `hasMerchantReturnPolicy`
- 有评论则加 `Review` + `AggregateRating`（评论文本必须真实且页面可见，schema 与可见内容不符会吃手动处罚）
- 多变体：遵循谷歌 product variant 标记规范；默认一个父产品一个规范 PDP，只有当变体有独立搜索需求（如颜色词）才独立收录
- 注意：schema 与 AI 引用是**相关而非因果**（Ahrefs 实验：补 schema 不直接带来引用）——它的作用是资格与一致性，不是排名捷径

### Step 6 — 站内评论与 UGC

评论文本必须**服务器端渲染、可被索引**（不是纯 JS 挂件）——这是免费的、带体验信号的独特内容，也是 Rufus 式 AI 回答的原料。引导买家在评论里描述场景与用途（评论问卷引导："你用它做什么？"）。

### Step 7 — 决策支持内容层（AI 引用的主入口）

给每个核心产品线配齐并内链到 PDP：
- 尺码/选型指南、兼容性对照表、"X vs Y" 对比页、"best X for [人群/场景]" 指南、清晰的运费与退换货页
- 这些页面用 Step 4 的 chunk 格式写，放实测数据和统计数字
- 内链：面包屑 + 指南→PDP + 相关产品，锚文本自然、不堆精确匹配关键词

### Step 8 — 技术卫生检查（交付时附清单）

- [ ] 分面导航（filter 组合 URL）：无搜索需求的参数组合用 robots.txt 屏蔽；canonical 不省爬取预算，别只靠它
- [ ] Shopify：保留 `/collections/x/products/y` → `/products/y` 的默认 canonical；tag 页与 `?variant=` 参数做 canonical 纪律
- [ ] 分页类目页是纯链接可爬（不是仅 JS 无限滚动），每页自我 canonical
- [ ] Core Web Vitals（含 INP）达标——它是转化杠杆和卫生分，不是排名救命稻草，别本末倒置
- [ ] Merchant Center feed 与页面价格/库存实时同步

### Step 9 — 站外提醒（写进交付建议，不属于文案本身）

全网品牌提及（数字 PR、媒体测评、Reddit/YouTube 出现）与 AI 可见度的相关性是外链的 3 倍。交付时提醒用户：文案做到位后，最大的 AI 曝光增量来自站外品牌提及建设。

## 交付格式

```
# [产品名] 独立站产品页方案
## 1. Title tag + Meta description + H1 + URL（含字符数）
## 2. 产品页正文（按 chunk 结构，含规格 HTML 表格）
## 3. 页面 FAQ（6-10 组）
## 4. JSON-LD 结构化数据（Product/Offer/Review 完整代码）
## 5. 决策支持内容层规划（需要配的指南页清单 + 各页目标关键词）
## 6. 内链方案
## 7. 技术卫生检查清单结果
## 8. 缺失的第一手素材清单（哪些声明需要用户补证据）
```

## 红线（会吃算法过滤或手动处罚）

规模化量产模板文案（scaled content abuse 垃圾政策，2025 年中起有手动处罚案例，AI 或人写都算）；厂商描述复制（近重复→整站质量沉底）；doorway 页（同一产品换地名/关键词批量落地页）；关键词堆砌与精确匹配锚文本滥用；schema 与可见内容不符；虚假/激励性评论标记；托管第三方优惠券/联盟内容区（site reputation abuse，手动处罚）。
