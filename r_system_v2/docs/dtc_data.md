# 独立站数据源（references/dtc_data.md）

Keepa 只管亚马逊。独立站分两条发现子路,数据源完全不同。**核心纠正:Minea/PiPiADS 没有公开数据 API**,
是给人手动研究的 UI 工具,不能直接接进自动化 pipeline。

## 一、API 现状(决定哪些能自动化)

| 来源 | 性质 | 费用 | 自动化 | 用途 |
|---|---|---|---|---|
| **Meta Ad Library API** | 官方 Graph API | 免费 | ✅ | 广告子路:谁在投、投多久 |
| **TikTok Commercial Content API** | 官方 | 免费 | ⚠️ 需审批、仅 EU 数据、限合规用途 | 广告子路:first/last_shown(投放时长)+reach |
| **AdLibrary.com API** | 第三方,为自动化设计 | Pro €179/mo,Business €329/mo | ✅ | 广告子路:TikTok+Meta+Google 统一 schema |
| **Google Ads Transparency** | 官方 | 免费 | ❌ 仅网页 UI | — |
| **Minea / PiPiADS** | UI+插件+credit | Minea $49/99/399;PiPiADS ~$77/155/263 | ❌ 无公开数据 API | **人工研究**,手动入库 |
| **Serper.dev** | Google SERP API | $0.30–1/1K,2500 免费,6 月有效 | ✅ | **SEO 子路 + Keepa×Serper 交叉** |
| **Google Ads Keyword Planner API** | 官方 | 免费(需 Google Ads 账户;无投放时量为区间) | ✅ | SEO 子路:搜索量 |
| **Google Trends** | 无官方 API,用 pytrends | 免费 | ✅ | 两路:趋势方向 |

## 二、广告子路数据流（自动化 + 人工旁路）
- **自动化**:Meta Ad Library API(在投+投放时长)+ Google Trends;要 TikTok 深度加 AdLibrary.com API。
- **人工旁路**:你想手动深挖时在 **Minea / PiPiADS UI** 里看,把挑出的候选**手动写入 `dtc_candidates`**。
  它们不是自动数据源 —— 别让 Codex 给一个不存在的 API 写集成。
- 关键信号:**`ad_run_days`(投放时长)= 头号爆品代理**(投得久=在盈利)。公开广告数据只能证明
  创意/报价/形式/近况,证明不了真实花费/ROAS,最终用你自己投放数据证伪。

## 三、SEO 子路数据流（Serper 为主,手动触发,查产品库)

**Serper 不空跑。由你手动触发,它去 Keepa 已灌满的产品库里,拿那些产品的标题/关键词去查 Google SERP。**

- **Serper `/search`**:抓目标关键词页一 → 算 **SERP 弱点分**(论坛/薄内容占位=弱=机会;强 DTC 品牌锁死=跳过)。
- **Serper `/autocomplete` + 相关搜索**:把种子词展开成长尾买家意图词。
- **Serper `/shopping`**:看交易意图 + 竞品价格带。
- **Google Ads Keyword Planner**:取搜索量(Serper 不给量,这是缺口,必须补)。
- **Google Trends**:常青/上升判定,排除 viral。
- **★ Keepa × Serper 交叉**:库里 Amazon 需求强(BSR/销量)的品,Serper 查出 Google SERP 弱
  → `dtc_seo_candidate=true`,进 SEO 评分卡。

> Serper 限制:Google-only,**不给搜索量**(用 Keyword Planner 补),看不到 Meta/TikTok 付费广告
> (广告子路用 Meta Ad Library),AI Overview 解析有限。
> 注:Google Custom Search JSON API 已对新客户关闭(老客户用到 2027-01),勿在其上建。

## 四、字段
- 广告子路 → `dtc_candidates`:`title/image_url/landing_url/supplier_url/price/est_margin/
  platforms[]/ad_first_seen/ad_last_seen/ad_run_days/engagement/google_trends_12m`
- SEO 子路 → 写回 `products`(SERP 信号列,见 ARCHITECTURE §3):`serp_weakness_score/serp_top_domains/
  serp_has_forums/serp_has_shopping/seo_opportunity_score/dtc_seo_candidate/serp_checked_at`
