# W-S 物流网络中枢 · Codex 施工指令（更名 + Woo 模板同步 + 订单轨迹）

> 交付人：Codex。验收人：用户 + Claude（按 §11 逐条验收）。
> 本文是**唯一需求来源**。前端所有文案、布局、CSS 已给定，逐字使用，禁止自创。
> 上一单（W-A 运费中枢）质量合格，本单延续同一纪律。

---

## 0. 背景与死命令

W-A 运费中枢已上线，现按用户拍板升级为 **W-S 物流网络中枢**，新增两大能力：
①控制台创建 Woo 运费模板并经 n8n 自动同步到 WooCommerce；②订单物流单号
管理 + 17TRACK 实时轨迹。

死命令（违反任何一条验收直接打回）：

1. **永不自动履约**。本模块只做：模板同步、订单展示、人工填单号、轨迹查询、
   信息回传。**不得**出现自动发货、自动购买面单、自动创建履约单的任何代码
   或预留接口。单号永远由用户人工填入。
2. **模块只挂国际贸易组织**（已生效的 INTL_TRADE_ONLY_MODULE_KEYS 与组织树
   规则不变，不要动）。
3. **Woo 的一切写操作走 n8n**（模板创建、订单单号回传）；**17TRACK 走
   console 直连**（数据采集类，有 keepa/serper 先例），密钥经密钥编排取用。

---

## 1. 范围

**做：**
- Part A：W-A → W-S 更名（显示名/文案/路由，内部 ID 不动）
- Part B：运费模板 1:1 表单 + n8n 同步契约 + 同步状态机
- Part C：`w_orders` 表 + n8n 订单 ingest + 单号管理 + 17TRACK 注册/webhook/轨迹 + Woo 回传
- 17track 外部依赖全套注册（§5，这次不能留空，照 F 的先例做全）
- migration（§6 有防双头协调，**必读**）
- 测试三通道全绿

**不做：**
- n8n 工作流本体（契约给足，用户自装）
- 自动轮询 17TRACK（省 200 次免费额度；只做 webhook 接收 + 手动刷新按钮）
- 不碰 `f_series/`、`c19/`、K 前端、globals.css（并行施工区）
- 不部署。交付 = 提交 main

---

## 2. Part A：更名 W-A → W-S 物流网络中枢

**不变**（稳定标识符，动了牵连权限记录）：module_key `w.site_ops`、权限 key
`w.site_ops.read/manage`、后端 api_namespace `/w`、表名。

**改**（精确清单）：
1. `backend/app/core/modules.py`：display_name → `W-S 物流网络中枢`；
   navigation.label 同；route_namespace → `/w-s`；description 更新（英文，提到
   logistics hub / shipping template sync / order tracking）；
   external_dependencies → `("17track",)`（§5 全套跟上）。
2. 前端目录 `frontend/src/app/(console)/w-a/` → `w-s/`（layout/page 移动）；
   原 `/w-a` 路径新建 `page.tsx` 只做 `redirect("/w-s")`（`next/navigation`）。
3. `frontend/src/lib/navigation.ts`：label/href/route_namespace 同步。
4. `frontend/src/lib/frontend-capability-state.ts`：LABELS map 值改
   `W-S 物流网络中枢`（GROUPS/ORDER/豁免集合不动）。
5. 页面 h1/副标题（§8 给定文案）。组件目录 `frontend/src/modules/w/siteops/`
   保持不动（内部路径无需改名）。
6. `tests/frontend/module-isolation.test.mjs` 中 route_namespace `/w-a` 的
   fixture 改 `/w-s`；`w-shipping-proxy.test.mjs` 不涉路由不用动。

---

## 3. Part B：运费模板 1:1 + n8n 同步

### 3.1 表扩展（进 §6 的同一个 migration）

`w_shipping_classes` 加列：

| 列 | 类型 | 语义 |
|---|---|---|
| description | Text nullable | Woo shipping class 描述 |
| zone_rates_json | JSON nullable | `[{"zone_name":"United States","base_cost":"4.99","class_cost":"2.00"}]`，区域名必须与 Woo 后台 zone 名一致 |
| sync_status | String(20) NOT NULL default 'draft' | draft / pending / synced / failed |
| woo_class_id | Integer nullable | n8n 回报的 Woo shipping class id |
| synced_at | DateTime(tz) nullable | |
| sync_error | Text nullable | |

新表 `w_sync_jobs`（照 `p_upload_jobs` 的骨架抄）：id BigInteger PK自增、
job_id String(64) unique、target_type String(30)（'shipping_class' /
'order_tracking'）、target_id Uuid、token String(128)、status String(16)
（pending/dispatched/success/failed）、payload_json JSON、error Text、
dispatched_at/finished_at/created_at/updated_at。索引 status、(target_type, target_id)。

### 3.2 同步契约（照 P 的一单一钥模式）

- 触发：模板 POST/PATCH 后用户点「同步到 Woo」（或新建时勾选「保存并同步」）
  → 建 job → POST 到 env `N8N_W_SYNC_WEBHOOK`（未配置则 job 停 pending）：
  ```json
  {
    "job_id": "...", "action": "upsert_shipping_class", "token": "...",
    "payload": {"slug": "...", "name": "...", "description": "...",
                 "woo_class_id": null, "zone_rates": [...]},
    "callback_url": "https://.../w/sync/{job_id}/result"
  }
  ```
- 回调：`POST /w/sync/{job_id}/result`（裸路径挂载 + X-Job-Token 鉴权，照
  `p_series/router.py` 的回报端点写法；**不进前端代理白名单**，并把它加进
  `tests/frontend/proxy-allowlist-drift.test.mjs` 的 KNOWN_UNPROXIED，注明
  server-to-server）。body：`{"status":"success|failed","woo_class_id":123,"error":null}`
  → 更新模板 sync_status/woo_class_id/synced_at。
- 幂等：success/failed 后重复回调不再处理。同一模板存在未完成 job 时拒绝
  再派（409 `该模板已有同步任务在执行中。`）。
- n8n 侧职责（写进契约注释，不实现）：调 Woo REST
  `POST/PUT /wp-json/wc/v3/products/shipping_classes`，再按 zone_rates 更新
  各 zone flat_rate method 的 class cost，回调结果。

### 3.3 UI（模板 tab 升级，文案见 §8）

- 列表新增「同步状态」列：`.statusBadge`，draft=草稿(青)/pending=同步中(橙)/
  synced=已同步(绿)/failed=失败(红, title=sync_error)；失败行给「重试」
  secondary 按钮。
- 表单新增：描述（textarea 一行式 input 即可）、区域费率行编辑（zone_name/
  base_cost/class_cost 三输入一行，「+ 加区域」添加行，行尾 ✕ 删除）。
- 按钮：「保存草稿」（secondary）、「保存并同步到 Woo」（primary）。

---

## 4. Part C：订单 + 单号 + 17TRACK 轨迹

### 4.1 `w_orders` 表（§6 migration）

| 列 | 类型 |
|---|---|
| id | Uuid PK |
| woo_order_id | Integer NOT NULL UNIQUE |
| order_number | String(64) NOT NULL |
| woo_status | String(30) NOT NULL |
| customer_name | String(255) nullable |
| country | String(8) nullable |
| total | Numeric(12,2) nullable |
| currency | String(8) nullable |
| items_json | JSON nullable（[{name, qty, sku}]） |
| placed_at | DateTime(tz) nullable |
| tracking_number | String(128) nullable |
| carrier_code | Integer nullable（17TRACK 数字承运商码，空=自动识别） |
| tracking_status | String(30) NOT NULL default 'none'（none=未填单号） |
| tracking_events_json | JSON nullable（轨迹事件数组，最新在前） |
| tracking_registered | Boolean NOT NULL default false |
| last_tracking_update | DateTime(tz) nullable |
| writeback_status | String(20) NOT NULL default 'none'（none/pending/success/failed） |
| created_at / updated_at | 照例 |

索引：tracking_status、woo_status、placed_at。
tracking_status 枚举（17TRACK v2.2 主状态归一）：`none / registered /
info_received / in_transit / out_for_delivery / delivered / exception /
expired / not_found`。

### 4.2 订单 ingest（n8n → console，server-to-server）

`POST /w/orders/ingest`：裸路径挂载，鉴权 = header `X-Ingest-Token` 与 env
`W_ORDERS_INGEST_TOKEN` 恒等比较（`secrets.compare_digest`，env 未配置一律
401）。body `{"orders":[{...上表字段的 woo 子集...}]}`，按 woo_order_id
upsert（**不得覆盖** console 侧的 tracking_* 字段）。加进 drift 测试
KNOWN_UNPROXIED。n8n 侧职责（注释）：定时拉 Woo orders（processing/completed）
推送过来。

### 4.3 填单号 → 双动作

`PATCH /w/orders/{id}/tracking` body `{"tracking_number":"...","carrier_code":null}`
（manage 权限）：
1. 存单号 → tracking_status='registered' 前先做第 2 步；
2. **17TRACK 注册（console 直连）**：`POST {base}/track/v2.2/register`，
   header `17token: <key>`，body `[{"number":"...","carrier":carrier_code?}]`。
   成功 → tracking_registered=true、tracking_status='registered'；额度不足或
   失败 → 单号照存，tracking_status='not_found'，返回体带
   `"tracking_warning": "17TRACK 注册失败：..."`（不阻塞填单号）。
   ⚠️ 慢 HTTP 前先 `db.rollback()`（仓库铁律）。
3. **回传 Woo（n8n）**：建 `w_sync_jobs`（action=`order_tracking`，payload=
   {woo_order_id, tracking_number, carrier_label}）→ 派 `N8N_W_SYNC_WEBHOOK`
   → 回调更新 writeback_status。n8n 侧职责（注释）：写 Woo 订单 note/meta。

清空/改单号：允许重 PATCH；改号重新注册（新号消耗新额度，UI 文案里提醒）。

### 4.4 17TRACK webhook（轨迹自动更新）

`POST /w/tracking/webhook`：裸路径 + KNOWN_UNPROXIED。签名校验按 17TRACK
v2.2 官方规范实现（请求头 `sign`，SHA-256 组合 payload 与 api key——**落地时
以官方文档为准核对精确格式**；拿不到文档就实现为可配置：env
`W_17TRACK_WEBHOOK_SIGN_MODE=sha256|off`，默认 sha256，校验失败 401）。
处理 `TRACKING_UPDATED` 事件：按 number 找 w_orders → 更新 tracking_status
（17TRACK 主状态映射到 §4.1 枚举）、tracking_events_json（保留最近 50 条：
time/location/description）、last_tracking_update。幂等：重复事件按
last_tracking_update 时间去重。

### 4.5 手动刷新

`POST /w/orders/{id}/refresh-tracking`（read 权限即可）：console 直连
`POST {base}/track/v2.2/gettrackinfo`（查询不耗注册额度），更新同 §4.4。
17TRACK key 缺失时返回 409 `17TRACK 密钥未绑定（去密钥管理添加）。`

### 4.6 密钥取用

照 F 的先例（`f_series/enrichment/runs.py` 的 `_serper_key`）：
`SecretManager(db_session=db).get_key("17track", org_id)`，org_id 按
`国际贸易组织名` 解析。base url 读 env `W_17TRACK_BASE_URL`，默认
`https://api.17track.net`。

### 4.7 UI：新增「订单与物流」tab（放在「产品台账」左边，作为第一个 tab）

- 统计行改为：`待填单号`（tracking_status=none 数，data-tone="failed"）、
  `运输中`（registered/info_received/in_transit/out_for_delivery，橙）、
  `已签收`（delivered，绿）、`异常`（exception/expired/not_found，红）。
- 子筛选（照台账 filter 按钮样式）：`待填单号 / 已填单号 / 全部`。
- 表格列：`订单`（order_number + customer_name 两行，.productCell 样式）|
  `国家` | `金额`（currency+total）| `商品`（items 首件名 + `等 N 件`，
  title=全列表）| `下单时间`（.timeCell）| `运单号`（未填=行内 input+
  「保存」小按钮；已填=单号文本 + tracking_status 徽章）| `轨迹`（已填时
  「查看」linkButton 展开行下方时间线 + 「刷新」secondary 小按钮）|
  `回传`（writeback_status 徽章）。
- 轨迹时间线：展开行内简单列表（时间 + 地点 + 描述，最新在上，最多 50 条），
  样式用 `.mutedLine` 体系，不新造组件库。
- 空态文案见 §8。

---

## 5. 17track 外部依赖注册（全套，不许留空）

照 F 系列 serper/alibaba1688 的完整先例，六处：

1. `backend/app/core/key_registry.py`：注册 `17track` 服务，default_url
   `https://api.17track.net`（照 serper 条目的写法，含别名归一）。
2. `backend/app/core/external_dependencies.py`：EXTERNAL_SERVICE_REGISTRY_V1
   加 `17track` 条目（service_id/display/category=data_acquisition，照 serper）。
   ⚠️ module key 校验规则若拒绝数字开头的 service id，则统一用 `track17`
   作为 service_id（display 名仍写 17TRACK），**六处保持同一 id**。
3. `backend/app/core/dependency_bindings.py` 两处：MODULE_SERVICE_BINDINGS_V1
   加 `{"module_key":"w.site_ops","service_id":"17track","binding_status":
   "restricted","allowed_capabilities":["data_acquisition"],"reason":"W-S
   logistics pulls shipment tracking through the 17TRACK API."}`；
   MODULE_CAPABILITY_BINDINGS_V1 加 w.site_ops（data_acquisition）。
4. `backend/app/core/modules.py`：w.site_ops manifest 的
   external_dependencies=("17track",)。
5. `tests/backend/test_dependency_binding_rules.py`：边数 25→26，集合里加
   `("w.site_ops","17track","data_acquisition")`。
6. `SERVICE_CAPABILITY_MAPPINGS_V1` 若要求每个 service 有能力映射（对照
   serper 是否单列），照 serper 的形状补一条。

---

## 6. migration 防双头协调（⚠️ 本单最高风险点）

Claude 正在并行施工 F 系列（revision `20260713_03_f_category_experience`）。
仓库出过两次双头事故，规矩：

1. 开工第一步：`ls backend/alembic/versions/ | tail -5` + 确认唯一 head。
2. 你的 migration 命名 `20260714_01_w_logistics_hub`，**down_revision 必须
   接当时的唯一 head**——正常情况是 `20260713_03_f_category_experience`；
   若该文件尚未出现，**停下来问用户**，不要接 20260713_02 抢链位。
3. 提交前重新生成 manifest 并同步 `EXPECTED_ALEMBIC_HEAD`
   （scripts/staging_stabilization.py），命令：
   ```bash
   .venv/bin/python -c "
   import sys; sys.path.insert(0, '.')
   from scripts import staging_stabilization as st
   st.write_json(st.MIGRATION_MANIFEST_FILE, st.build_migration_manifest())"
   ```
4. 提交前 `git status` 复查没卷进 f_series/c19 文件。

---

## 7. 工程红线（仓库踩坑清单，逐条遵守）

1. C18G：裸 SQL 必须带 org_id 或包 `without_org_data_isolation()`；优先 ORM。
2. User.id 是 **int**（BigInteger），不是 UUID。
3. 慢 HTTP（17TRACK/n8n webhook POST）前先 `db.rollback()`。
4. 裸路径 server-to-server 端点（ingest/回调/webhook）不进前端代理白名单，
   但必须进 drift 测试 KNOWN_UNPROXIED 并写理由。
5. 鉴权依赖复用现成 `_require_w_permission`（W-A 已有），manage 隐含 read。
6. 新前端 API 路径进 `isAllowedWPath`（route.ts）+ `w-shipping-proxy.test.mjs`
   allow/deny 各补齐。
7. 侧边栏可见性六处已就位（w. 前缀/豁免集合），只改 label 不新增模块，
   **不要动 capability-sidebar-engine.tsx**。

---

## 8. 前端给定文案（逐字使用）

- 页面标题 h1：`W-S 物流网络中枢`
- 页面副标题：`运费模板在这里创建、经 n8n 同步进 WooCommerce；订单与物流单号在这里管理，17TRACK 轨迹自动回流。发货永远是人工决定——这里只做看得清、传得快。`
- tab 名：`订单与物流` / `产品台账` / `分配规则` / `运费模板` / `试算器`
- 订单 tab 空态：`还没有订单数据。n8n 的订单同步流配置好后，Woo 订单会自动出现在这里。`
- 待填单号提示（统计卡下方 notice，仅当待填>0）：`有 {n} 个订单等待填写运单号——填入后自动注册 17TRACK 轨迹并回传 Woo 订单。`
- 单号输入 placeholder：`填入运单号，如 YT2513…`
- 刷新轨迹按钮：`刷新轨迹`；查看轨迹：`查看轨迹`；收起：`收起`
- 改单号确认 title：`更换运单号会重新消耗一次 17TRACK 注册额度`
- 模板同步按钮：`保存并同步到 Woo` / `保存草稿` / 失败行 `重试同步`
- 模板 tab 说明行（替换原有）：`slug 必须与 WooCommerce 后台的运费类别 slug 完全一致；「保存并同步到 Woo」会经 n8n 直接写入 Woo 后台，区域名需与 Woo 配送区域名一致。`
- 轨迹状态中文映射：none=待填单号 / registered=已登记 / info_received=已揽收 /
  in_transit=运输中 / out_for_delivery=派送中 / delivered=已签收 /
  exception=异常 / expired=查询过期 / not_found=暂无轨迹
- 回传状态：none=— / pending=回传中 / success=已回传 / failed=回传失败

CSS：继续只用 `ShippingDeck.module.css` 现有类 + 从 F/P 模块 CSS 逐字复制；
新增类只做布局；颜色只用既有白名单。禁止 emoji/alert/inline style。

---

## 9. 测试要求

`tests/backend/test_w_logistics_hub.py`（integration，fixture 照 w_env）：
1. 模板同步：建模板→派单（mock urllib 到 n8n）→回调 success 更新状态；
   重复回调幂等；in-flight 期间再派 409；回调坏 token 403。
2. ingest：token 鉴权（无/错=401）；upsert 不覆盖 tracking_* 字段。
3. 填单号：mock 17TRACK register 成功→registered；失败→单号保存+warning；
   同时建 order_tracking 回传 job。
4. webhook：合法签名事件更新状态与事件列表；坏签名 401；重复事件去重。
5. refresh-tracking：mock gettrackinfo 更新；无 key 409。
6. 更名：`/w-a` 路由 redirect 到 `/w-s`（前端测试断言 page 源码含 redirect）。
7. 权限：viewer 全端点 403。
8. 依赖绑定：test_dependency_binding_rules 边集合更新后全绿。

三通道命令与全绿要求同上单。**未部署，交付=一个 commit**：
`feat(w): logistics hub with Woo template sync and 17TRACK tracking (W-S cut 2)`

---

## 10. n8n 侧契约摘要（写给用户的接入说明，放文件尾注释即可）

用户需自建两条 n8n 流：
1. **W 同步流**（webhook 接 §3.2/§4.3 payload）：action=upsert_shipping_class
   → Woo API 建/改 shipping class + zone 费率；action=order_tracking → 写
   Woo 订单跟踪信息；完成后 POST callback_url（带 token）。
2. **订单拉取流**（定时）：拉 Woo orders → POST `/w/orders/ingest`
   （header X-Ingest-Token）。
env 清单：`N8N_W_SYNC_WEBHOOK`、`W_ORDERS_INGEST_TOKEN`、
`W_17TRACK_BASE_URL`（默认已填）、17track key 走密钥管理绑定。

---

## 11. 验收清单（Claude 逐条对照）

- [ ] 死命令三条无违反（重点：全仓 grep 无自动履约/自动面单痕迹）
- [ ] migration 单头、接链正确、manifest+EXPECTED_ALEMBIC_HEAD 同步
- [ ] 更名后 /w-a 平滑跳转、侧边栏 label 正确、模块 ID/权限未动
- [ ] 模板同步契约与状态机照 §3.2；回调幂等；n8n 未配置时优雅停 pending
- [ ] 填单号双动作（17TRACK 注册 + Woo 回传 job）且失败不阻塞
- [ ] webhook 签名校验 + 状态映射 + 去重
- [ ] 17track 依赖六处注册齐全，两个硬编码测试更新
- [ ] UI 文案逐字、视觉与现有驾驶舱不可区分
- [ ] 三通道全绿；未部署
