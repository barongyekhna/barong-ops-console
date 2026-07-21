# R-A 复核行动(谷歌数据回填后)· Codex 规格 v1

> 背景:R-A 的 1671 份选品报告当初评审时 **Google Keyword Planner 数据全部缺失**(API 钥匙 7/16 猝死,2026-07-21 已修复并全量回填)。零成本筛选后,**238 份**「dtc_seo / dtc_ad 曾被拒或待定、但真实谷歌数据显示有肉」的报告需要复核。
> **本次由 Codex 亲自担任复核模型**(用你自己的推理判案,不调用任何外部 AI API——这正是本任务的意义:省 API 开销)。判完交付一个决定文件 + 一个应用脚本;**生产数据库操作由 Claude 执行,你不碰**。

## 输入(已备好,勿改)
`docs/RA_REREVIEW_20260721/evidence.json` —— 238 件,每件含:
- `title` / `primary_keyword` / `price_usd`(零售价,可能缺)
- `google`:主词月搜索量、竞争、CPC 低/高(USD)、按搜索量排序的前 5 灵感词
- `current`:dtc_seo 与 dtc_ad 的现有 verdict / score / 判由(当初**无谷歌数据**时判的)
- 个别件带 `priority_review` / `protected_from_deletion` 标记(见 §保护名单)

## 判案原则(照抄生产漏斗的三托盘家规,逐渠道独立判,绝不一票否决)
- **dtc_seo 托盘**(零成本自然流量):看 Google 月搜索量、CPC 含金量(CPC 越高=流量被市场验证越值钱=SEO 越有肉)、SERP 可入性。SEO 见效需数月:明显昙花/短周期风口品不适合此通道。
- **dtc_ad 托盘**(零库存但花钱买流量):核心是广告经济性——用 CPC 日常价(低位 + (高-低)×0.25)÷ 转化率 3-5% 估 CAC,对比零售价的可承受毛利;毛利扛不住 CAC 就 reject。爆款/短历史品适合此通道。
- **amazon 托盘一个字都不许动**(它基于 Keepa 证据,与谷歌数据无关)。
- 判 `pass` 需证据充分;证据矛盾或不足时判 `review`(进待滑堆让老板亲自滑),**宁 review 不乱 pass**。原判合理的就维持,复核不是翻案大赛。

## 输出一:决定文件
`docs/RA_REREVIEW_20260721/decisions.jsonl` —— 每行一个 JSON:
```json
{"report_id":"…","channel":"dtc_seo","previous_verdict":"reject","new_verdict":"pass","confidence":"high","reason_zh":"主词月搜16.5万、CPC高位$60=流量含金量极高;原判仅因谷歌数据缺失而拒;SERP无强势品牌位…(≤200字,必须引用具体数字)"}
```
- 每件的 dtc_seo 和 dtc_ad **各判一行**(共 ~476 行),维持原判也要写行(new=previous)并给一句理由——这是审计痕迹。
- `channel` 只允许 `dtc_seo` / `dtc_ad`;`new_verdict` 只允许 `pass|review|reject`。

## 输出二:应用脚本 + 测试
`scripts/apply_ra_rereview.py`(Claude 会在生产容器里执行):
- 读 decisions.jsonl,逐条更新 `ra_reports.payload`:
  - `channel_routes.routes.<channel>.verdict` ← new_verdict;`reasons` 头部插入 `"[2026-07-21 谷歌数据复核] " + reason_zh`
  - 首次触碰某报告时写审计块 `payload.rereview_20260721 = {"by":"codex","previous_routes":{原两渠道verdict}, "applied_at":"2026-07-21"}`(已存在则不覆盖——幂等)
- **幂等**:重复执行结果一致。**无迁移、不建表**。批量提交(50/批),`SET statement_timeout='300s'`。
- **保护名单硬编码**:对 `protected_from_deletion` 的 report_id,任何 `reject` 决定一律**升格为 `review`**并在 reasons 注明「老板保护名单:不淘汰」。
- 单元测试(fake session 模式,照 tests/backend 现有套路):幂等、审计块只写一次、保护名单升格、amazon 路由零改动、非法 verdict 拒绝。`bash scripts/run_backend_tests.sh unit` 全绿。

## 保护名单(死命令)
`027a4c3d-7f53-4c4b-8623-914a273a6437`(VISCOO 120 Pack Squishy Toys)——**老板点名重点审查**:
- 给它写**加长版**深度分析(reason_zh 可放宽到 500 字):结合"needoh/squishy 品类正处于全美爆红+亚马逊全面下架造成的供给真空"这一市场背景,分别论证 dtc_ad 与 dtc_seo 的机会与风险(它的谷歌数据:squishies 月搜 20.1 万、CPC 高位 $9.35)。
- **无论判什么,不得 reject**(最低 review 进待滑堆);protected 标记必须落进审计块。

## 硬约束
别动 F;别碰生产 DB(你只产出文件与脚本);别动 Claude 的 WP 插件目录;evidence.json 只读;每任务一句根因/做法;本地提交。

## 交付后 Claude 接管
执行 apply → 清分组池缓存 → 验证三托盘/待滑堆计数变化 + 捏捏套装落位与保护标记 → 向老板交总账。
