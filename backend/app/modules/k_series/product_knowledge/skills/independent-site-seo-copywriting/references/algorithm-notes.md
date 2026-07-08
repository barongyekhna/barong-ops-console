# 谷歌排名机制调研笔记（2025-2026）

按可信度分级。用于校对 SKILL.md 规则、回答"为什么"的追问、未来更新对照。

## 谷歌官方确认

- **Helpful Content 并入核心算法（2024-03）**：不再是独立系统，helpfulness 由多信号在很大程度上**站点级**评估。
  来源: https://developers.google.com/search/docs/appearance/ranking-systems-guide
- **2025 年实际发布的更新**（谷歌确认，仅此四次）：3 月核心更新（3/13-27）、6 月核心更新（6/30-7/17）、8 月垃圾更新（8/26-9/22）、12 月核心更新（12/11-29）。官方描述均为"更好地呈现相关、令人满意的内容"，**没有公布任何具体机制**——网上一切"12 月更新专打 XX"的文章都是推测。
  来源: https://searchengineland.com/google-algorithm-updates-2025-in-review-3-core-updates-and-1-spam-update-466450
- **AI 功能官方指南（2026-05 文档）**：AI Overviews/AI Mode 无需特殊标记、无"AI 文件"、无新 schema；要求就是常规项——可索引、可出摘要、people-first 内容、重要内容用文本、结构化数据与可见内容一致、Merchant Center 数据新鲜、内链。垃圾政策同样适用于生成式结果。
  来源: https://developers.google.com/search/docs/appearance/ai-features
- **FAQ 富媒体结果彻底下线**：2023-08 收紧，2025-05 宣布弃用，2026-05-07 完全停止展示。页面 FAQ 内容本身仍可用于匹配与 AI 抽取。
  来源: https://developers.google.com/search/updates
- **结构化数据两套体验**：merchant listing（可购买页：Product+Offer 必备，增强字段 shippingDetails、hasMerchantReturnPolicy、GTIN、变体规范）与 product snippet（测评/对比页：Review、AggregateRating、优缺点标记）。
  来源: https://developers.google.com/search/docs/appearance/structured-data/product
- **Site reputation abuse**（寄生 SEO）：手动处罚执行；2024-11 起"无论是否有第一方参与或监督"都算违规（CNN/USA Today 优惠券区被除名）。
  来源: https://developers.google.com/search/blog/2024/11/site-reputation-abuse
- **Core Web Vitals**：INP 于 2024-03 取代 FID；官方口径"强烈推荐"但相关性远比它重要（John Mueller）。
- **Scaled content abuse** 垃圾政策（2024-03）：批量生产低价值页面，无论 AI 还是人写；2025 年中起出现引用该政策的手动处罚（Search Engine Roundtable 报道）。
- **电商专项文档**: https://developers.google.com/search/docs/specialty/ecommerce （URL 结构、分页、导航、评论写作质量章节）
- **Agentic 购物**：2025 底谷歌发布 agentic checkout 与 UCP 协议（与 Shopify 共建）；Shopping Graph 500 亿+ 条目，Gemini 购物回答的查询对象。
  来源: https://blog.google/products/ads-commerce/agentic-commerce-ai-tools-protocol-retailers-platforms/

## 可信研究（行业，非官方）

- **GEO 论文（普林斯顿/佐治亚理工，KDD 2024）**：内容中加入统计数据/可引用信息 → AI 可见度 +30-40%，最被复现的 GEO 发现。
- **Ahrefs（2025-08，7.5 万品牌）**：全网品牌提及与 AI 可见度相关系数 0.664，外链仅 0.218（约 3 倍）；schema 与被引用相关但**补 schema 不直接带来引用**（非因果）。
- **AI Mode query fan-out**：5000 查询研究显示 AI Mode 引用与自然前 10 的域名重合仅 ~51%（URL 级 ~32%）；约 80% 被 AIO 引用的来源不在该词自然排名中；自然前 3 也只有 ~8% 的被引用概率（方向性数据）。
- **3600 万 AIO 引用分析**：Wikipedia、YouTube、谷歌自家、Reddit、Amazon 合计吃掉 ~38% 引用。传统电商页在 AIO 引用中占比极小（一项研究 ~0.3%，单一来源未复核）。
- **Aleyda Solis 电商 AI 引用研究**（25 家头部店铺）：被引用最多的是尺码/合身指南、运费退换货政策、购买指南、兼容性页——**不是 PDP**；但 AI 流量更多落在 PDP。策略含义：PDP 接单 + 决策支持层被引用。
  来源: https://www.aleydasolis.com/en/ai-search/ecommerce-ai-search-citations-optimization/
- **Kevin Indig 可用性研究（70 人）**：用户约 80% 的最终答案仍来自自然结果；AI Overviews 压缩点击但经典排名仍驱动购买。AI 引荐流量对多数品牌 <1%（Similarweb/Aleyda/Lily Ray 2026）。
- **AIO 出现率**：约 16% 的查询（Semrush 2025）。
- **信息增益（information gain）**：源于谷歌专利、由 Indig/Backlinko/iPullRank 推广的概念——提供已排名结果集中没有的信息的页面表现更好。与评论系统"第一手体验"要求和 GEO"加统计数据"完全同向。

## 低可信 / 勿引用

- 给 2025 年各次核心更新指派具体机制或精确影响百分比的文章（大量 AI 生成的"恢复指南"站）。
- 任何"AI 专用 schema/llms.txt 能提升引用"的说法——与谷歌官方指南直接矛盾。
