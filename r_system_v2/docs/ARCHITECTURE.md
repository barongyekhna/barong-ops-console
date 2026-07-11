# 自动化选品系统 · 完整架构与实现规格（交付 Codex 执行）

> 本文件是**自包含的实现规格**。Codex 应当能仅凭本文件构建系统,无需外部上下文。
> 判断规则细节见 `SKILL.md` 及 `references/*.md`,但本文件已内联所有关键阈值、prompt 与 schema。
> **凡标 `⚠️CONFIRM` 的常量,Codex 编码前必须用对应官方文档/免费状态接口核实真实值,不得臆测。**

---

## 0. 系统目标与非目标

**亚马逊轨(全自动)**
1. **持续段(便宜,24/7)**:Keepa 流式拉取 → 抽取特征 → 规则预筛 → 入库。
2. **按需段(贵,手动触发)**:用户点"启动选品"时,对库内 rule_passed 候选跑 DeepSeek→GPT→Opus 三层漏斗。

**独立站轨(半自动,两条子路)**
3. **广告子路**:自动用 Meta Ad Library API + Google Trends(可选 AdLibrary.com);Minea/PiPiADS 是
   **人工研究旁路**(无 API,手动入库)。汇入同一三层 AI(广告品评分卡)。
4. **SEO 子路**:**Serper 手动触发,去产品库里拿 Keepa 已拉的产品查 Google SERP**,算 SERP 弱点 +
   做 **Keepa×Serper 交叉**,汇入同一三层 AI(SEO 品评分卡,毛利放松)。

**非目标(明确不做)**:不实时调 AI;不存 Keepa 原始全量进主库(只存特征行);
持续段不调任何 AI;**Serper 不空跑、不自动后台跑 —— 只在用户手动触发时,对库内已有产品查**;
不给 Minea/PiPiADS 写 API 集成(它们没有数据 API)。

**核心成本纪律**:漏斗形,越往后越贵的资源处理越少的候选。

---

## 1. 组件清单

| 组件 | 选型 | 用途 |
|---|---|---|
| 编排 | **ops-console 自带的定时作业 + 后台 worker** | 所有流程 |
| 主库 | PostgreSQL 16 | 特征库 + 状态机 + 评估 + SERP 信号 |
| 对象存储 | Cloudflare R2 / B2 / Hetzner Storage Box | Keepa 原始 JSON(可选) |
| 亚马逊数据 | Keepa API(20 token/min 档) | 发现 + 富化(全自动) |
| SEO/SERP | **Serper.dev**(已有 key) | SEO 子路 + Keepa×Serper(**手动触发,查库内产品**) |
| 搜索量 | Google Ads Keyword Planner API | SEO 子路:关键词月搜索量 |
| 趋势 | Google Trends(pytrends) | 趋势方向 |
| 广告数据 | Meta Ad Library API(免费)+ 可选 AdLibrary.com API | 广告子路(自动) |
| 广告研究(人工) | Minea / PiPiADS UI | **无 API,人工研究→手动入库** |
| AI-1 | DeepSeek(`DEEPSEEK_MODEL`) | 量化过滤 |
| AI-2 | GPT(`OPENAI_MODEL`,如 gpt-5.6-luna) | 带上下文验证 |
| AI-3 | Opus(`ANTHROPIC_MODEL`)⚠️CONFIRM 模型串 | 决策+方案 |
| 推送 | Telegram Bot | 推 Top 候选 + 告警 |

**部署单机**:Hetzner CCX23(4 专用核/16GB)可同时跑 ops-console + Postgres + 特征库。拆库条件见 §11。

> **亚马逊页一垄断指标**(top3_review_count / single_brand_share / new_product_ratio)需要 **Amazon 搜索源**
> (Keepa 类目 Best Sellers 数据,或 SellerSprite/Helium10 API,或 Amazon SERP 抓取)—— **不是 Serper**
> (Serper 是 Google)。Serper 只服务 SEO 子路与 Keepa×Serper。这两个 SERP 用途不要混。

---

## 2. 环境变量(.env)

```
# Keepa
KEEPA_API_KEY=  KEEPA_DOMAIN=1  KEEPA_TOKENS_PER_MIN=20  ⚠️CONFIRM
KEEPA_ENRICH_BATCH=20  KEEPA_REFRESH_DAYS=7

# 数据库
PG_HOST= PG_PORT=5432 PG_DB= PG_USER= PG_PASSWORD=

# 对象存储(可选)
OBJ_STORAGE_ENDPOINT= OBJ_BUCKET= OBJ_ACCESS_KEY= OBJ_SECRET_KEY= STORE_RAW_JSON=false

# Serper(SEO 子路;手动触发)
SERPER_API_KEY=  SERPER_BASE_URL=https://google.serper.dev
SERP_RUN_LIMIT=300            # 每次手动触发最多查多少个库内产品
SERP_RECHECK_DAYS=30         # SERP 信号多少天后才重查

# 搜索量 / 趋势
GOOGLE_ADS_DEVELOPER_TOKEN= GOOGLE_ADS_CLIENT_ID= GOOGLE_ADS_CLIENT_SECRET= GOOGLE_ADS_REFRESH_TOKEN= GOOGLE_ADS_CUSTOMER_ID=

# 广告子路
META_ADLIB_TOKEN=            # Meta Ad Library API(Graph token)
ADLIBRARY_API_KEY=           # 可选,AdLibrary.com

# AI
DEEPSEEK_API_KEY= DEEPSEEK_MODEL=deepseek-chat DEEPSEEK_BASE_URL=
OPENAI_API_KEY=  OPENAI_MODEL=gpt-5.6-luna
ANTHROPIC_API_KEY= ANTHROPIC_MODEL=          # ⚠️CONFIRM 当前 Opus 模型串

# 漏斗阈值
DEEPSEEK_PASS_SCORE=60  GPT_PASS_SCORE=65  OPUS_KEEP_SCORE=75

# 亚马逊硬规则
PRICE_MIN=25 PRICE_MAX=70 MIN_NET_MARGIN=0.15 MAX_SELLER_COUNT=15
MAX_TOP3_REVIEWS=500 MAX_SINGLE_BRAND_SHARE=0.50 MAX_WEIGHT_LB=2.0

# 独立站规则
DTC_AD_MIN_GROSS_MARGIN=0.60   # 广告子路
DTC_SEO_MIN_GROSS_MARGIN=0.40  # SEO 子路(放松)
DTC_PRICE_MIN=25 DTC_PRICE_MAX=65 DTC_MIN_AD_RUN_DAYS=14
# Keepa×Serper 交叉阈值
SEO_MIN_DEMAND_UNITS=300       # Amazon 月销下限
SERP_WEAKNESS_MIN=60           # SERP 弱点分下限(0-100,越高越好打)

# 推送
TELEGRAM_BOT_TOKEN= TELEGRAM_CHAT_ID=
```

---

## 3. 数据模型(PostgreSQL DDL)

```sql
CREATE TYPE stage_t AS ENUM (
  'discovered','enriched','rule_passed','rule_rejected',
  'ai1_passed','ai1_rejected','ai2_passed','ai2_rejected',
  'final_keep','final_cut','shortlisted'
);

-- 3.1 亚马逊特征库(一行一 ASIN;UPSERT,不 append)
CREATE TABLE products (
  asin TEXT PRIMARY KEY,
  marketplace TEXT NOT NULL DEFAULT 'US',
  title TEXT, brand TEXT, category_root TEXT, category_node BIGINT,
  -- 价格/利润
  current_price NUMERIC(10,2), price_floor_12m_slope NUMERIC, price_floor_declining BOOLEAN,
  landed_cost NUMERIC(10,2), est_net_margin NUMERIC,
  -- 需求/销量
  bsr_current INTEGER, bsr_90d_avg INTEGER, bsr_90d_trend TEXT, bsr_12m_trend TEXT,
  est_monthly_units INTEGER, has_12m_history BOOLEAN, viral_suspect BOOLEAN,
  -- 竞争/垄断(★需 Amazon 页一源,非 Serper;可 NULL)
  seller_count INTEGER, fba_seller_count INTEGER, buybox_concentration NUMERIC,
  top3_review_count INTEGER, single_brand_share NUMERIC, new_product_ratio NUMERIC,
  -- 评论
  review_count INTEGER, rating NUMERIC(2,1), review_velocity_30d NUMERIC,
  -- 履约
  weight_lb NUMERIC, is_fragile BOOLEAN DEFAULT FALSE, redline_category BOOLEAN DEFAULT FALSE,
  -- ★ SERP 信号(Serper 手动富化写回;§6.6)
  serp_weakness_score INTEGER,       -- 0-100,越高=Google 页一越弱=越好排
  serp_top_domains TEXT[],
  serp_has_forums BOOLEAN,           -- 页一有论坛/Reddit/Quora=弱surface
  serp_has_shopping BOOLEAN,         -- 有 Shopping 结果=交易意图
  serp_checked_at TIMESTAMPTZ,
  seo_opportunity_score INTEGER,     -- Keepa×Serper 交叉分
  dtc_seo_candidate BOOLEAN DEFAULT FALSE,
  -- 状态机
  stage stage_t NOT NULL DEFAULT 'discovered',
  rule_reject_reason TEXT, raw_object_key TEXT, last_keepa_pull TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_products_stage ON products(stage);
CREATE INDEX idx_products_cat   ON products(category_root);
CREATE INDEX idx_products_seo   ON products(dtc_seo_candidate);
CREATE INDEX idx_products_serp  ON products(serp_checked_at);

-- 3.2 富化队列
CREATE TABLE enrich_queue (
  asin TEXT PRIMARY KEY, marketplace TEXT DEFAULT 'US',
  enqueued_at TIMESTAMPTZ DEFAULT now(), picked BOOLEAN DEFAULT FALSE
);

-- 3.3 选品运行记录
CREATE TABLE selection_runs (
  run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  triggered_by TEXT, channel TEXT,       -- amazon / dtc_ad / dtc_seo
  filters JSONB, status TEXT DEFAULT 'running', counts JSONB,
  started_at TIMESTAMPTZ DEFAULT now(), finished_at TIMESTAMPTZ
);

-- 3.4 AI 评估(每产品每层一行)
CREATE TABLE ai_evaluations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID REFERENCES selection_runs(run_id),
  asin TEXT, layer TEXT NOT NULL, model TEXT,
  score INTEGER, verdict TEXT, channel_guess TEXT, payload JSONB NOT NULL,
  in_tokens INTEGER, out_tokens INTEGER, cost_usd NUMERIC, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_eval_run ON ai_evaluations(run_id);
CREATE INDEX idx_eval_asin ON ai_evaluations(asin);

-- 3.5 独立站候选(广告子路;无 ASIN 用指纹)
CREATE TABLE dtc_candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fingerprint TEXT UNIQUE, source TEXT,    -- meta_adlib/adlibrary/minea_manual/pipiads_manual
  title TEXT, image_url TEXT, landing_url TEXT, supplier_url TEXT,
  price NUMERIC(10,2), est_margin NUMERIC, platforms TEXT[],
  ad_first_seen DATE, ad_last_seen DATE, ad_run_days INTEGER,
  engagement BIGINT, google_trends_12m TEXT,
  stage stage_t DEFAULT 'discovered', rule_reject_reason TEXT, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_dtc_stage ON dtc_candidates(stage);

-- 3.6 Keepa token 账本(可选)
CREATE TABLE keepa_token_log (
  ts TIMESTAMPTZ DEFAULT now(), tokens_left INTEGER, refill_in_sec INTEGER,
  refill_rate INTEGER, consumed INTEGER, op TEXT
);
```

---

## 4. 亚马逊规则预筛(纯代码,持续段)

命中任一 KILL = `stage='rule_rejected'`+记 reason;**NULL 不触发 KILL**(留给 AI)。

```
RULE_KILL(p):
  price 不在 [PRICE_MIN,PRICE_MAX] → reject('price_out_of_band')
  est_net_margin < MIN_NET_MARGIN → reject('margin_too_low')
  price_floor_declining=true → reject('price_war')
  seller_count > MAX_SELLER_COUNT → reject('too_many_sellers')
  single_brand_share > MAX_SINGLE_BRAND_SHARE → reject('brand_monopoly')
  top3_review_count > MAX_TOP3_REVIEWS → reject('review_wall_too_high')
  viral_suspect=true → reject('viral_unproven')
  redline_category=true → reject('redline_category')
  weight_lb > MAX_WEIGHT_LB → reject('too_heavy')
  else → stage='rule_passed'
```
`redline_category`:维护类目/关键词黑名单(battery/lithium/liquid/aerosol/medical/knife/restricted),
匹配 title/category 或 Keepa `hazardousMaterials` 命中即 true。

---

## 5. Keepa 节流(持续段;匀速回血,绝不爆发)

```
ENRICH_TICK():                  # ops-console 定时作业,每 60s
  status = keepa.status()       # 免费,返回 tokensLeft/refillIn/refillRate;log_token(status)
  budget = min(KEEPA_ENRICH_BATCH, status.tokensLeft); if budget<=0: return
  rows = SELECT asin FROM enrich_queue WHERE picked=false LIMIT budget FOR UPDATE SKIP LOCKED
  mark picked=true
  for asin: product=keepa.query(asin,history=true,stats=90)   # 1 token;不拉 offers
            UPSERT products(EXTRACT_FEATURES(product)); RULE_KILL(); DELETE enrich_queue
```
- **offers 不在富化拉**(贵);仅进 GPT 层、需竞品报价时对个别幸存者单独 `keepa.query(asin,offers=20)`。⚠️CONFIRM offers token 成本。
- `FOR UPDATE SKIP LOCKED` 防重复领取;`KEEPA_REFRESH_DAYS` 内的 ASIN 不重拉。

---

## 6. 特征抽取 + SERP 富化

**6.1–6.5 同前**:用 Keepa 库解析后的 `product['data']` 命名字段(SALES/RATING/COUNT_REVIEWS/AMAZON/NEW…),
不手撕 csv;rating 原值/10;派生 bsr 趋势斜率、price_floor 斜率、review_velocity、has_12m_history、
viral_suspect、est_net_margin(缺 landed_cost 则 NULL)。`est_monthly_units` 用**可插拔的按类目 BSR→销量曲线**,
不硬编通用公式。亚马逊页一垄断三指标(top3_review/single_brand_share/new_product_ratio)用 **Amazon 搜索源**
(Keepa 类目数据 / SellerSprite-Helium10 / Amazon SERP 抓取)按需补,**非 Serper**,可 NULL。

### 6.6 ★ Serper SERP 富化(手动触发,查产品库 —— 本系统的关键设计)

**Serper 不空跑。由 JOB-S(§8)手动触发,从 `products` 里取产品,用其标题/主关键词查 Google SERP,算弱点分写回。**

```
SERP_ENRICH(p):                                 # 对单个库内产品
  q = build_query(p.title 或 主关键词 + 类目词)
  r = serper.search(q, gl='us', hl='en')         # 1 credit
  domains = [host(x.link) for x in r.organic[:10]]
  weak  = count(domain in WEAK_SURFACES for domain in domains)   # reddit/quora/forum/pinterest/blogspot/薄内容
  giant = count(domain in MARKETPLACE_GIANTS)                    # amazon/walmart/etsy/ebay
  strong= count(domain in domains if 看似强DTC品牌深内容)          # 启发式:非巨头非论坛的独立域名+标题像产品页
  serp_has_forums = weak>0
  serp_has_shopping = r.shopping 非空 (可选单独调 /shopping)
  # 弱点分:论坛/薄内容/巨头占位越多=越好排;强DTC品牌越多=越难
  serp_weakness_score = clamp( 100 - strong*25 + weak*10 + giant*5 , 0, 100 )
  写回 p: serp_weakness_score, serp_top_domains=domains, serp_has_forums, serp_has_shopping, serp_checked_at=now()
```
> `WEAK_SURFACES` / `MARKETPLACE_GIANTS` 做成可配置域名表。真实域名权重(DA)Serper 不给,用上述启发式;
> 要更准可选接一个 DA 源,非必需。Serper 端点见 `/search`、`/autocomplete`、`/shopping`(⚠️CONFIRM 字段名)。

### 6.7 ★ Keepa × Serper 交叉(SEO 机会)

```
SEO_CROSS(p):
  demand_ok = p.est_monthly_units >= SEO_MIN_DEMAND_UNITS            # Amazon 需求已验证
  serp_ok   = p.serp_weakness_score >= SERP_WEAKNESS_MIN             # Google 页一好排
  p.seo_opportunity_score = round(0.5*norm(p.est_monthly_units) + 0.5*p.serp_weakness_score)
  p.dtc_seo_candidate = demand_ok and serp_ok
```
`dtc_seo_candidate=true` 的产品进 SEO 子路三层 AI(加载 dtc.md 子路 B 评分卡)。

---

## 7. 三层 AI 漏斗 — Prompt 与 Schema

通用:每次必返**纯 JSON**,无 markdown;parse 失败剥 ```json 围栏重试一次;严格 DeepSeek→GPT→Opus,不越级。
DTC 两条子路加载 dtc.md 对应子路评分卡(广告品 / SEO 品),其余流程一致。

### 7.1 DeepSeek(量化过滤器)
System:`你是选品量化过滤器,只依据给定结构化数据判断,不臆造。目标:滤掉明显不值得细看的,放行可能可行的(宁错放不错杀)。综合判断需求质量与竞争可攻性。只输出 JSON。`
Schema:`{ "score":0,"verdict":"keep|cut|hold","competition_attackability":0,"demand_quality":0,"top_reason":"","channel_guess":"amazon|dtc_ad|dtc_seo|both" }`
放行:`score>=DEEPSEEK_PASS_SCORE` 或 hold → ai1_passed。**建议夜间批量(JOB-C)。**

### 7.2 GPT(带上下文验证)
输入:特征行 +(亚马逊)listing/差评、(SEO)Serper 页一域名+serp 信号、(广告)竞品广告文案。
System:`你是选品验证层。核对数字与真实内容是否一致,找出小卖家靠"活儿"(设计/listing/bundle/内容)能补的差异化缺口或可排进去的 SEO 缺口。验证需求真实(非viral)。只输出 JSON。`
Schema:`{ "validated_score":0,"verdict":"keep|cut|hold","differentiation_gap":"","demand_real":true,"red_flags":[],"channel_guess":"amazon|dtc_ad|dtc_seo|both" }`
放行:`validated_score>=GPT_PASS_SCORE` 且 demand_real → ai2_passed。

### 7.3 Opus(决策+方案)
System(内联门槛矩阵 + 路由 + SEO 经济学):
```
你是小卖家选品决策者,只处理通过前两层的候选,做"赌错就亏钱"的判断:
(1) 门槛矩阵:护城河是"钱砌"(认证/大MOQ/专利/广告预算/海量评论)还是"活儿砌"(差异化/listing/bundle/内容/SEO)?钱砌→倾向cut,活儿砌→可keep。
(2) 方案以小卖家资源是否真可行(不砸大钱)。
(3) 真实 P&L:退货率类目基线×运费×储仓费算进去。
(4) 路由:
    amazon=有现成搜索需求+利润扛FBA+缺3秒钩子;
    dtc_ad=强钩子+毛利≥60%付得起广告+已被亚马逊价格战;
    dtc_seo=可搜索问题+Google页一弱(serp_weakness高)+常青+毛利≥40%(SEO 边际CAC≈0,毛利可放松);
    both=兼具。
(5) Amazon已验证+独立站可承接 → dtc_migration_candidate=true(尤其 Keepa×Serper 命中者)。
产出可执行行动:打样验什么;amazon→listing改什么;dtc_ad→广告钩子+bundle;dtc_seo→目标关键词簇+内容角度。只输出 JSON。
```
Schema:`{ "final_score":0,"verdict":"keep|cut|hold","channel":"amazon|dtc_ad|dtc_seo|both","barrier_type":"capital|skill","differentiation_plan":"","pnl_estimate":{"sell_price":0,"landed_cost":0,"fees":0,"return_cost":0,"net_margin":0},"risks":[],"next_action":"","dtc_migration_candidate":false }`
收尾:`final_score>=OPUS_KEEP_SCORE` 且 keep → shortlisted,推 Telegram;否则 final_cut。

---

## 8. ops-console 作业编排

> 全部在 ops-console 内执行,不用任何外部编排工具。每个"作业(JOB)"是 ops-console 里的一个
> 后台任务:**定时作业**(由 ops-console 的调度器按 cron 周期触发)或 **手动作业**(由 ops-console
> UI 按钮 / 内部接口触发)。下面用 `步骤 → 步骤` 描述每个作业的执行链,都是 ops-console 内的函数调用 +
> 数据库读写 + 外部 HTTP 请求,不涉及可视化节点。

### JOB-A · 亚马逊发现(定时,每日)
调 Keepa Product Finder(filters;⚠️CONFIRM token 成本) → 解析 ASIN →
按 last_keepa_pull 去重 → `INSERT enrich_queue ON CONFLICT DO NOTHING`。

### JOB-B · 富化滴流(定时,每 60s)
调 Keepa status → `budget=min(BATCH,tokensLeft)` → 若 ≤0 直接返回 →
领取 budget 条(`FOR UPDATE SKIP LOCKED`)→ 逐个 Keepa query → `EXTRACT_FEATURES` →
(可选)写对象存储 → `UPSERT products` → `RULE_KILL` → `DELETE enrich_queue`。

### JOB-C · DeepSeek 夜间批量(定时,02:00)
`SELECT stage='rule_passed'` → 分批 → 调 DeepSeek →
`INSERT ai_evaluations(deepseek)` → 阈值判定 → 更新 stage 为 ai1_passed/ai1_rejected。

### JOB-S · ★ Serper SEO 富化(手动触发,查产品库)
ops-console 里一个**手动按钮 / 内部接口**触发(可带 filters:类目/stage) →
`SELECT * FROM products WHERE (dtc_seo_candidate IS NOT TRUE) AND (serp_checked_at IS NULL OR serp_checked_at < now()-SERP_RECHECK_DAYS) AND stage IN ('rule_passed','ai1_passed') ORDER BY est_monthly_units DESC LIMIT SERP_RUN_LIMIT` →
分批调 Serper `/search`(+可选 `/shopping`) → `SERP_ENRICH(§6.6)` → `SEO_CROSS(§6.7)` →
`UPDATE products(serp_*, seo_opportunity_score, dtc_seo_candidate)` →
Telegram 通知:本次新发现 dtc_seo_candidate=N 个。
> **纯手动,绝不设定时调度。** Serper 便宜但按你节奏跑,`SERP_RUN_LIMIT` 控每次量;只对库内已有产品做检查。

### JOB-D · 按需选品·亚马逊(手动触发)
触发(channel=amazon) → `INSERT selection_runs` →
`SELECT stage='ai1_passed'(+filters) ORDER BY est_monthly_units DESC LIMIT N` → (可选)Amazon 页一富化补垄断三指标 →
逐个调 GPT(带 listing/差评) → `ai_evaluations(gpt)` → 通过则调 Opus → `ai_evaluations(opus)` →
`update products` → `update selection_runs` → Telegram 推 Top shortlist。

### JOB-E · 按需选品·独立站(手动触发)
- **SEO 子路**(channel=dtc_seo):`SELECT products WHERE dtc_seo_candidate=true(+filters)` → 同 GPT→Opus(加载 dtc.md 子路B)→ 推送。
- **广告子路**(channel=dtc_ad):
  调 Meta Ad Library API(在投+ad_run_days)+ Google Trends → 指纹去重 → `UPSERT dtc_candidates` →
  `DTC_AD_RULE_KILL` → 同 GPT→Opus(加载 dtc.md 子路A)→ 推送。
  (人工:你在 Minea/PiPiADS UI 挑的候选,经 ops-console 的一个录入表单写入 dtc_candidates,再进同漏斗。)

```
DTC_AD_RULE_KILL(c):
  est_margin < DTC_AD_MIN_GROSS_MARGIN → reject('margin<60%')
  price 不在 [DTC_PRICE_MIN,DTC_PRICE_MAX] → reject('price_out_of_band')
  ad_run_days < DTC_MIN_AD_RUN_DAYS → reject('unproven_ad')
  redline(title) → reject('redline')  else rule_passed
```

### JOB-F · 错误/告警(横切)
所有外部 HTTP 调用(Keepa/Serper/各 AI/Meta)统一封装:retry(指数退避×3);
最终失败 → Telegram 告警 + 记 error,不阻塞当前批次的其余项。

---

## 9. 评分卡与路由

统一 0–100,<60 剔除,60–75 待定,75+ 保留;任一硬红线=0 分剔除。

| 维度 | 亚马逊 | DTC广告 | DTC-SEO |
|---|---|---|---|
| 需求真实性(12月,非viral) | 高 | 高 | 高(常青尤甚) |
| 利润结构 | 高 | 最高(毛利≥60%) | 中(毛利≥40%,CAC≈0) |
| 竞争可攻性 | 最高(评论/卖家/品牌份额/新品占比) | 中 | 最高(SERP弱点) |
| 门槛种类(技能+/资本−) | 高 | 高 | 高 |
| 差异化/钩子 | 中 | 最高(3秒钩子) | 高(可搜索问题+内容角度) |
| 复购/AOV | 中 | 高 | 中 |
| 履约友好 | 高 | 高 | 高 |

**路由**:amazon / dtc_ad / dtc_seo / both;`dtc_migration_candidate`(Keepa×Serper 命中者优先)= 先 amazon 验证 → 独立站 SEO 承接。

---

## 10. 存储与扩展

特征行 ~1–2 KB(100 万≈1–2 GB,**硬盘**问题非 RAM);原始 JSON 只在 `STORE_RAW_JSON=true` 入对象存储;
按 ASIN UPSERT 去重不 append。**单机 Hetzner CCX23 足够**。拆独立 DB VPS 仅当查询并发/体量拖慢单机时:
第二台装 Postgres + 内网私网(Hetzner vSwitch/Vultr VPC)+ 防火墙只放行 ops-console 所在主机 IP + TLS,或托管 Postgres(Neon/Supabase)。**当前勿拆。**

---

## 11. 安全与可观测
- ops-console 自身做好鉴权 + 挂 Cloudflare;Postgres 不对公网暴露;密钥仅 .env,不入库/日志/URL。
- 成本看板:`keepa_token_log` + `ai_evaluations.cost_usd` + Serper credit 用量;每日 Telegram 汇总
  (富化数 / 各层通过数 / Opus 花费 / dtc_seo_candidate 数 / shortlist 数)。
- AI 输出全量留 `payload`,可回溯剔除原因。

---

## 12. 给 Codex 的构建顺序(每步可独立验证)

1. **DB**:建 §3 全部表与枚举。
2. **富化最小闭环**:JOB-B + §6 抽取 + §4 规则预筛。验证:塞几个 ASIN 入队 → products 落库、stage 正确、token 不超流速。
3. **发现**:JOB-A,确认队列持续进货 + 去重。
4. **DeepSeek 批量**:JOB-C,确认 rule_passed→ai1_* 且留痕。
5. **GPT 层 + Opus 层**:JOB-D(亚马逊),含 listing/差评抓取、路由、P&L、shortlisted、Telegram。
6. **★ Serper SEO**:JOB-S(手动触发查库)+ §6.6 SERP 弱点 + §6.7 Keepa×Serper,确认 dtc_seo_candidate 正确标记。
7. **独立站漏斗**:JOB-E(dtc_seo 用库内 candidate;dtc_ad 用 Meta Ad Library API + 人工旁路),加载 dtc.md 对应子路。
8. **成本看板 + 告警**:JOB-F、Telegram 汇总。
9. **硬化**:节流压测、重试、密钥与网络安全。

> 每里程碑先用少量真实数据跑通再放量。⚠️CONFIRM 所有标注项后再编码对应常量。
> **Serper 始终手动触发,绝不挂 Cron 自动空跑;它只对 Keepa 已灌入库的产品做 SERP 检查。**
