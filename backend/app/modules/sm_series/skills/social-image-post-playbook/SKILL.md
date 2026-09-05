---
name: social-image-post-playbook
description: 【社媒 · 图文帖运营（Pinterest / Instagram / Facebook，不含视频）】把控制台已有的 K 产品事实与成品图、GEO 指南、SEO 工艺事实，原子化成各平台的图文帖：选支柱、写标题与文案、定关键词与标签、配图与叠字、排节奏、看指标、回流批评。只要任务涉及社媒发帖、图钉、轮播、文案、标签、话题、图文运营、Pinterest、Instagram、Facebook、社媒 SEO，即使没有明说"写文案"，都应使用本 skill。视频（Reels / TikTok / Shorts）不在本 skill 范围。
---

# 社媒图文帖运营（Pinterest / Instagram / Facebook · 2026-09 版）

> 草稿 REV 1，2026-09-05。来源见文末「参考与核实日期」。平台规则一年一变，改版前先读参考部分，看哪条过期了。

## §0 品牌家规（硬覆盖，任何平台任何支柱都不能违反）

遇到 Barong Yekhna 的内容，下面每一条都压过后文的任何技巧：

1. **对外品牌只有 Barong Yekhna。** 第三方品牌名、logo、型号对照一律不出现在文字、标签、叠字、图片像素里（品牌硬门四层防线同样适用于社媒）。
2. **三家主体口径全站一致：** 卖方是 Guangzhou Longjie E-Commerce Co., Ltd.；生产在**吉林自有工厂**；团队有人在**洛杉矶**。永远不写「广州工厂」「广州车间」，永远不出现「深圳 / Shenzhen」。自称 "a small factory" / "we make these ourselves"，不许 "leading manufacturer"。
3. **一切事实只能来自 K。** 规格、数字、认证、时效、退换、价格，每一条都要能指回 `k_product_knowledge_products` 的某个字段或 `craft_facts` 的某条记录；输出里必须列 `facts_used`。K 里没有的，不写；想写就先回 K 补数据。
4. **英制单位**（gallons、GPM、inches、lbs、°F），面向美国买家。
5. **承诺必须配机制。** 折扣、免运、样品、保修，没有 W-S / B2B 里对应的机制就不许写进帖子。
6. **工厂内容只能用真照片。** AI 不许生成「像是我们工厂」的画面；产品成品图按 K 视觉家规（明亮暖白、产品是唯一变量），场景图共享同一暖亮柔光。
7. **每个外链带 utm**：`utm_source={platform}&utm_medium=social&utm_campaign={pillar}&utm_content={post_id}`。没有归因的帖子等于没发。
8. **绝不自动回复私信，绝不买粉、互赞、转发别人的图。** 回复评论是黄灯（起草送审），回复私信是红灯（人亲手）。

## §1 流量机制一页纸（为什么这样写）

**图文平台的流量只有三种来源：搜索、推荐、关注。** 零粉丝账号只有前两种，所以每条帖子的第一读者是排序系统，不是人：标题、文案、alt、看板名、图里的东西，都是在告诉系统「这是什么、给谁看」。

### Pinterest：它是搜索引擎，不是社交网络

- 排序四信号：**相关性**（标题 / 描述 / 看板 / 落地域名里的关键词）、**互动**（保存 > 点击 > 点赞）、**质量**（清晰竖图、可放大）、**新鲜度**（新图钉有一段早期曝光窗口；同一张图重复保存会被降权）。
- **标签几乎无效**：官方口径是把关键词写进标题、描述、看板名，标签不作为优化对象。
- **新图钉（自己创建的）带来 90% 以上的站外流量，转存（repin）几乎不带。** 所以「一篇内容出多张不同图」是 Pinterest 的基本功。
- **竖图 2:3（1000×1500）**，横图和方图会被裁；系统会分析图片内容，图里要能看出「成品 / 用途」。
- 标题 100 字符，**前 40 个字符最可能被显示**；描述 500 字符；所有字段都填（有些字段不显示但喂推荐引擎）；有「主题」标签选项就选。
- 生命周期以**月**计，和 Instagram 的 48 小时是两个物种；它是复利渠道。
- 频率：新账号从每天 3–5 个新图钉起，几周内升到 5–10；突然放量会被标为可疑；老一套「每天 25+」现在被惩罚。
- 商品图钉 / Rich Pins / 认证商家（VMP）需要认领域名、接产品目录、装 Pinterest tag，且账号 ≥3 个月、域名 ≥9 个月；这是和 GMC 同类的门，**本 skill 只管普通图钉**，商品目录那条线归投放模块。

### Instagram：三套排序器，收藏与转发压过点赞

- Feed、Explore、Search 各自一套排序。Explore 看**互动速度与量**，这是零粉丝账号唯一能上的车。
- **转发（DM sends）权重约为点赞的 3–5 倍，收藏约 3 倍。** 内容目标不是「好看」而是「值得存、值得发给朋友」。
- **轮播是图文里最强形态**（2026 年 3500 万帖样本：轮播 0.55% > Reels 0.52% > 单图 0.45%；轮播收藏约 2 倍）。5–7 页最优；第 1 页是钩子（≤12 词），第 3 页前给出兑现，最后一页放行动。
- **文案关键词是搜索杠杆**：写进正文（不是评论），自然口语；关键词丰富的文案比堆标签的多约 30% 触达。2025 年起公开专业账号的帖子可被 Google 收录，文案和 alt 同时喂两边。
- **标签上限 5 个（2025-12 官方改），超过会被压制**；标签只做分类，不制造触达。用 3–5 个窄标签。
- **前 125 个字符**就是大多数人看到的全部文案，把关键词和核心信息放在这一段。
- **alt text ≤125 字符**，描述画面里真实有什么，自然带一个关键词。
- **原创性硬指标**：30 天内 ≥10 次转发别人的内容即整体踢出推荐。我们从不转发。
- 频率：每周 3–5 条 feed 帖是甜点区（Buffer 210 万帖），再多有收益但递减；一致性比数量重要。
- **诚实的预期**：Instagram 2026 的增长引擎是 Reels，没有视频的账号在这里的角色是「存在证明 + 靠轮播攒收藏」，不是涨粉机器。
- **商品标签（Instagram Shopping）对中国主体不可用**（支持市场名单里没有中国），所以链接只能走简介和「产品页在简介链接」；这是结构性限制，不是没做好。
- 审美风向：过度设计的图形帖在 2026 年表现变差，用户偏好真实、不那么修饰的画面。对我们的含义：**产品支柱用家规成品图，工厂 / 场景支柱用真照片**，两种风格分开，不混。

### Facebook：镜像 Instagram，链接放评论

- 主页自然触达只有粉丝的 1–6%；**带外链的帖子触达再砍 70–80%**，链接放**第一条评论**是通行做法。
- 互动诱饵（"tag a friend"、"comment YES"）被系统惩罚，不用。
- 有价值的自然放大器是**小组**，但进组发帖是人的事（红灯），系统只准备素材。
- 结论：Facebook 是 Instagram 的镜像 + 评论区链接，每周 3 条，不单独生产内容。

### 小红书方法论（不发小红书，但它是全球最成熟的图文平台，方法可迁移）

- 标题公式：**关键词 + 痛点 + 解决方案 + 好奇钩子**，核心关键词落在前 10 个字内，数字能显著提高点击。
- 关键词权重位置由高到低：标题 > 正文前 100 字 > 正文中段 > 结尾 > 图片文字 / alt > 标签 > 评论区 > 简介 > 收藏夹名。**和 Pinterest / Instagram 的结论完全一致**：标签垫底，标题和首段最重。
- 互动权重：关注 ×8、评论 ×4、转发 ×4、收藏 ×1、点赞 ×1；发布后 60 分钟的互动决定进不进更大流量池。
- 搜索流量的转化率约是推荐流量的 4 倍；图文笔记生命周期 15–20 天，适合干货清单、教程、测评，主打搜索承接。
- 关键词配比 **70% 长尾 + 30% 热门**。

### 五条跨平台通用结论（写任何帖子前默念）

1. 零粉丝阶段一切为搜索写：关键词进标题和首段，标签只做分类。
2. 收藏和转发才是硬通货，点赞不算数；问自己「谁会把这条存起来 / 发给谁」。
3. 一帖一个想法，一个行动。
4. 图必须新鲜且原创：同一源头出多张不同图，绝不重复同一文件。
5. 一致性压过数量：节奏由库存推出来，宁少勿断。

## §2 内容支柱（这家店的五根柱子，文案和标签按柱子分）

| 支柱 | 目标 | 素材来源（控制台） | 主平台 | 钩子类型 | 关键词类型 | 行动 |
|---|---|---|---|---|---|---|
| **P1 产品** | 成交 | K main / gallery 图 + approved 卖点 + 规格 | Pinterest 产品钉、IG 轮播 | 数字规格 / 用途 | 产品词 + 属性词（`primary_keyword`、`secondary_keywords`） | 看产品页 |
| **P2 导购 / 教育** | 被搜到、被收藏 | GEO 指南（按 chunk 拆）、K FAQ、挖到的问句 | Pinterest 指南钉（叠字）、IG 轮播 | 问句 / 数字清单 / 常见错误 | 长尾问句词（`long_tail_keywords`、PAA） | 读完整指南 |
| **P3 工厂 / 工艺** | 信任 | SEO 工艺事实库 + 真实工厂照片 | IG 单图或轮播、FB | "How we make it" | 工艺词 + 材料词 | 无硬行动，或「问我们」 |
| **P4 场景 / 生活** | 情绪、点击 | K description / scene 图、真实用户照片（有了再说） | Pinterest 场景钉、IG | 场景 + 一个事实 | 场景词（camping、van life、off-grid） | 看产品页 |
| **P5 品牌 / 人** | 记忆 | 凤凰、"why we make"、LA + 吉林 | IG、FB | 故事 | 品牌词 | 关注 |

**第一年配比（零粉丝、无视频）**，由资产量推出，不问人：

- Pinterest：P2 40% · P1 30% · P4 20% · P3 10%（P5 不发，Pinterest 不看故事）
- Instagram：P2 35% · P4 25% · P3 20% · P1 15% · P5 5%
- Facebook：镜像 Instagram

理由：搜索和收藏驱动的平台奖励导购内容；零粉丝账号发满产品图就是一本目录，没人关注目录。产品支柱靠 Pinterest 挂产品页链接来成交，不靠 Instagram。

**每根柱子的文案、关键词、标签、图片风格都不同**，这是本 skill 存在的理由。P1 说数字，P2 答问题，P3 讲过程，P4 给画面，P5 讲人。混着写就是「什么都像广告」。

## §3 开工前必须收集的输入

- 支柱与源头：`source_type`（k_product / geo_item / seo_item / craft_fact / manual）+ `source_id`
- 产品事实：K 的 `product_name_en`、`product_type`、`primary_use_case_en`、`target_customer_en`、`structured_specs_json`、`selling_points_approved_json`、`faq_research_json`、`dimensions_json`、`weight_json`、`certifications_json`、`warranty_note_en`、`safety_note_en`
- 关键词：K 的 `primary_keyword`、`secondary_keywords_json`、`long_tail_keywords_json`、`risk_keywords_json`；GEO `geo_mined_questions`；类目树叶子名；Pinterest 自动补全 / Trends（人工或 n8n 采集，写入类目级关键词池）
- 图：可用的 K 媒体资产（`asset_role` = main / gallery / description），每张的 `metadata_json`（位号、变体色）；工厂真照片（若有）
- 落地页：产品 `published_url` 或指南 `published_url`（必须 published，且匿名可打开；未发布的源头不出帖）
- 平台：目标平台、看板名（Pinterest）、本周已排帖子（避免同一源头连发）
- 品牌黑名单：`detected_brand_terms`

缺任何一项事实性输入 → 不生成该支柱的帖子，记 `blocked_reason`。这就是 fail-closed。

## §4 工作流

### Step 1 — 定支柱、定源头、定平台

按 §2 配比和当周已排帖子，从库存里挑源头。规则：同一产品同一平台 7 天内不重复；同一指南可以出 3–6 张不同图钉（按 chunk），但要分散在两周内发。

### Step 2 — 定关键词（先于写字）

- 主关键词 1 个：来自 K `primary_keyword` 或指南标题主词。
- 次关键词 2–3 个：K `secondary_keywords` / 长尾问句 / Pinterest 自动补全。
- **70% 长尾 + 30% 头部**。头部词只放看板名和简介，长尾词放单条帖子。
- 检查 `risk_keywords_json`：出现即换词。

### Step 3 — 写标题（Pinterest）/ 首行（Instagram）

**Pinterest 标题（≤100 字符，关键词在前 40 内）：**

- P1：`[product type] for [use case] – [one spec with number]`
- P2：问句或数字清单：`How to [do X] off-grid: [N] setups that actually work`
- P4：`[scene] with [product type]: [feeling/benefit in 3 words]`

**Instagram 首行（≤125 字符，含主关键词，就是整条文案的全部意义）：**

- P1：结果 + 数字：`A [product type] that [does X at Y number]. Here's what's in the box.`
- P2：`[N] [things] most first-time [users] get wrong about [topic]`
- P3：`How we [process] every [product] before it leaves our factory in Jilin`
- P4：一句画面 + 一个事实
- P5：一句故事

钩子四型：**数字 / 问句 / 反常识 / 常见错误**。禁：标题党、诱饵、和内容不符的承诺。

### Step 4 — 写描述 / 文案

**Pinterest 描述（≤500 字符，2–3 句）：**第一句直接说这是什么、给谁（含主关键词）；第二句 1–2 个事实（数字）；第三句说明点进去能看到什么。自然句子，不堆词，不用标签。

**Instagram 文案：**

- P1 / P4：125–150 字符即可，首行之后 1–2 句事实，结尾一个行动。
- P2：可以写成小博客（300–600 字符）：首行钩子 → 三点要点（对应轮播页）→ 一句「完整指南在简介链接」。
- P3：第一人称复数，讲一个过程事实，诚实承认边界（"not for X"），这是 E-E-A-T 的社媒版。
- 表情 ≤2 个；不出现 "premium / high-quality / best" 这类空形容词；每个形容词换成数字或换掉。
- 链接不可点，写「product page in bio」；Facebook 版本正文不带链接，链接进第一条评论。

**语气：**美国口语，小工厂说人话，像一个懂产品的人在给朋友解释，不像品牌部。

### Step 5 — 标签与看板

- **Pinterest：不用标签。** 看板即分类：一个类目子树一块看板，看板名 = 类目名 + 用途词（"Camping Showers & Off-Grid Washing"），看板描述含头部词；10–30 块看板封顶。
- **Instagram：3–5 个窄标签**，从类目级标签池取，池按支柱分组：1 个类目窄词 + 1 个用途社群词 + 1 个产品类型词 + `#barongyekhna` + 可选 1 个季节 / 地点词。禁：泛词（#love #outdoors 单独用）、超过 5 个、和内容无关的热门词。
- 标签池按类目子树建一次，产品再多也不重建（模块不按产品）。

### Step 6 — 配图与叠字

| 支柱 | Pinterest（2:3 竖图） | Instagram（4:5 轮播为主） |
|---|---|---|
| P1 产品 | K main 图做产品钉；gallery 每张一钉；小 wordmark 在底部；不叠规格文字 | 第 1 页 main 图 + 一句钩子叠字，第 2–5 页 gallery 细节，每页一个信息，最后一页产品名 + 「in bio」 |
| P2 导购 | 指南钉：家规配色模板，叠字 ≤ 图面 30%，标题 ≤8 词，底部品牌名；同一指南按 chunk 出 3–6 张不同图 | 轮播 5–7 页：第 1 页问句，第 2–6 页每页一个要点（可用 K 图或纯字卡），末页行动 |
| P3 工厂 | 少发 | 真照片，不加滤镜，不叠字或只叠一行 |
| P4 场景 | K 场景图直接做钉（有实测显示场景图点击约为纯产品图的 3 倍） | 单图或双页 |

规则：**一张图只用一次**（新鲜度）；变体靠裁切、换叠字、换底色生成，不靠复制；内部 WebP，出平台时转 JPEG / PNG（Pinterest 只收这两种）；每张图写 alt（≤125 字符，说画面里有什么）。

### Step 7 — 自检（交给批评闭环之前先过一遍）

- [ ] 每个数字都能指回 K / craft_facts（`facts_used` 非空且逐条可解析）
- [ ] 主关键词在标题前 40 字符 / 文案前 125 字符
- [ ] 没有第三方品牌、没有深圳、没有「广州工厂」
- [ ] 英制单位
- [ ] IG 标签 ≤5，Pinterest 0 标签
- [ ] 一个行动，一个想法
- [ ] 链接是 published_url 且带 utm
- [ ] 图片未在本平台用过
- [ ] 承诺（折扣 / 免运 / 样品 / 保修）都有机制

### Step 8 — 节奏（由库存推出，不问人）

- Pinterest 每日新图钉数 = `clamp(可用图钉库存 ÷ 60, 3, 10)`；前两周固定 3–5，之后按公式；一天内分散到 3 个时段；绝不一次性倾倒。
- Instagram 每周 3–5 条 feed；Facebook 镜像 3 条。
- 起步时段假设（太平洋时间，等指标校正）：Pinterest 晚间与周末；Instagram 工作日早晨与午间。
- 任何平台连续 14 天没有新素材 → 报「卡住」（数字员工四规矩里的那种），不硬发。

## §5 示例（占位符来自 K 字段；示意数字必须被 K 真值替换后才能发）

**P1 · Pinterest 产品钉**

- 差：`Premium Portable Shower – Best Quality Camping Gear!` （空形容词、无关键词结构、感叹号）
- 好：标题 `Rechargeable Camping Shower for Van Life – {flow_gpm} GPM, {runtime_min} min per charge`
  描述 `A portable camping shower for van life and car camping: {flow_gpm} GPM flow, about {runtime_min} minutes on one charge, and it draws from any bucket or stream. The product page has the full spec table, what's in the box, and our shipping times to the US.`
  `facts_used: [structured_specs_json.flow_gpm, structured_specs_json.runtime_min, package_includes_json]`

**P2 · Instagram 轮播（来自一篇 GEO 指南）**

- 首行：`5 things first-time campers get wrong about portable showers (and the fix for each)`
- 页 1 叠字：`5 portable shower mistakes` · 页 2–6：每页一个错误 + 一句修正（每句对应指南一个 chunk）· 页 7：`Full guide + spec table: link in bio`
- 标签：`#campingshower #vanlifeessentials #offgridliving #barongyekhna`
- alt（页 1）：`Portable rechargeable camping shower standing in a bucket beside a camper van at dusk`

**P3 · Instagram 单图（工厂）**

- 首行：`Every shower pump gets a {test_duration} water test before it leaves our factory in Jilin.`
- 正文：`We're a small factory. {process_fact_from_craft_facts}. If a unit fails the test, it doesn't ship. Not glamorous, but it's why we can say what we say on the product page.`
- 图：真照片；`facts_used: [craft_facts.{id}]`

**差的 P3（不许出现）**：`Proudly made in our Guangzhou facility by a leading manufacturer` （主体口径错 + 自夸）

## §6 指标与迭代

| 平台 | 北极星 | 次要 | 看什么就改什么 |
|---|---|---|---|
| Pinterest | 出站点击、保存 | 展示、放大 | 顶部 10% 的钉出 2–3 张变体；底部 20% 的批评回流到本 skill 的标题 / 叠字规则 |
| Instagram | 收藏 + 转发 ÷ 触达 | 轮播完读、简介点击 | 收藏低 = 内容不值得存（改 P2 结构）；转发低 = 没有社交价值（改钩子） |
| Facebook | 评论区链接点击 | 触达 | 只看它有没有帮 Pinterest / IG 之外带来订单归因 |

- 每周一次批评汇总（复用 `content_core/critique`）：反复出现的批评改 skill 不改单帖；数据缺口回流 K。
- 前两周影子期：全部帖子进内容台等人放行，用来对答案；之后 P1 / P2 可以放绿灯自动排期，P3 / P5 保持黄灯。
- 订单归因（utm → `w_orders.attribution_json`）是唯一算 ROI 的地方；社媒后台的数字只用来改内容。

## §7 红线（做了就是事故）

- 事实不来自 K；数字自己编；认证 / 时效 / 退换自己写
- 第三方品牌名或 logo；「广州工厂」；「深圳」
- 转发、搬运别人的图或文；AI 生成的「工厂现场」
- Instagram 标签 >5；Facebook 正文带链接；Pinterest 同一图片重复保存
- 互动诱饵、标题党、买粉、互赞群、自动私信
- 折扣 / 免运 / 样品承诺没有机制
- 未发布的产品或指南出帖；链接不带 utm

## §8 输出格式（一帖一条，落 `sm_posts`）

```json
{
  "platform": "pinterest | instagram | facebook",
  "pillar": "P1 | P2 | P3 | P4 | P5",
  "source_type": "k_product | geo_item | seo_item | craft_fact | manual",
  "source_id": "uuid",
  "title": "Pinterest only, ≤100 chars, keyword in first 40",
  "caption": "IG/FB caption or Pinterest description",
  "first_line": "IG only, ≤125 chars",
  "alt_text": "≤125 chars, literal description of the image",
  "hashtags": ["≤5, IG only, empty for Pinterest"],
  "board": "Pinterest board name (category subtree)",
  "link_url": "published_url + utm",
  "media_refs": [{"asset_id": "uuid", "slot": 1, "overlay_text": "≤8 words or null", "crop": "2:3 | 4:5"}],
  "keyword_primary": "...",
  "keywords_secondary": ["...", "..."],
  "cta": "one action",
  "facts_used": ["k.structured_specs_json.flow_gpm", "craft_facts.<id>"],
  "blocked_reason": null,
  "skill_version": "sm-image-post-playbook-v1"
}
```

`facts_used` 为空而正文含数字 → 门禁拒绝；`blocked_reason` 非空 → 不进队列。

## 参考与核实日期（2026-09-05 查证；带 ⚠ 的是二手或未见官方出处，开工前再核）

**Pinterest**
- Pinterest Business《Creative best practices》：2:3 / 1000×1500，标题 100 字符前 40 显示，描述 500 字符，logo 每图可见，产品要在真实场景 — https://business.pinterest.com/creative-best-practices/
- Pinterest Business《How to build your audience》《How to make Pins》：所有字段都填、加主题、看板标题描述用清楚的关键词 — https://business.pinterest.com/blog/how-to-build-audience-pinterest/ · https://business.pinterest.com/en-gb/how-to-make-pins/
- Sprout Social《Pinterest algorithm 2026》：四信号、新鲜度早期曝光、5–10 新钉/天 — https://sproutsocial.com/insights/pinterest-algorithm/
- Pingenerator《Pinterest SEO 2026》/ SEO Sherpa：标签约 1% 权重、关键词前置 — https://pingenerator.com/blog/pinterest-seo-2026 · https://seosherpa.com/pinterest-seo/
- Tailwind 2026 Benchmark（转引）：新钉带来 90%+ 站外流量 ⚠ — https://unil.ink/blog/pinterest-marketing-guide-2026
- 新账号节奏 3–7/天起、突增被标记 — https://pinboostr.com/how-many-pins-per-day/ · https://yourpincoach.com/how-often-to-post-on-pinterest/
- 场景图点击约 3 倍（单店测试，⚠ 样本小） — https://www.tailwindapp.com/blog/pinterest-pin-design-tips
- 叠字 ≤ 20–30% 图面 — https://aj-graphics.org/2025/02/26/how-to-use-text-overlays-for-pinterest-pin-designs/
- VMP 门槛（账号 3 个月、域名 9 个月、目录 50% 成功、tag）— https://www.godatafeed.com/blog/becoming-a-verified-merchant-on-pinterest · https://business.pinterest.com/verified-merchant-program-terms/ ；「2026 增强认证需营业执照」⚠ 未见官方 — https://www.getafollower.com/blog/pinterest-verification/
- 关键词工具：自动补全、Trends、Ads 关键词工具 — https://nealschaffer.com/pinterest-keywords/ · https://pinradar.io/blog/pinterest-keyword-research-2026/
- 「2026-01 更新 24–48 小时新钉曝光窗口」⚠ 未见官方 — https://www.outfy.com/blog/pinterest-algorithm/

**Instagram**
- Instagram 官方《Instagram ranking explained》：Feed / Explore 信号 — https://about.instagram.com/blog/announcements/instagram-ranking-explained
- 标签上限 5（2025-12 @creators 宣布、Mosseri 确认）— https://www.socialmediatoday.com/news/instagram-implements-new-limits-on-hashtag-use/808309/ · https://jennstrends.com/instagram-limits-hashtags-to-5-per-post/
- 转发权重 3–5×、收藏 3×、原创 vs 转发、10 次转发踢出推荐 — https://sproutsocial.com/insights/instagram-algorithm/ · https://blog.hootsuite.com/instagram-algorithm/ · https://creatorlanehq.com/blog/instagram-algorithm-2026-mosseri-vs-measured
- 关键词文案 +30% 触达（⚠ 行业统计非官方）— https://www.divemedia.com.au/marketing-tips-and-insights/social-seo-keywords-vs-hashtags · https://www.toptal.com/creator/post/instagram-seo
- 轮播 0.55% / Reels 0.52% / 单图 0.45%（3500 万帖）；轮播 5–7 页、钩子 ≤12 词 — https://www.diyphotography.net/instagram-algorithm-2026-whats-really-driving-reach-for-photographers/ · https://metricool.com/instagram-carousels/ · https://www.adpicto.com/en/blog/instagram-carousel-best-practices-2026
- 125 字符折叠 — https://boomp.net/blog/instagram-caption-best-practices-2026 · https://textcaret.com/content/why-is-my-instagram-caption-cut-off
- alt ≤125 字符、Google 收录专业账号 — https://sproutsocial.com/insights/instagram-seo/ · https://later.com/blog/instagram-seo/
- 每周 3–5 帖（Buffer 210 万帖）— https://buffer.com/resources/how-often-to-post-on-instagram/
- 商品标签支持市场不含中国 — https://help.instagram.com/337910740093030 · https://shopsetupexperts.net/facebook-shop-instagram-shop-supported-countries/
- 真实感压过精修图形（趋势观察）— https://www.designshifu.com/blog/instagram-optimized-graphics-what-works-in-2025

**Facebook**
- 自然触达 1–6%、链接帖 −70–80%、链接进评论 — https://brand24.com/blog/how-to-increase-reach-on-facebook/ · https://arjankc.com.np/blog/facebook-organic-reach-decay-2026-analysis/ · https://www.oneupweb.com/blog/why-you-shouldnt-always-post-links-on-facebook/
- 「每月只许 2 条外链帖」⚠ 未见官方 — https://techradar.info/are-links-allowed-in-facebook-posts-the-2026-strategy-guide/

**小红书 / 中文方法论**
- 花叔《小红书创作最佳实践》：标题公式、关键词 9 位置、CES 权重、搜索转化 4.1× — https://www.huasheng.ai/insights/xiaohongshu-best-practices/
- 知乎《2026 小红书搜索排名规则》 — https://zhuanlan.zhihu.com/p/2036024906928894713
- 卖家之家 / Shopline《Pinterest 引流独立站》 — https://mjzj.com/article/cjs8ay0aidqc · https://shoplineapp.cn/blog/shein-yin-liu-di-yi-zhan-pinterest-du-li-zhan-mai-jia-ru-he-wan-zhuan-hai-wai-ban-xiao-hong-shu
- 腾讯云《Instagram 运营终极指南 2026》（其中「10–15 标签」已过期，以官方 5 个上限为准）— https://developer.cloud.tencent.com/article/2713167

**内容支柱 / 同行**
- 内容支柱 3–5 根 — https://www.hypotenuse.ai/blog/content-pillars · https://624agency.com/blog/organic-social-media-strategy-dtc-brands
- 工厂幕后建立信任 — https://blog.saleslayer.com/social-media-marketing-for-manufacturing-companies · https://247manufacturingmarketing.com/how-manufacturers-build-buyer-trust-with-digital-content/
- EcoFlow 三类人群分层（Outdoor Adventurer / Home Preparedness / Tradesperson）与达人 UGC 体系 — https://www.modash.io/breakdowns/ecoflow-influencer-marketing-strategy
