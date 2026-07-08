# Codex 指令 · R-A 真实 AI 筛选链 + Rainforest 竞争富化

> 交付对象:Codex。目标:把 R-A 的 mock AI 链换成真实调用,并在"利润通过"之后、AI 链之前,插入 Rainforest 竞争数据富化,补上 P0 缺失的"竞争可攻性"维度。
> 先读:`r_system_v2/docs/` 下的 `README.md / ARCHITECTURE.md / SKILL.md / amazon.md / dtc.md / shared.md / dtc_data.md / RA_TASKS.md / ra_supplier_keyword_skill.md`(选品判断手册 + 三层 prompt/schema + provider 规则)。
> 本指令基于 2026-07-08 用真实 Rainforest key 的实测,数据事实见 §3.0,不要臆测字段。

---

## 0. 边界与前置(务必遵守)
- **绝不碰 R-W**(Keepa 抓取 `r_system_v2/rw/*`)。只**读** `products_rw`,只**写** R-A 自己的表。R-W 必须持续运行,R-A 任何失败不得影响 R-W。
- **Rainforest key 已经接好,别重复做**:密钥系统里已新增并可绑定 `rainforest`(`backend/app/core/key_registry.py` + `KeyType` 枚举 + 前端目录,提交 `8d49ad1`)。key_type=`rainforest`,provider=`rainforest`,base_url=`https://api.rainforestapi.com`,用 `SecretManager.get_key("rainforest", org_id)` 取。
- Provider 规则(见 RA_TASKS §3):DeepSeek 直连;GPT、Claude/Opus 走 **4sapi 代理**;不接官方 OpenAI/Anthropic。
- 严守漏斗:**利润 → 竞争富化 → DeepSeek → GPT → Opus**,不跳层,最贵资源处理最少候选。
- 缺字段/失败**不误杀**:写 NULL、留给后面的 AI(R 系统铁律)。

## 1. 单产品流水线(一次 R-A run 内,对每个候选)
```
候选(来自 products_rw / ra_candidates)
  → ① 利润计算(已存在,Codex 刚做)
  → 若 profit_pass=false:停,记 reject,不进后续
  → 若 profit_pass=true:
      → ② ★竞争富化(Rainforest,本指令新增)
      → ③ DeepSeek 初筛(真实)   —— 分<DEEPSEEK_PASS_SCORE 淘汰
      → ④ GPT 验证(真实,4sapi) —— 分<GPT_PASS_SCORE 淘汰
      → ⑤ Opus 决策(真实,4sapi)—— 分≥OPUS_KEEP_SCORE 入 shortlist
  → 写 ra_final_decisions + ra_reports
```

---

## 2. ★ Rainforest 竞争富化(核心新增)

### 3.0 实测事实(不要臆测)
- `type=search` 返回 `search_results[]`,每条含:`position / asin / rating / ratings_total(评论数) / title / sponsored`。**不含 brand。**
- `type=product` 返回 `product.brand`(可靠)、`product.date_first_available`(**经常为 None,不可靠,别依赖**)。
- 成本:**search = 2 credits,product = 1 credit**。
- 单端点:`GET https://api.rainforestapi.com/request?api_key=..&type=search&amazon_domain=amazon.com&search_term=..`。

### 2.1 触发
只对 `profit_pass=true` 的产品触发。量级:每次 run 几十~几百个。**严禁全量回填 products_rw。**

### 2.2 搜什么词
复用 `ra_supplier_keyword_skill` 抽出的**产品主体词**(已去品牌/ASIN/商标)作 `search_term`;`amazon_domain` 取产品 marketplace(默认 `amazon.com`)。

### 2.3 三指标算法(默认「便宜档」= 每产品 1 次 search,2 credits)
过滤 `sponsored=true`,取自然位:
- **top3_review_count** = 前 3 条自然位 `ratings_total`(存数组 + 最大值)。直接可得。
- **single_brand_share** = 从每条 `title` 抽品牌(启发式:标题首 token;更稳可把 10 条标题**一次性**丢给 DeepSeek 批量抽品牌),统计最大品牌数 / 自然位数。标题无品牌前缀的记 `generic`(本身=非品牌锁定信号)。
- **new_entrant_ratio_est** = 自然位中 `ratings_total < RAINFOREST_NEW_REVIEW_THRESHOLD`(默认 50)的占比(**代理法**,不依赖 date_first_available)。弱信号,可选。

### 2.4 精确档(默认关,`RAINFOREST_MODE=deep` 才开)
对页一前 10 ASIN 各打 1 次 `type=product`(+10 credits),拿准确 brand + date_first_available。仅个别候选进到 Opus 且需硬证据时开。

### 2.5 RainforestClient(新建)
- 单端点 `/request` + `type` 参数;`api_key` 从 SecretManager 取;超时 40s;失败指数退避重试 ×2。
- **credits 记账**:每次读响应 `request_info.credits_used / credits_remaining`,写成本看板(仿 `keepa_token_log` / `ai_evaluations.cost_usd`)。
- **按关键词缓存**:同 `search_term` 在 `RAINFOREST_RECHECK_DAYS`(默认 30)内不重复查,命中缓存 0 成本。

### 2.6 竞争块(注入 AI 上下文的结构)
```json
{"competition": {
  "keyword": "neck fan",
  "top3_review_count": [997, 19095, 5],
  "review_wall_max": 19095,
  "single_brand_share": 0.2,
  "dominant_brand": "JISULIFE",
  "new_entrant_ratio_est": 0.3,
  "page_one_sample": [{"asin":"..","reviews":62452,"brand":".."}],
  "source": "rainforest_search",
  "fetched_at": "2026-07-08T.."
}}
```
拿不到/失败 → 整块或个别字段为 NULL,**不 KILL**,产品照进 AI 链,只是少一份证据。

### 2.7 新表
`ra_competition_snapshots`(id, org_id, asin, keyword, top3_review_count jsonb, review_wall_max, single_brand_share, dominant_brand, new_entrant_ratio_est, page_one_sample jsonb, mode, credits_used, source, fetched_at)。keyword 缓存可复用本表(按 keyword+fetched_at 命中)。

---

## 3. 真实三层 AI 链(替换 mock)

### 3.1 Skill 加载
用已实现的 `skill_loader`(RA-4)按频道加载:Amazon→`SKILL.md+amazon.md+shared.md`;DTC-SEO/广告→`SKILL.md+dtc.md+dtc_data.md+shared.md`;综合→全部。每次结果持久化 skill version + hash。

### 3.2 三层 prompt / schema
严格用 `ARCHITECTURE.md §7` 的三层 system prompt 与 JSON schema(DeepSeek 量化过滤 / GPT 带上下文验证 / Opus 决策+方案+路由+P&L)。上下文注入:**特征行(来自 products_rw)+ 利润块(§1①)+ 竞争块(§2.6)**。GPT 层如需真实差评,可选调 Rainforest `type=reviews`(本期非必须)。

### 3.3 Provider 与阈值
- DeepSeek:`DEEPSEEK_API_KEY`;GPT:4sapi(`FOURSAPI_API_KEY/BASE_URL`,`RA_GPT_MODEL`);Opus:4sapi(`RA_OPUS_MODEL`)。
- 阈值(ARCHITECTURE §2):`DEEPSEEK_PASS_SCORE=60`、`GPT_PASS_SCORE=65`、`OPUS_KEEP_SCORE=75`。
- 每层必返**纯 JSON**;parse 失败剥 ```json 围栏重试一次;严格不越级。

### 3.4 审计(RA 交付硬要求)
每层每次调用把 **输入 / 输出 / 模型 / skill version+hash / in-out tokens / cost / 理由** 写 `ra_ai_evaluations`。竞争块要在 payload 里可见、可回溯。

---

## 4. 韧性 / worker 要求(RA_TASKS §9)
可取消、可重试、有超时、有 token/credits 成本记录;单产品失败不炸整 run,其余继续;R-W 持续运行不受影响。

## 5. 配置(新增 env)
`RAINFOREST_MODE=cheap|deep`(默认 cheap)、`RAINFOREST_RECHECK_DAYS=30`、`RAINFOREST_NEW_REVIEW_THRESHOLD=50`。

## 6. 验收标准
1. 一个 profit_pass 产品:利润 → 真实 Rainforest 竞争(cheap,2 credits)→ 真实 DeepSeek→GPT→Opus → 决策 + 报告,全链路真数据。
2. 竞争三指标算出(top3 来自 search、品牌份额来自标题、新品占比用代理),竞争块进 prompt 且写入 ai_evaluations。
3. NULL-safe:竞争抓取失败不 KILL。
4. 每次 AI 调用有审计(模型/skill hash/输入输出/成本);Rainforest credits 有记账;同关键词缓存命中 0 成本。
5. R-W 不受影响。

## 7. 本期**不做**(留给 owner + Claude 事后优化,别碰)
- "**开模-able / 制造改良机会**"标签(服务用户工厂开模的第 4 层战略,后续加进 Opus 输出维度)。
- "**履约模式**"维度(FBM/自发货 vs FBA 经济账区分)。
- **TikTok Shop** 路由出口、**GEO** 信号、2026 阈值重校准、Rainforest 精确档默认化。
这些是复盘阶段的优化项,本次只做上面的核心链路。
