# Codex 任务单：H 系列 —— 独立站健康巡检中枢（h.site_health）

> 任务代号：H-SITE-HEALTH
> 委托方：台里（Claude）· 拍板人：Barong Yekhna
> 日期：2026-07-15

---

## 0. 开工前必读（违反任何一条 = 返工）

1. **先跑 `git status`**。树上有并行工作头。你只准动本单「允许触碰的文件」清单里的文件。
2. **绝对禁碰**：
   - `backend/app/modules/f_series/**`、`frontend/src/modules/f/**`（F 系列）
   - `backend/app/modules/w_series/**`、`backend/app/modules/p_series/**`（运费链刚验收完，冻结）
   - `r_system_v2/**`、`frontend/src/modules/r/**`（Google Ads 工作头在动）
   - `frontend/src/app/globals.css`（一行都不碰）
   - 任何 n8n 工作流 JSON（`backend/app/modules/*/n8n/*.json`）——巡检执行流由台里写
3. **迁移纪律**：本任务有一个迁移，revision 必须是 `20260715_01_h_site_health`，`down_revision = "20260714_04_f_market_refs"`（当前 head）。改完迁移后必须：
   - 更新 `scripts/staging_stabilization.py` 的 `EXPECTED_ALEMBIC_HEAD = "20260715_01_h_site_health"`
   - 重新生成 manifest：`.venv/bin/python -c "import scripts.staging_stabilization as st; st.write_json(st.MIGRATION_MANIFEST_FILE, st.build_migration_manifest())"`
   - **生产部署和 alembic 由台里执行**，你只保证代码与测试正确
4. 工作目录：所有命令一律从 repo root（`/opt/barong-ops-console`）执行。
5. 完成后 commit 自己的文件即止，不部署。

## 1. 前端美学铁律（最高优先级约束）

**你没有任何视觉设计决策权。**

- 禁止新增 CSS 类/颜色/动画/间距/字号；禁止修改任何 `.css` 文件。
- H 页面的 module css 文件**允许新建一个** `frontend/src/modules/h/sitehealth/HealthDeck.module.css`，但内容必须**整块复制** `frontend/src/modules/w/siteops/ShippingDeck.module.css`（改类名前缀之外一个值都不许动）。W 的页面结构就是 H 的页面结构。
- 所有用户可见文案逐字取自 §6 文案表。
- 布局照抄 W-S ShippingDeck 的「统计卡行 + tab 面板 + 列表 + 台账」骨架。不发明新交互。

## 2. 模块定位与架构

**H 系列 = 独立站健康巡检**：定时（n8n cron）+ 手动（console 按钮）对 `https://barongyekhna.com` 做健康巡检，结果回传 console 入账，异常落通知收件箱。

**控制面/执行面分工（用户死命令：console 控制面 + n8n 执行面）**：

```
n8n 定时(每日) ──┐
                 ├──> n8n 巡检工作流（台里写）：
console 手动触发 ─┘      拉 sitemap → 逐 URL 检查(状态码/耗时) → 首页关键断言
                        └──POST /h/ingest（X-H-Ingest-Token）──> console 落库+告警
```

- console **不自己爬站**（执行面在 n8n）。console 负责：触发（调 n8n webhook）、收账（ingest）、展示（运行台账+发现列表）、告警（通知收件箱）。
- 模块只属于国际贸易组织（`INTL_TRADE_ONLY_MODULE_KEYS` 加 `h.site_health`，见 §5）。

## 3. 数据模型（migration `20260715_01_h_site_health`）

三张表，全部 UUID 主键 + created_at/updated_at（照抄 F/W 的 mixin 写法，模型文件 `backend/app/modules/h_series/sitehealth/models.py`）：

**h_health_runs**（巡检运行台账）
| 列 | 类型 | 说明 |
|---|---|---|
| id | Uuid PK | |
| trigger | String(20) NOT NULL default 'scheduled' | CHECK IN ('scheduled','manual') |
| status | String(20) NOT NULL default 'running' | CHECK IN ('running','completed','failed') |
| started_at / finished_at | DateTime(tz) | |
| urls_total / urls_ok / urls_broken / urls_slow | Integer NOT NULL default 0 | |
| avg_response_ms / p95_response_ms | Integer nullable | |
| sitemap_ok | Boolean NOT NULL default true | sitemap 拉取+解析是否成功 |
| homepage_ok | Boolean NOT NULL default true | 首页 200 且包含品牌串 |
| summary_json | JSON nullable | n8n 回传的原始摘要 |
| error | Text nullable | |

**h_health_findings**（发现明细，运行内逐条）
| 列 | 类型 | 说明 |
|---|---|---|
| id | Uuid PK | |
| run_id | Uuid FK→h_health_runs.id NOT NULL | index |
| finding_type | String(30) NOT NULL | CHECK IN ('broken_link','slow_page','sitemap_error','homepage_error') |
| url | String(2048) NOT NULL | |
| status_code | Integer nullable | |
| response_ms | Integer nullable | |
| detail | Text nullable | |
| status | String(20) NOT NULL default 'open' | CHECK IN ('open','acknowledged','resolved') |
| index | (run_id), (finding_type, status) | |

**h_ingest_tokens 不建表**——ingest 鉴权走 env `H_INGEST_TOKEN`（对齐 W_ORDERS_INGEST_TOKEN 模式，`backend/app/modules/w_series/router.py:950` 附近有现成写法照抄）。

## 4. 后端（`backend/app/modules/h_series/sitehealth/`：models.py / service.py / router.py + `backend/app/modules/h_series/router.py` 聚合导出，照 F 系列包结构）

### 4.1 端点（prefix="/h"，tags=["h-site-health"]）

人用端点鉴权照 F/P 口径写 `_require_h_permission`（owner / super_admin 放行，`h.site_health.read`，manage 隐含 read；照抄 `backend/app/modules/f_series/router.py:40-63`）。

| 端点 | 方法 | 权限 | 行为 |
|---|---|---|---|
| `/h/runs` | GET | read | 台账列表（limit 默认 30，倒序），返回上表全部统计字段 |
| `/h/runs/{run_id}` | GET | read | 单次运行 + findings 前 200 条 |
| `/h/runs/trigger` | POST | manage | 手动触发：POST env `N8N_H_HEALTH_WEBHOOK` 指向的 n8n webhook（body `{"trigger":"manual","ingest_url":"{H_CALLBACK_BASE}/api/app/h/ingest"}`，超时 10s）；同时建一条 status='running' 的 run 记录并把 run_id 一并 POST 给 n8n；n8n 不可达时该 run 标 failed 并返回 502 detail「n8n 巡检工作流不可达，检查 N8N_H_HEALTH_WEBHOOK」 |
| `/h/findings` | GET | read | 发现列表，query: `status`(默认 open)、`finding_type`、`limit`(默认 100 上限 500) |
| `/h/findings/{finding_id}` | PATCH | manage | body `{"action": "acknowledge"\|"resolve"\|"reopen"}` → status 流转 |
| `/h/ingest` | POST | **无会话鉴权**，header `X-H-Ingest-Token` == env `H_INGEST_TOKEN`（403 否则）| n8n 回传：见 §4.2 契约 |

### 4.2 ingest 契约（n8n → console，台里按这个写工作流，一个字段都不能偏）

```json
{
  "run_id": "console 触发时给的 uuid；定时触发时为空，console 自建一条 trigger='scheduled' 的 run",
  "status": "completed | failed",
  "error": "失败原因（status=failed 时）",
  "summary": {
    "urls_total": 128, "urls_ok": 120, "urls_broken": 3, "urls_slow": 5,
    "avg_response_ms": 640, "p95_response_ms": 2100,
    "sitemap_ok": true, "homepage_ok": true
  },
  "findings": [
    {"finding_type": "broken_link", "url": "https://barongyekhna.com/x", "status_code": 404, "response_ms": 320, "detail": "linked from sitemap"},
    {"finding_type": "slow_page", "url": "https://barongyekhna.com/y", "status_code": 200, "response_ms": 4200, "detail": "超过 3000ms 阈值"}
  ]
}
```

ingest 处理：找到/新建 run → 写 summary 统计列 → findings 落库（**同 URL 同 finding_type 已有 open 记录则不重复插入，只更新 status_code/response_ms/detail 和 updated_at**）→ 若 `urls_broken > 0 或 sitemap_ok=false 或 homepage_ok=false`，调 `backend/app/modules/notifications/service.py` 的 `create_notification`（签名见该文件 `:17`）落一条告警：`event_type="h.health_alert"`, `level="warning"`, `source="h_site_health"`, `title` 用 §6 文案表的告警标题模板, `payload={"run_id": ..., "urls_broken": ..., "sitemap_ok": ..., "homepage_ok": ...}` → 幂等（同一 run 重复 ingest 不重复告警：run 已 completed 则直接 200 返回 `{"deduped": true}`）。

### 4.3 惰性收尸

running 超过 30 分钟无更新 → failed（照抄 `backend/app/modules/f_series/enrichment/runs.py` 的 `reap_stale_runs` 语义，list 端点触发）。

## 5. 新模块登记全清单（历史上每一处都有人栽过，逐项照做）

**后端：**
1. `backend/app/core/modules.py`：加 `h.site_health` manifest（照抄 `f.enrichment` 的条目结构，`:1151` 附近）：display_name「H 站点健康」，category business，status active，lifecycle production_released，route_namespace `/h-site-health`，api_namespace `/h`，navigation group Registry / label「H 站点健康」/ icon "Activity" / order 15，required_permissions `("h.site_health.read",)`，permission_manifest 两条（read/manage，文案照 §5.3），denied_behavior show_locked，**external_dependencies 留空元组**（H 不用外部密钥），execution_provider_required False
2. `backend/app/services/module_registry.py`：`INTL_TRADE_ONLY_MODULE_KEYS` 加 `"h.site_health"`（`:68`）
3. **权限注册表**（F/W 两次都漏过的坑，manifest 不会自动同步进 DB）：`backend/app/core/permissions.py` 的 `BASE_PERMISSION_REGISTRY_SEED` 加两条，格式照抄 `w.site_ops.read/manage` 那两条（就在文件里）：
   - `h.site_health.read`｜business/read｜label "Read site health"｜description "View site health runs, findings, and statistics."｜RISK_LEVEL_LOW｜SHOW_LOCKED
   - `h.site_health.manage`｜business/manage｜label "Manage site health"｜description "Trigger health runs and acknowledge or resolve findings."｜RISK_LEVEL_MEDIUM｜SHOW_LOCKED
4. `backend/app/main.py`：注册 h router（照 f 的 include_router 行）
5. `backend/app/core/dependency_bindings.py`：H 无外部依赖，**只在**硬编码边集合测试报错时按报错补零依赖登记（预期不用动；动了要在回报里说明）

**前端（六处，漏一处 = 模块隐身或测试红）：**
1. `frontend/src/app/api/backend/[...path]/route.ts`：新增 `isAllowedHPath`（照 `isAllowedFPath` 结构）：GET `/h/runs`、GET `/h/runs/{uuid}`、POST `/h/runs/trigger`、GET `/h/findings`、PATCH `/h/findings/{uuid}`；并加入主判定链（`isAllowedFPath(...) ||` 那一串）。**`/h/ingest` 不进白名单**（机器端点走 nginx 直达，台里配）
2. `frontend/src/lib/navigation.ts`：加 H 导航项（照 F 的条目）
3. `frontend/src/lib/frontend-capability-state.ts`：GROUPS/LABELS/ORDER 三个 map 加 `h.site_health`（label「H 站点健康」），并加进 `ACTION_SCOPED_EXECUTION_GATE_MODULE_KEYS` 豁免集
4. `frontend/src/lib/capability-sidebar-engine.tsx`：`ORGANIZATION_MODULE_PREFIXES` 加 `"h."`；`isRestrictedProductModule` 的产品系前缀集合加 `"h."`（否则侧边栏隐身——F/W 都栽过）
5. `tests/frontend/module-isolation.test.mjs`：nav 列表 + registry fixture 两处加 h 条目（照 f 条目抄）
6. 页面：`frontend/src/app/(console)/h-site-health/page.tsx`（照 f-enrichment 的 page.tsx 壳）+ `frontend/src/modules/h/sitehealth/{HealthDeck.tsx, api.ts, HealthDeck.module.css}`

### 页面结构（照 W-S ShippingDeck 骨架，零发挥）

- 统计卡行（4 张）：最近一次巡检状态 / 死链数（open 的 broken_link 数）/ 慢页数 / 巡检总 URL 数
- 主操作按钮：「立即巡检」（primary-button；触发后按钮 loading，台账 5 秒轮询直到该 run 终态——轮询写法照 F EnrichmentDeck 的 RUN_POLL_MS 模式）
- tab 三个：「待处理」（findings status=open）/「已确认」（acknowledged）/「运行台账」（runs 列表）
- findings 行：finding_type 徽章（文案见 §6）+ url（外链新开）+ status_code + response_ms + 操作按钮（open→「确认」「已解决」；acknowledged→「已解决」「重开」）
- runs 行：时间 + trigger 徽章（定时/手动）+ 状态徽章 + `{urls_ok}/{urls_total} 可用 · 死链 {urls_broken} · 慢页 {urls_slow} · P95 {p95_response_ms}ms`

## 6. 文案表（逐字使用）

| 位置 | 文案 |
|---|---|
| 页面标题 | `H 站点健康` |
| 统计卡 | `最近巡检` / `死链` / `慢页` / `巡检 URL 数` |
| 触发按钮 | `立即巡检` |
| 触发成功提示 | `巡检已发起，n8n 执行中——完成后台账自动更新` |
| 触发失败（502） | 直接显示后端 detail |
| tab | `待处理` / `已确认` / `运行台账` |
| finding_type 徽章 | broken_link→`死链` / slow_page→`慢页` / sitemap_error→`站点地图异常` / homepage_error→`首页异常` |
| findings 操作 | `确认` / `已解决` / `重开` |
| trigger 徽章 | scheduled→`定时` / manual→`手动` |
| run 状态徽章 | running→`巡检中` / completed→`完成` / failed→`失败` |
| 空态（待处理） | `没有待处理的异常——站点健康` |
| 空态（台账） | `还没有巡检记录。点「立即巡检」跑第一轮，或等每日定时任务。` |
| 告警标题模板（backend） | `站点巡检发现异常：死链 {urls_broken} 个` （sitemap_ok=false 时改用 `站点巡检发现异常：sitemap 不可用`；homepage_ok=false 时 `站点巡检发现异常：首页异常`，多种异常并存按此优先级取最严重的一条做标题） |

## 7. 环境变量（代码读取即可，生产值台里配）

| env | 用途 | 默认 |
|---|---|---|
| `N8N_H_HEALTH_WEBHOOK` | 手动触发的 n8n webhook URL | 空=触发端点 502 |
| `H_CALLBACK_BASE` | 拼 ingest 回传地址 | `http://console_backend:8000` |
| `H_INGEST_TOKEN` | ingest 鉴权 | 空=ingest 一律 403 |

## 8. 测试要求（全部 repo root）

```bash
bash scripts/run_backend_tests.sh unit          # 基线 484 绿
bash scripts/run_backend_tests.sh integration   # 基线 80 绿
cd frontend && npx tsc --noEmit && npm run test # 基线 191 绿
```

新增（照 F 的测试文件组织）：
1. `tests/backend/test_h_site_health.py`（integration）：ingest 全流程（建 run→ingest→统计列/findings 落库→告警产生一条 h.health_alert→重复 ingest deduped 且不重复告警）；findings 状态流转 + 越权 403；trigger 无 env → 502 且 run 标 failed；token 错 → 403
2. 权限测试：viewer role 全端点 403（照 `test_f_series_enrichment.py` 的 `test_f_endpoints_require_permission` 抄）
3. `tests/frontend/module-isolation.test.mjs` 契约同步（§5 前端第 5 条）
4. 迁移链：integration 通道天然验证；`test_pre20_p_staging_stabilization.py` 红了就按 §0.3 重新生成 manifest

## 9. 验收清单（回报时逐项贴结果）

- [ ] `git status` 只含允许清单内文件 + 新增 h 系列文件
- [ ] 迁移 `20260715_01_h_site_health` 链在 `20260714_04` 后，head 锁与 manifest 已更新
- [ ] `h.site_health.read/manage` 同时存在于 manifest、权限注册表种子、模块清单三处
- [ ] 侧边栏四件套（prefix/受限集/GROUPS/nav）全部登记
- [ ] HealthDeck.module.css 与 ShippingDeck.module.css 逐 diff 仅类名前缀差异
- [ ] 文案与 §6 逐字一致
- [ ] 三通道测试全绿（贴数字）
- [ ] commit：`feat(h): site health module (runs/findings/ingest/alerts)`，只含自己的文件

## 10. 回报格式

动了哪些文件、三通道数字、验收清单勾选、发现但未动的问题（只报告不越界）。n8n 巡检工作流（sitemap 爬取+URL 检查+回传）由台里在你交卷后编写并联调。
