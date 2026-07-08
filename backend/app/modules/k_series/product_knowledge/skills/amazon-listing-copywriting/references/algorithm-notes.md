# 亚马逊排名机制调研笔记（2025-2026）

按可信度分级。用于校对 SKILL.md 中的规则、回答用户"为什么"的追问、以及未来更新时对照。

## 官方确认的事实

- **COSMO**：Amazon SIGMOD 2024 论文《COSMO: A Large-Scale E-commerce Common Sense Knowledge Generation and Serving System at Amazon》。LLM 从搜索/购买行为中挖掘用户常识知识，人工审核后构建约 630 万节点 / 2900 万边的知识图谱，覆盖 18 个大类目，已部署于搜索相关性、会话推荐、搜索导航。10% 美国流量 A/B 测试：导航互动 +8%，GMV +0.7%。
  来源: https://www.amazon.science/publications/cosmo-a-large-scale-e-commerce-common-sense-knowledge-generation-and-serving-system-at-amazon
- **标题新政（2025-01-21 生效）**：≤200 字符（部分服装 125）；禁用 `! $ ? _ { } ^ ¬ ¦`；同词最多 2 次（虚词豁免）；品牌方有 14 天窗口修改被标记标题，逾期亚马逊自动改写。
  来源: Seller Central 公告；https://searchengineland.com/amazon-title-policy-update-2025-450485
- **Rufus 规模（2025 Q3 财报，Andy Jassy）**：2.5 亿活跃用户，月活 +140% YoY，交互 +210% YoY，使用者购买完成率高 60%，年化增量销售 $100 亿+；2025 底达 3 亿+/$120 亿。
  来源: https://fortune.com/2025/11/02/amazon-rufus-ai-shopping-assistant-chatbot-10-billion-sales-monetization/
- **2026-05-13**：Rufus 品牌并入 Alexa+，统一为 "Alexa for Shopping"；数据源与推荐逻辑不变（品牌层面变更）。
  来源: https://www.cnbc.com/2026/05/13/amazon-ditches-rufus-ai-chatbot-in-favor-of-alexa-shopping-agent.html
- **后台搜索词**：249 字节上限（字节非字符），超限可能整字段不索引。来源: Seller Central 帮助文档。
- **A+ alt-text**：2025 起（欧洲先行，2026 初扩展）卖家自写 alt-text 被移除，改为亚马逊 AI 自动生成，关闭了这条关键词索引通道。
  来源: https://myamazonguy.com/news/amazon-alt-text-removed-from-indexing/ （多家代理机构报告，无正式新闻稿）
- **A+ 转化数据（亚马逊官方口径）**：基础 A+ +5-8% 销量，Premium A+ 最高 +20%。

## 强社区共识（多家头部代理一致，非官方）

- "A10" 不是亚马逊官方术语，是卖家社区对 A9 后排名行为变化的统称。共识因子：自然销售速度与历史、转化率（最强可控杠杆，优化后 15-25% vs 弱 listing ≤8%）、CTR、卖家权重（账户健康/断货率/退货率，权重比 A9 时代大幅上升）、站外流量（新增强信号）、PPC 排名光环减弱（但 PPC 销量仍计入速度）。
  来源: My Amazon Guy, SellerLogic, Signalytics, Seller Labs 2025 指南。
- **Rufus 读取源**：标题、五点、描述、A+、结构化属性、评论、Q&A（RAG 式）。Q&A 是高价值检索源；评论被当作事实基准，属性维度的差评情绪可覆盖星级；偏好具体可验证数字声明，忽略营销最高级与全大写堆砌。
  来源: EvolveAMZ, Perpetua, Amalytix, Seller Metrics, Seller Labs。
- **结构化属性填充率**成为 AI 表面（COSMO/Rufus 过滤与图谱）的关键输入，头部代理称属性区"比标题更重要"（针对 AI 表面而言）。
- **标题改写生效周期**：关键词排名移动约 14-21 天（代理经验值）。
- 五点最佳实践：利益先行 + 大写标题头；移动端默认仅展开前 3 条；每条 ≤200 字符；禁 emoji/保修/价格。
- 关键词工作流标准栈：DataDive（Brandon Young 反查竞品 ASIN → Master Keyword List → 按字段映射）+ Helium 10（Cerebro/Magnet + Listening 评论分析）。

## 有争议 / 视为方向性参考（勿当作事实引用）

- A10 各因子的精确百分比权重（一切给出具体 % 的文章都是推测）。
- "站外流量占排名 15-20%"（Upscale Valley 单一来源）。
- "Rufus 直接改变主搜索排序"——亚马逊从未确认；Kevin King 认为 Rufus 对排名的影响"仍有争议"。保守立场：Rufus 是增量发现渠道，经典 SEO 因子仍决定主搜索结果页。
- "违规 listing 流量少 40%" 类供应商统计——未经验证。
