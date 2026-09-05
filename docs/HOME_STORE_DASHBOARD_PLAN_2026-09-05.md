# 贸易公司主页重做 + 独立站流量采集 方案（2026-09-05 立项）

状态：方案，未开工。用户已拍板：按组织类型分皮；「控制台内实时」= 3 秒内；先做 store 组织，factory 组织另立项。

## 0. 为什么重做

现主页（`operations-dashboard.tsx`）五张卡全是控制台自身运行状态：可用模块数、执行数、成功率、待审批、活动流。
对 store / factory 两类组织一视同仁，没有一个数字和卖货或生产有关。

## 1. 骨架：一副骨，按 org_type 换皮

- 页面 `(console)/dashboard` 保留，`DashboardScene`（星场 + 星舰彩蛋）保留。
- **游戏厅 `ConsoleArcade`（12 台机 + 按组织记的历史纪录）必须保留**，仍在主页最底下，两类组织都有。用户 09-05 明令。
- 新增前端卡片注册表 `home-cards/registry.ts`：每张卡声明 `{ id, module_key | null, org_types[], component, drawer }`。
- 登录后 org_type 唯一（一个用户只在一个组织，见 org-multi-membership-lockout），从 `/auth/me` 的组织上下文取，不问用户。
- 卡片可见 = `org_type` 匹配 且（`module_key` 为空 或 该模块在 `useFrontendCapabilityState().sidebarItems` 里）。
  外部数据卡（流量、站点健康）`module_key = null`，store 组织人人可见。
- 自定义抽屉（显示/隐藏/排序）保留，localStorage 键按 org_type 分开。

## 2. 卡片契约（每个模块出一个接口，主页不认识任何模块）

```
GET /api/app/{module}/home-card
→ {
    card_id: "cs-inbox",
    count: 3,                       // 待办数，角标
    items: [{ id, title, subtitle, at, href }],   // ≤5 条
    freshness: "2026-09-05T03:40:00Z",            // 数据截至；控制台内=查询时刻
    actions: ["reply", "dismiss"]                 // 浮窗允许的简单操作
  }
```

- 所有查询带 `workspace_key`（org 范围），逐端点 curl 复验（geo-seo-workspace-leak-class）。
- 简单操作复用模块已有端点，不新造写接口。复杂操作 = 浮窗里「去模块」按钮跳 `href`。
- 新端点全部登记前端代理白名单（frontend-proxy-allowlist-gate）。

## 3. 实时：一条 SSE 流喂所有卡

```
GET /api/app/dashboard/stream   Accept: text/event-stream
event: card   data: {card_id, count, items, freshness}
event: ping   每 15s
```

- 服务端循环：每 3 秒把当前用户可见卡片的 `home-card` 摘要跑一遍，与上一轮比对，只推变化的卡。
- 复用 C19 `_event_page_stream` 的会话校验和循环结构（`c19_record_event_poll_seconds` 同类配置，主页单独一个 `home_stream_poll_seconds = 3`）。
- 整个主页只此一条长连接。原因：浏览器同域并发连接上限 6 条，一卡一流会把页面卡死。
- 断线：前端 EventSource 自动重连；重连前显示上次数据并灰掉「数据截至」。
- 上限：每 3 秒 × 打开的标签页数 一次聚合查询。十几人无压力；过百人改事件驱动（pg NOTIFY），本期不做。

## 4. store 组织第一版卡片清单

| card_id | module_key | 数据源 | 浮窗简单操作 | 跳模块 |
|---|---|---|---|---|
| cs-inbox | cs | `cs_series` messages status=new，retail+wholesale | 回复、标已处理 | 客服 |
| w-orders | w | `w_orders` 新单（自上次查看）、tracking_status 异常 | 查看详情、复制单号 | 发货 |
| geo-todo | geo | geo_content_items 待批评/待重写/待发布 | 放行单篇 | GEO |
| seo-todo | seo | seo_content_items 同上 | 放行单篇 | SEO |
| b2b-drafts | b2b | b2b_email_drafts 待人工审核；退信率接近 3% 红线 | 看、驳回（**永不发送**） | B2B |
| approvals | (approvals) | approvals pending + notifications unread | 通过/驳回/已读 | 审批 |
| site-traffic | null | `w_traffic_*`（§5） | 浮窗选日期区间（7/14/30 天预设 + 自选起止），看来源/国家/热门页/搜索词/外链点击 | 无 |
| site-health | null | H 哨兵最近一次结果 + SMTP 体检 | 无；红时置顶 | 站点健康 |

每张卡显示「数据截至」。控制台内卡 = 查询时刻；外部卡 = 最近一次成功采集时间。

卡片顺序（2026-09-05 预览定稿）：第一行 site-traffic（占两列）+ site-health；之后 cs-inbox、w-orders、geo-todo、seo-todo、b2b-drafts、approvals。

## 5. 独立站流量：n8n 采集流

### 数据源（2026-09-05 实测通）
站在 WordPress.com Atomic。用 n8n 凭据 `kaIcXMDT4cNA0GXm`（Wordpress account，应用密码）打站内 REST，**不需要 WP.com OAuth**。

| 接口 | 用途 |
|---|---|
| `GET /wp-json/jetpack/v4/module/stats/data` | 今日/昨日访客、浏览 |
| `GET /wp-json/jetpack/v4/stats-app/sites/242834372/stats/visits?unit=day&quantity=N&date=YYYY-MM-DD` | 按天曲线；`date` 为截止日，任意区间可取（实测 30 天、历史日期均通） |
| `…/stats/visits?unit=hour&quantity=24` | 今日按小时 |
| `…/stats/top-posts?period=day&date=…&num=N&max=10` | 按天热门页面，控制台按区间聚合 |
| `…/stats/referrers?period=day&date=…&num=N` | 按天来源（Jetpack 只分「搜索引擎 / 来源站 / 直接」） |
| `…/stats/country-views?period=day&date=…&num=N` | 按天国家 |
| `…/stats/search-terms?period=day&date=…&num=N` | 搜索词（绝大多数已加密，只报未加密的） |
| `…/stats/clicks?period=day&date=…&num=N` | 点出外链 |

`period=week` 按 ISO 周（周一起）分桶，不是任意 7 天；自选区间一律用 `period=day&num=N` 再在控制台聚合。
**时区**：Jetpack 按站点时区分日，实测 `utc_offset=-05:00`；控制台分日桶必须用站点时区，否则和 WP 后台对不上。用户在洛杉矶（UTC-7/-8），主页标注「站点时区」。

`stats/summary` 403，不用。Site Kit 的 GA4 代理缺 `analytics.readonly` scope，以后做渠道拆分时用户在 WP 后台 Site Kit 重新授权一次即可，本期不接。

### n8n 流「W-TRAFFIC 独立站流量」
- Cron `5-55/10 * * * *`（错开 03:00/03:20/03:40 三条每日流），7 个 HTTP 节点并行 → Merge → Code 打包 → `POST http://console_backend:8000/w/traffic/ingest`。认证走**静态令牌头** `X-Ingest-Token` = compose env `W_TRAFFIC_INGEST_TOKEN`（与现成十条流同一做法；独立一把钥匙，绝不复用 W 订单那把）。机器人账号那条家规是给数字员工的，n8n 采集流从来不以用户身份认证。
- 改 n8n 必须同步写 `workflow_history` 活跃版本（n8n-patch-method）。
- 免费接口，无台账需求；但按 promise-needs-mechanism 记：10 分钟一轮 = 144 次/天。

### 控制台侧
- 表 `w_traffic_hourly(workspace_key, bucket_at, views, visitors)` 唯一键 (workspace_key, bucket_at)，upsert。
- 发版记录（2026-09-05 UTC）：08:33 后端（镜像 4b7ba952d297，迁移已跑）；08:35 n8n `barongWtraffic001` 三表装库并激活；08:45 首轮采集成功，`worker_heartbeats.w-traffic` 落地，30 天 + 24 小时数据入库；08:43 前端（镜像 b9d94eb09b2e）。nginx `= /api/backend/dashboard/home/stream` 块由用户手工加。代码**未 commit**。
- 表 `w_traffic_daily(workspace_key, day, views, visitors, top_posts_json, referrers_json, countries_json, search_terms_json, clicks_json)`，唯一键 (workspace_key, day)。
- 心跳：`worker_heartbeats` 记 `w-traffic` 最近一次成功写入。**验收只认这个时间戳**（acceptance-must-be-implementation-independent）。
- 采集：每轮拉今日按小时 + 最近 30 天按天（visits / top-posts / referrers / country-views / search-terms / clicks 各一次），按 (workspace_key, day) upsert，历史日自动被修正。更早的区间浮窗按需向站点现拉，不落库。
- 卡片（默认最近 7 天，带日期标注）：7 天访客/浏览 + 与上个 7 天对比、今天与昨天、7 天柱状图（深柱访客浅柱浏览，x 轴日期）、7 天最热页/来源/国家各一行。
- 浮窗：日期区间 7/14/30 天预设 + 自选起止；区间柱状图；来源表、国家表、热门页面表、搜索词、外链点击，全部按所选区间聚合。
- 心跳超 20 分钟卡片变红「采集停了」，不静默显示旧数。
- 自己人不污染：Jetpack 靠页面 JS 打点，H 哨兵 curl 不计入；登录管理员默认不计。

## 6. 不做 / 不动

- factory 组织主页：另立项（库存、单据、BOM 缺料、霓旌心跳）。
- 事件总线 / 零延迟推送：本期不做。
- 浮窗里发开发信：永不。
- 现有登录页未提交改动：不碰。
- 游戏厅：不删不改不挪位。

## 7. 发版顺序（一块功能发一次，deployable-not-deployed）

1. 后端：卡片契约 + 8 个 home-card 端点 + SSE 流 + 流量表/ingest/心跳（一次发）。
2. n8n：W-TRAFFIC 流 + workflow_history。验收：心跳表出现 `w-traffic` 且 10 分钟内刷新。
3. 前端：注册表 + 骨架 + 8 张卡 + 浮窗 + 代理白名单（一次发）。
