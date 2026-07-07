# R-A 产品分析中心任务总文档

更新时间：2026-07-05

本文档用于记录 R-A 系列的架构、任务范围、实施顺序和进度状态。R-W 已作为持续抓取与产品仓库层完成，后续利润、成本、供货商、二轮 AI 分析、DTC 判断和最终选品报告均归入 R-A。

## 1. 当前结论

R-A 不是 R-W 的延伸页面，而是 R 系列的深度分析与最终选品决策层。

R-W 负责：

- Keepa 24 小时持续抓取。
- 类目与子类目抓取。
- 硬门前置过滤。
- 产品基础数据沉淀。
- FBA fee、referral fee、评论、销量、BSR、图片等基础字段。
- DeepSeek 轻量实时初筛与标签。

R-A 负责：

- 从 R-W 产品库读取候选产品。
- 对通过产品进行 DeepSeek、GPT、Opus 三层深度分析。
- 调用 1688 官方 API 获取真实供货商与成本；真实 API 到位前使用 mock 1688 API 跑通 R-A 闭环。
- 计算真实利润、毛利、净利、ROI 和风险。
- 判断 Amazon / DTC / Amazon+DTC / hold / reject 路由。
- 输出最终选品报告和可执行下一步动作。

## 2. R-A 架构目标

目标链路：

```text
R-W 产品库
  -> R-A 候选池
  -> Skill Loader
  -> DeepSeek 第一层分析
  -> GPT 第二层验证
  -> Opus 第三层最终判断
  -> Serper / 1688 / Playwright 成本与供应商分析
  -> 利润计算引擎
  -> 最终选品报告
  -> Telegram / 前台 UI / 持久化结果
```

R-A 必须支持：

- 中文 UI。
- 手动选择候选品。
- 批量启动分析。
- 按分数、利润、销量、风险排序。
- 记录每一次 AI 输入、输出、模型、skill 版本和判断理由。
- 不覆盖 R-W 数据，只读取 R-W 并写入 R-A 自己的数据表。

## 3. Provider 与 Key 规则

用户已确认：

- Claude / Opus 使用 4sapi 代理 key。
- ChatGPT / GPT 使用 4sapi 代理 key。
- 不直接接 Anthropic 官方 key。
- 不直接接 OpenAI 官方 key。

R-A provider 应设计为：

```text
DeepSeek provider
4sapi GPT provider
4sapi Claude/Opus provider
Serper provider（仅用于 DTC SEO / Google SERP 弱点分析，不再用于利润成本主链路）
1688 official API provider
1688 mock API provider
Profit/cost engine
```

建议配置项：

- `DEEPSEEK_API_KEY`
- `FOURSAPI_API_KEY`
- `FOURSAPI_BASE_URL`
- `RA_GPT_MODEL`
- `RA_OPUS_MODEL`
- `SERPER_API_KEY`
- `ALIBABA1688_API_KEY` 或密钥管理中 `alibaba1688` 绑定（可保存 AppKey/AppSecret/AccessToken JSON）
- `RA_1688_COOKIE_PROFILE`
- `RA_SUPPLIER_CRAWLER_PROXY`

## 4. Skill 安装与加载方式

R-A 使用的是 R 系列选品 skill，不是 Codex 插件。

现有 skill 文件：

- `r_system_v2/docs/SKILL.md`
- `r_system_v2/docs/amazon.md`
- `r_system_v2/docs/dtc.md`
- `r_system_v2/docs/dtc_data.md`
- `r_system_v2/docs/shared.md`

需要实现 `skill_loader`：

- 校验 skill 名称与版本。
- 加载对应参考文件。
- 计算文件 hash。
- 将 skill 内容注入 DeepSeek / GPT / Opus prompt。
- 在每次 AI 结果中持久化 skill version、hash、模型、输入、输出和理由。

加载规则：

- Amazon 分析：`SKILL.md + amazon.md + shared.md`
- DTC SEO 分析：`SKILL.md + dtc.md + dtc_data.md + shared.md`
- DTC 广告分析：`SKILL.md + dtc.md + dtc_data.md + shared.md`
- 综合分析：全部加载

## 5. 核心选品策略

### 5.1 Amazon 选品策略

重点判断：

- 是否存在真实需求。
- BSR 与月销量是否稳定。
- 价格是否主要处于 25-70 美金区间。
- review wall 是否可突破。
- 竞争是否被少数品牌垄断。
- 是否有 listing、图片、套装、功能、材质、场景上的差异化空间。
- FBA fee、referral fee、头程、退货、PPC 后是否仍有可接受利润。
- 是否适合中小卖家进入。

### 5.2 DTC 选品策略

广告型 DTC：

- 有 3 秒视觉钩子。
- 产品容易通过短视频解释。
- 毛利空间足够。
- 可做套装、复购或场景化内容。

SEO 型 DTC：

- Google 有明确购买意图搜索。
- Serper 结果显示 SERP 较弱。
- Amazon 有需求，但 Google 内容竞争不足。
- 产品可长期内容化，不依赖短期热点。

### 5.3 中小卖家红线

R-A 必须重点避开：

- 强认证。
- 强专利。
- 强品牌垄断。
- 高破损。
- 高退货。
- 过重或体积过大。
- MOQ 过高。
- 供应链不可控。
- 无差异化空间。
- 价格战严重。

## 6. 利润与成本实现方案

利润计算放在 R-A，不放在 R-W。

R-W 已提供 Amazon 侧数据：

- 售价。
- FBA fee。
- referral fee。
- 类目。
- 尺寸。
- 重量。
- 销量。
- BSR。
- 评论。
- 卖家数量。

R-A 需要补齐供应链侧数据：

1. 根据产品标题、中文名、图片和类目生成中文采购关键词。
2. 使用 1688 官方 API 图搜/同类商品接口获取候选供应商。
3. 使用 1688 商品详情接口补齐 SKU 价格、起批量、库存、运费提示和供应商信息。
4. 真实 API 到位前，使用 mock 1688 API 返回稳定的 3-5 个候选供应商，方便搭建 R-A 后续 AI 漏斗。
5. 按价格、MOQ、店铺年限、成交、评价、图片匹配、发货能力筛选。
6. 最终保留 3-5 个候选供应商。
7. 使用确定性公式计算利润，AI 只能解释和判断，不能编造成本。

利润计算字段：

- `supplier_unit_cost`
- `domestic_shipping_cost`
- `packaging_cost`
- `inspection_cost`
- `international_freight_cost`
- `duty_cost`
- `amazon_referral_fee`
- `fba_fee`
- `storage_fee_estimate`
- `return_reserve`
- `ppc_reserve`
- `landed_cost`
- `net_profit`
- `net_margin`
- `roi`
- `confidence`

## 7. 数据库任务

待建 R-A 表：

- `ra_selection_runs`
- `ra_candidates`
- `ra_ai_evaluations`
- `ra_supplier_searches`
- `ra_supplier_offers`
- `ra_profit_snapshots`
- `ra_final_decisions`
- `ra_reports`
- `ra_alerts`

数据边界：

- 读取：`products_rw`
- 写入：R-A 自己的表
- 不直接覆盖 R-W 产品主数据

## 8. 后端 API 任务

待实现 API：

- `GET /api/r/analysis/overview`
- `GET /api/r/analysis/candidates`
- `POST /api/r/analysis/runs`
- `GET /api/r/analysis/runs/{run_id}`
- `POST /api/r/analysis/runs/{run_id}/cancel`
- `POST /api/r/analysis/candidates/import-from-rw`
- `POST /api/r/analysis/supplier-search`
- `GET /api/r/analysis/suppliers`
- `GET /api/r/analysis/profit`
- `GET /api/r/analysis/reports`
- `POST /api/r/analysis/reports/{report_id}/approve`
- `POST /api/r/analysis/reports/{report_id}/reject`

## 9. Worker 任务

待实现 worker：

- R-A run manager。
- DeepSeek analysis worker。
- GPT validation worker。
- Opus final decision worker。
- 1688 official API supplier discovery worker。
- 1688 mock supplier discovery worker（真实 API 到位前默认启用）。
- Serper SEO/SERP enrichment worker（不参与利润成本主链路）。
- Profit calculation worker。
- Telegram notification worker。

Worker 要求：

- 可取消。
- 可重试。
- 有超时。
- 有 token 成本记录。
- 失败不影响 R-W 继续运行。

## 10. 前端任务

R-A 前台必须全部中文化。

页面至少包括：

- 总览。
- 候选池。
- 分析任务。
- AI 判断记录。
- 供应商比价。
- 利润测算。
- 最终报告。
- 设置。

关键功能：

- 从 R-W 导入通过产品。
- 手动选择产品。
- 批量启动分析。
- 查看每一层 AI 的理由。
- 查看供应商候选。
- 查看利润拆解。
- 一键只看通过产品。
- 一键只看高利润产品。
- 一键只看 DTC 候选。
- 导出最终报告。

## 11. 实施顺序

| 阶段 | 任务 | 状态 |
| --- | --- | --- |
| RA-0 | 审计 R 系列文档并确认 R-A 边界 | 已完成 |
| RA-1 | 编写 R-A 任务总文档 | 已完成 |
| RA-2 | 修正 R-A provider 架构，支持 4sapi GPT/Opus | 框架已完成，真实调用未接入 |
| RA-3 | 建立 R-A 数据表与迁移 | 框架表已完成 |
| RA-4 | 实现 skill_loader | 元数据加载已完成，prompt 组装未接入 |
| RA-5 | 实现 R-A 后端 API | 只读框架 API 已完成 |
| RA-6 | 实现 R-A 中文前端 | 框架工作台已完成 |
| RA-7 | 实现 R-W 候选池导入 | 未开始 |
| RA-8 | 实现 DeepSeek 第一层分析 | 未开始 |
| RA-9 | 实现 GPT 第二层验证 | 未开始 |
| RA-10 | 实现 Opus 最终判断 | 未开始 |
| RA-11 | 实现 Serper 1688 候选供应商发现 | 未开始 |
| RA-12 | 实现 Playwright 1688 页面抓取 | 未开始 |
| RA-13 | 实现供应商比价与 3-5 家候选输出 | 未开始 |
| RA-14 | 实现利润/成本计算引擎 | 未开始 |
| RA-15 | 实现最终报告与人工确认 | 未开始 |
| RA-16 | 实现 Telegram / 通知 | 未开始 |
| RA-17 | E2E 全链路测试 | 未开始 |
| RA-18 | 生产部署 | 未开始 |

## 12. 当前阻塞点

- R-A 已从 placeholder 升级为框架工作台。
- R-A manifest 已接入只读 API，执行功能仍未启用。
- 当前 R-A worker 只是 standby。
- Opus / GPT 角色已按 4sapi provider 框架定义，真实调用未接入。
- R-A 独立数据表框架已建立，尚未写入真实任务数据。
- R-A 中文前台框架已建立，候选导入和分析按钮尚未接入。
- 1688 抓取需要确认 cookie、登录态、反爬、代理和速率限制方案。

## 13. 交付标准

R-A 达到可交付必须满足：

- 能从 R-W 导入候选产品。
- 能人工启动批量分析。
- DeepSeek / GPT / Opus 三层结果均可见。
- 每个结论都有理由。
- 每个模型调用都有审计记录。
- 至少 3 家供应商候选可见。
- 成本与利润不是猜测，而是由供应商数据和确定性公式计算。
- 最终报告可持久保存。
- 前台全中文。
- R-W 持续运行不受 R-A 失败影响。
