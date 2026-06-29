# R 系列未来系统功能建议

调研日期：2026-06-29  
主题：R 系列未来系统功能建议  
边界：只做功能建议和评分模型草案，不写代码，不设计数据库。

## 1. R 系列定位

R = Research。R 系列应成为 Barong 自动化体系的上游“产品机会判断系统”，负责把全球市场信号、Amazon 信号、SEO/GMC/Ads 信号、供应链信号和风险信号统一成可评分、可淘汰、可流转的产品机会。

R 系列不应该只是“爬榜工具”，而应该是：

1. 机会发现系统。
2. 风险排除系统。
3. 利润判断系统。
4. 差异化判断系统。
5. 渠道路径判断系统。
6. K / I / P / GMC / SEO 的上游准入系统。

## 2. 系统阶段建议

| 阶段 | 名称 | 目标 | 输出 |
|---|---|---|---|
| R0 | Candidate Intake | 收集候选产品和种子关键词 | candidate_pool |
| R1 | Hard Exclusion | 先排除高风险和明显不适合 | rejected / needs_review / continue |
| R2 | Amazon Research | 判断平台需求、竞争、利润、FBA、差异化 | amazon_scorecard |
| R3 | Independent Site Research | 判断 SEO、Ads、GMC、内容、B2B、品牌化 | site_scorecard |
| R4 | Supply Chain Review | 判断 MOQ、成本、交期、认证、工厂改良 | supply_chain_scorecard |
| R5 | Final Recommendation | 给出渠道路径和优先级 | final_recommendation |
| R6 | Downstream Handoff | 输出给 K/I/P/GMC/SEO | handoff_package |
| R7 | Monitoring | 上架/测试后持续监控 | keep / iterate / kill |

## 3. 必备功能模块

### 3.1 亚马逊选品评分系统

功能：

1. 录入/抓取候选产品、ASIN、关键词、类目。
2. 记录 BSR、评论数、评分、价格、估算销量、估算收入、变体数量。
3. 分析首页竞品评论墙、品牌集中度、广告位、listing 质量。
4. 挖掘差评和 QA，输出痛点主题。
5. 计算 FBA 适配、物流风险、退货风险、广告后贡献利润。
6. 输出 Amazon final_score 和淘汰理由。

关键依据：Amazon Product Opportunity Explorer 提供 niche、需求、竞争、评论、价格、退货等机会信号；BSR 只能代表销售排名趋势，不等于机会本身。[A01][A03]

### 3.2 独立站选品评分系统

功能：

1. 记录关键词簇、搜索意图、长尾词、SERP 类型。
2. 判断 SEO 难度、内容潜力、FAQ 潜力、比较页潜力。
3. 判断 Google Ads / Shopping Ads 的 CPC、竞争、Top of page bid、广告后利润。
4. 判断 GMC feed 准备度和 misrepresentation 风险。
5. 判断页面信任要求、品牌化、复购、B2B 询盘潜力。
6. 输出 independent_site_score 和渠道建议。

关键依据：Google Merchant Center 对商品数据和落地页一致性要求严格；misrepresentation 会导致展示受限或账号风险；SEO 应同时看搜索意图、难度、流量潜力和商业价值。[G01][G02][S03][S04]

### 3.3 市场需求判断

数据：

1. Amazon BSR、销量估算、POE demand。
2. Google 搜索量、趋势、长尾簇。
3. 社媒讨论量和痛点语言。
4. Reddit/Quora/YouTube/TikTok/Pinterest 的真实问题。

判断：

1. 多源一致为高需求。
2. 只有社媒短爆为低可信趋势。
3. 只有搜索无购买意图为内容机会，不一定是产品机会。
4. 只有 Amazon 销量无站外搜索，适合平台，不一定适合独立站。

### 3.4 竞争强度判断

Amazon 竞争：

1. top10 评论中位数。
2. 评分分布。
3. 品牌集中度。
4. 广告密度。
5. 标题密度。
6. 价格战强度。

独立站竞争：

1. SERP 前 10 域名强度。
2. 内容深度。
3. Shopping 竞价强度。
4. CPC 和 Top of page bid。
5. 竞品页面信任度。

### 3.5 利润空间判断

R 系列必须算广告后贡献利润，而不是只算毛利。

Amazon:

`target_price - COGS - first_mile - FBA_fee - referral_fee - storage_estimate - return_cost - coupon - PPC_cost_per_order`

独立站:

`AOV * gross_margin - CPC / conversion_rate - shipping_subsidy - payment_fee - return_cost - content_or_creator_cost_allocated`

若贡献利润为负，默认淘汰。若只有规模后才盈利，中小卖家不优先。

### 3.6 SEO 机会判断

功能：

1. 关键词分组：商业词、信息词、比较词、问题词、B2B 词。
2. SERP 类型判断：电商页、教程页、论坛页、视频页、供应商页。
3. 内容地图：产品页、集合页、FAQ、安装指南、对比页、案例页。
4. 商业潜力评分：内容是否能自然导向产品。

### 3.7 广告成本判断

功能：

1. Amazon CPC 和 ACOS/TACoS 预估。
2. Google CPC 和 Top of page bid 预估。
3. 关键词按意图分层：购买、比较、学习、B2B、品牌。
4. 用保守转化率计算广告后利润。
5. 输出可投、谨慎、不可投。

### 3.8 合规风险判断

功能：

1. 类目门槛：Amazon gating、危险品、FBA 限制。
2. 认证风险：电池、无线、高压、儿童、食品接触、医疗、个护。
3. IP/专利风险：品牌名、兼容性描述、外观、结构。
4. GMC/Ads 政策：misrepresentation、夸大功效、退换货政策、联系信息、价格一致性。
5. 输出：low / medium / high / reject。

### 3.9 差异化机会判断

功能：

1. 差评主题聚类。
2. QA 购买前疑问聚类。
3. 竞品 listing 质量差距。
4. 可改良点分类：材质、尺寸、结构、接口、套装、说明、包装、配件、质检。
5. 工厂可实现性评分。

### 3.10 B2B 潜力判断

功能：

1. 是否可批发。
2. 是否可定制。
3. 是否有行业应用。
4. 是否需要 datasheet / spec / manual / case study。
5. 是否适合 RFQ。
6. 是否有 supplier / manufacturer / custom / wholesale / bulk 关键词。

### 3.11 产品进入 K 系列的准入门槛

必须具备：

1. seed_keywords。
2. Amazon keywords 或 Google keywords。
3. search intent 分类。
4. commercial keywords。
5. long_tail_clusters。
6. negative_keywords 初稿。
7. competitor_keywords。

准入建议：关键词地图完整度 >= 70。

### 3.12 产品进入 I 系列的图片需求判断

必须具备：

1. 主图需求。
2. 场景图需求。
3. 细节图需求。
4. 尺寸/规格图需求。
5. 对比图需求。
6. 安装/使用步骤图需求。
7. 包装图需求。
8. 工厂/质检图需求。
9. 视频脚本需求。

准入建议：visual_demonstration_score >= 70。

### 3.13 产品进入 P 系列的页面生成条件

必须具备：

1. 产品标题。
2. 核心卖点。
3. 目标用户。
4. 痛点-解决方案。
5. 规格参数。
6. FAQ。
7. 对比信息。
8. 图片需求。
9. 信任模块。
10. 合规与政策信息。
11. CTA 类型：Buy / Quote / Contact / Sample。

准入建议：page_readiness_score >= 75。

### 3.14 产品进入 GMC / SEO 的前置条件

GMC：

1. 商品 title、description、image、price、availability、brand、GTIN/MPN。
2. 落地页价格、库存、运输、退货一致。
3. Contact、Shipping、Returns、Privacy、Terms、About 页面完整。
4. 无虚假承诺、无夸大功效、无仿牌误导。[G01][G02]

SEO：

1. 关键词簇。
2. 搜索意图。
3. 内容地图。
4. FAQ。
5. 内链目标。
6. 产品页和内容页的转化路径。

### 3.15 产品淘汰机制

淘汰类型：

1. hard_reject：合规/IP/危险品/侵权/利润为负。
2. soft_reject：需求弱、竞争强、内容弱、供应链不可控。
3. waitlist：趋势未确认、数据不足、需要观察。
4. iterate：需要改良产品、页面、关键词或供应链。
5. approved：进入样品、页面、广告或内容测试。

淘汰后保留：

1. 淘汰原因。
2. 触发指标。
3. 证据链接。
4. 是否可未来复查。
5. 复查条件。

## 4. R 系列评分模型草案

| 字段 | 方向 | 推荐权重 | 说明 |
|---|---|---:|---|
| demand_score | 越高越好 | 16 | 真实需求、销量、搜索、趋势 |
| competition_score | 越高越好 | 12 | 越高表示竞争越可进入 |
| profit_score | 越高越好 | 16 | 广告后贡献利润 |
| differentiation_score | 越高越好 | 14 | 可改良、可套装、可内容化 |
| compliance_risk_score | 越高越好 | 12 | 越高表示风险越低 |
| seo_score | 越高越好 | 10 | SEO 长尾和内容机会 |
| ads_score | 越高越好 | 8 | CPC 与转化经济性 |
| b2b_score | 越高越好 | 6 | 批发、定制、询盘 |
| brandability_score | 越高越好 | 4 | 品牌、系列、复购 |
| automation_fit_score | 越高越好 | 2 | 是否适合 K/I/P/GMC/SEO 自动化 |

## 5. final_recommendation 规则

| 条件 | 推荐 |
|---|---|
| 总分 >=85 且无硬风险 | priority_test |
| 总分 75-84 且风险可控 | test_after_review |
| 总分 65-74 | watchlist |
| 总分 50-64 | reject_for_now |
| 总分 <50 | reject |
| 任一硬淘汰触发 | hard_reject |

渠道建议：

1. Amazon-first：Amazon demand 高，FBA/利润/竞争可控，独立站潜力中等或待验证。
2. Site-first：SEO/B2B/内容/定制强，Amazon 需求不明显或不适合标准 SKU。
3. Dual-channel：Amazon 和独立站都高，优先进入 Barong 主线。
4. Research-only：数据不足，继续观察。
5. Reject：不进入后续系统。

## 6. 第一阶段最应该先做什么

R 系列第一阶段不要先追求自动化全链路，而应先做“产品机会评分表 + 淘汰机制 + 下游交接标准”。

第一阶段最小可用能力：

1. 候选产品录入。
2. 硬淘汰清单。
3. Amazon 评分卡。
4. 独立站评分卡。
5. Barong 适配评分。
6. final_recommendation。
7. 输出 K/I/P/GMC/SEO 的 handoff checklist。

原因：只要评分标准和淘汰机制不清晰，后续自动化越强，越可能把错误产品高效推进到错误系统。
